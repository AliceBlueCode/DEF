"""Sessionの T2I 画像生成: appearance_tags 適用・シーンプロンプト生成・生成エンドポイント。
`session.py`分割の一部。
"""

import os
import re

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel

from def_kari.characters import load_profiles, get_character
from def_kari.llm.backend import LLM_BACKENDS, DEFAULT_LLM_BACKEND
from def_kari.safety.filters import character_rating_exceeds_invite
from def_kari.safety.audit_log import record_generation_event
from def_kari.t2i.backend import generate_image as _generate_t2i_image
from def_kari.gm.events import game_event_bus as _game_event_bus

from def_kari.api.routes.session_state import router, _sessions
from def_kari.api.routes.session_auth import (
    require_player,
    _resolve_client_ip,
    _check_circuit_breaker,
    _check_generation_rate,
    _check_daily_generation_limit,
    _try_acquire_generation_lock,
    _release_generation_lock,
    _record_violation_and_maybe_trip,
    _extract_content_policy_from_json,
)
from def_kari.api.routes.session_persistence import _autosave

_VRAM_LOCK_TIMEOUT_SECONDS = float(os.environ.get("DEF_VRAM_LOCK_TIMEOUT", "60"))


def _resolve_model(backend_id: str, req_model: str = "") -> str:
    """バックエンドに対応するモデル名を解決する。

    優先順位: リクエスト指定 > 設定ファイル(llm_ext_model_{backend_id}) > バックエンドデフォルト
    """
    if req_model:
        return req_model
    try:
        from def_kari.settings import load_settings
        per_backend = load_settings().get(f"llm_ext_model_{backend_id}", "")
        if per_backend:
            return per_backend
    except Exception:
        pass
    from def_kari.llm.backend import LLM_BACKENDS
    return LLM_BACKENDS.get(backend_id, {}).get("default_model", "")


def _apply_char_tags(prompt: str, char_id: str | None, profiles: dict | None = None) -> str:
    """appearance_tags・image_name_tags・LoRA をプロンプトに適用する。
    name_tags を先頭、appearance_tags を追加、LoRA 構文を末尾に付加。"""
    if not char_id:
        return prompt
    if profiles is None:
        profiles = load_profiles()
    _char = get_character(char_id, profiles)
    _app_tags = _char.get("appearance_tags", "").strip()
    _name_tags = _char.get("image_name_tags", "").strip()
    _lora = _char.get("lora") or []

    _clean = re.sub(r'<lora:[^>]+>', '', prompt).strip().strip(',').strip()
    _existing = [t.strip() for t in _clean.split(',') if t.strip()]
    _existing_lower = {t.lower() for t in _existing}

    _prefix_raw = [t.strip() for t in (_name_tags + ',' + _app_tags).split(',') if t.strip()]
    _prefix = [t for t in _prefix_raw if t.lower() not in _existing_lower]

    from def_kari.characters import build_lora_prompt
    _lora_str = build_lora_prompt(_lora)

    result = ', '.join(_prefix + _existing)
    if _lora_str:
        result = (result + ' ' + _lora_str).strip()
    return result


class SessionGenerateImageRequest(BaseModel):
    backend: str = DEFAULT_LLM_BACKEND
    t2i_backend: str = ""
    t2i_model: str = ""
    t2i_prompt_mode: str = ""


@router.post("/{session_id}/generate-image")
def generate_session_image(session_id: str, req: SessionGenerateImageRequest, request: Request, _auth: dict = Depends(require_player)):
    """レート制限＋in-flight排他制御を課した上で実際の生成処理へ委譲する。

    generate-image は課金API呼び出し・GPU時間を消費する実コストの高い
    操作であるため、WS発言用の `_check_ws_rate` とは別の専用バケットで
    頻度を制限し（1参加者あたり6回/分）、加えて同一参加者からの
    多重同時実行（in-flight）を防ぐ。

    jti単位の制限に加えてIPベースの制限も併用する（8.6対策）。/joinは同一招待コードの
    使い回しがオンラインセッションの仕様上OKで、そのたびに新しいjtiのトークンが
    発行されるため、jti単位の制限だけでは正規の招待コード保持者がjoinを繰り返して
    使い捨てトークンで際限なく回避できてしまう。IP単位の上限（1分あたり20回、
    jti単位より緩め）を素通りできないバケットとして併設し、jti単位のバイパスを防ぐ。
    """
    gen_key = _auth.get("jti") or str(_auth)
    client_ip = _resolve_client_ip(request)
    if not _check_circuit_breaker(session_id):
        raise HTTPException(423, "Generation for this session is paused due to unusual activity. Ask the host to review the audit log and reset it.")
    if not _check_generation_rate(session_id, gen_key):
        _record_violation_and_maybe_trip("generate_session_image", session_id, client_ip, gen_key)
        raise HTTPException(429, "Too many image generation requests. Please wait a moment.")
    if not _check_generation_rate(session_id, f"ip:{client_ip}", limit=20):
        _record_violation_and_maybe_trip("generate_session_image", session_id, client_ip, gen_key)
        raise HTTPException(429, "Too many image generation requests from this network. Please wait a moment.")
    if not _check_daily_generation_limit(session_id):
        raise HTTPException(429, "This session has reached its daily generation limit.")
    if not _try_acquire_generation_lock(session_id, gen_key):
        raise HTTPException(429, "An image is already being generated for you. Please wait for it to finish.")
    record_generation_event("generate_session_image", session_id, client_ip, gen_key)
    try:
        return _generate_session_image_impl(session_id, req)
    finally:
        _release_generation_lock(session_id, gen_key)


def _generate_session_image_impl(session_id: str, req: SessionGenerateImageRequest):
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}

    history = session.get("history", [])
    initiative = session.get("initiative", [])
    actions_per_turn = session.get("actions_per_turn", 2)
    name_map = session.get("name_map", {})
    topic = session.get("topic", "")
    scene = session.get("scene", "")

    # 直近ラウンドの発言を取得
    round_size = max(len(initiative) * actions_per_turn, 1)
    last_round = [h for h in history[-round_size * 2:] if h.get("role") == "assistant"][-round_size:]

    from def_kari.settings import load_settings as _load_settings
    _settings = _load_settings()
    t2i_prompt_mode = req.t2i_prompt_mode or _settings.get("t2i_prompt_mode", "current")
    from def_kari.models.t2i_profiles import get_current_tag_format as _get_tag_fmt
    _tag_format = _get_tag_fmt()
    _is_tag_based = _tag_format in ("danbooru", "e621")
    _fmt_label = {"danbooru": "Danbooru", "e621": "e621", "natural": "natural language", "other": "English"}.get(_tag_format, "Danbooru")

    def _dedup_tags(prompt: str, max_tags: int = 256) -> str:
        raw = [t.strip() for t in prompt.split(',') if t.strip()]
        seen: set[str] = set()
        unique: list[str] = []
        for t in raw:
            k = t.lower()
            if k not in seen:
                seen.add(k)
                unique.append(t)
        return ', '.join(unique[:max_tags])

    # TRPGモード: initiative からランダム1人 / 通常: 最後の発言者
    import random as _random
    _pc_ids = [cid for cid in initiative if not cid.startswith("_")]
    if session.get("trpg_mode") and _pc_ids:
        _scene_char_id = _random.choice(_pc_ids)
    else:
        _scene_char_id = last_round[-1].get("character_id") if last_round else None

    # 持ち込みキャラ(guest_chars)については、参加時に許可された招待コードの
    # レーティング上限をセッション内T2I生成でも引き続き適用する（join_session参照）。
    # ロスターキャラ（ホストが用意した既存キャラ）は対象外——ホストが自ら
    # 選んだキャラのため、ここでは持ち込みキャラの取り込み経路のみを塞ぐ。
    _guest_char_data = session.get("guest_chars", {}).get(_scene_char_id)
    if _guest_char_data:
        _scene_content_policy = _extract_content_policy_from_json(_guest_char_data)
        _scene_session_rating = session.get("guest_char_ratings", {}).get(_scene_char_id, "SFW")
        if character_rating_exceeds_invite(_scene_content_policy, _scene_session_rating):
            return {"error": "Image generation blocked: this character's rating exceeds the rating it joined under"}

    if t2i_prompt_mode == "passthrough":
        # LLM不使用: history の image_prompt_en を直接流用
        try:
            _ip_parts = [h.get("image_prompt_en", "") for h in last_round if h.get("image_prompt_en")]
            image_prompt = ", ".join(_ip_parts)
            if not image_prompt and scene:
                image_prompt = scene
            image_prompt = _apply_char_tags(image_prompt, _scene_char_id)
            image_prompt = _dedup_tags(image_prompt)
        except Exception as e:
            return {"error": f"image prompt (passthrough) failed: {e}"}

    else:
        # current / dedicated: LLM経由でタグ生成
        dialogue_block = "\n".join(
            f"{name_map.get(h.get('character_id', ''), h.get('character_id', ''))}: "
            f"{h.get('content', '').split(': ', 1)[-1]}"
            for h in last_round
        ) if last_round else ""

        scene_line = f"Base scene: {scene}" if scene else ""
        topic_line = f"Session topic: {topic}" if topic else ""
        dialogue_line = f"Recent dialogue (for character count and mood):\n{dialogue_block}" if dialogue_block else ""

        if t2i_prompt_mode == "dedicated":
            # dedicated: 出力制約を強化（thinkingモデル対策）
            if _is_tag_based:
                system_prompt = (
                    f"Scene tag generator for Stable Diffusion. Output comma-separated {_fmt_label} tags ONLY. "
                    "CHARACTER APPEARANCE IS ALREADY SET — DO NOT output hair color, eye color, clothing, body type. "
                    "Output ONLY: setting, background, weather, time of day, lighting, composition, camera angle, "
                    "character count, pose, action, expression/emotion. "
                    "Start with the first tag immediately. No prose, no reasoning."
                )
                user_text = "\n".join(filter(None, [scene_line, topic_line, dialogue_line])) + (
                    f"\n\nIMMEDIATELY output 8-15 scene {_fmt_label} tags, comma-separated. "
                    "SCENE & ENVIRONMENT ONLY — no hair/eye/clothing tags. "
                    "NO explanation. NO reasoning. First token must be a tag."
                )
            else:
                system_prompt = (
                    "Scene description generator for Stable Diffusion. "
                    "Output a concise English visual description of SETTING, LIGHTING, and ACTION ONLY. "
                    "CHARACTER APPEARANCE IS ALREADY SET — do not describe hair, eyes, or clothing. "
                    "No reasoning, no abstract concepts."
                )
                user_text = "\n".join(filter(None, [scene_line, topic_line, dialogue_line])) + (
                    "\n\nIMMEDIATELY output a short English scene description (1-3 sentences). "
                    "Describe setting, lighting, mood, and action only. NO character appearance. "
                    "NO explanation. NO reasoning. Start with the description directly."
                )
            num_predict = 128
        else:
            # current
            if _is_tag_based:
                system_prompt = (
                    f"You are a scene tag generator for Stable Diffusion. "
                    f"Output ONLY {_fmt_label}-style tags, comma-separated. "
                    "CHARACTER APPEARANCE IS ALREADY SET — DO NOT output hair color, eye color, clothing, body type. "
                    "Output ONLY: setting, background, lighting, weather, time of day, composition, "
                    "camera angle, character count, pose, action, expression/emotion. "
                    "Do NOT think out loud. Do NOT explain. Output tags immediately."
                )
                user_text = "\n".join(filter(None, [scene_line, topic_line, dialogue_line])) + (
                    f"\n\nOutput ONLY {_fmt_label}-style scene tags in English, comma-separated. "
                    "SCENE & ENVIRONMENT ONLY — no hair/eye/clothing tags. "
                    "Include: setting, lighting, mood, pose/action, expression. "
                    "No explanation. No reasoning. Tags only."
                )
            else:
                system_prompt = (
                    "You are a scene description generator for Stable Diffusion. "
                    "Output ONLY a concise English description of SETTING, LIGHTING, and ACTION. "
                    "CHARACTER APPEARANCE IS ALREADY SET — do not describe hair, eyes, or clothing. "
                    "Do NOT think out loud. Do NOT explain. Output the description immediately."
                )
                user_text = "\n".join(filter(None, [scene_line, topic_line, dialogue_line])) + (
                    "\n\nOutput ONLY a short English scene description (2-4 sentences). "
                    "Describe setting, lighting, mood, and character action/emotion. NO character appearance. "
                    "No explanation. No reasoning. Visual details only."
                )
            num_predict = 256

        backend_id = req.backend or session.get("backend", DEFAULT_LLM_BACKEND)
        if backend_id not in LLM_BACKENDS:
            backend_id = DEFAULT_LLM_BACKEND

        try:
            chat_fn = LLM_BACKENDS[backend_id]["chat"]
            model = _resolve_model(backend_id)
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ]
            from def_kari.resources.vram_lock import get_vram_lock
            _vram_lock_llm = get_vram_lock()
            if not _vram_lock_llm.acquire(timeout=_VRAM_LOCK_TIMEOUT_SECONDS):
                raise RuntimeError(f"vram_lock busy for over {_VRAM_LOCK_TIMEOUT_SECONDS:.0f}s")
            try:
                image_prompt = chat_fn(messages, model, json_mode=False, options={"num_predict": num_predict})
            finally:
                _vram_lock_llm.release()
            image_prompt = re.sub(r'#(\w)', r'\1', image_prompt).strip().strip('"').strip("'")
            image_prompt = _apply_char_tags(image_prompt, _scene_char_id)
            if _is_tag_based:
                image_prompt = _dedup_tags(image_prompt)
        except Exception as e:
            return {"error": f"image prompt generation failed: {e}"}

    if not image_prompt:
        return {"error": "empty image prompt"}

    try:
        from def_kari.settings import load_settings
        from def_kari.api.routes.t2i import set_t2i_debug
        settings = load_settings()
        t2i_backend = req.t2i_backend or settings.get("t2i_backend", "")
        if not t2i_backend:
            return {"error": "T2Iバックエンドが未設定です"}
        t2i_model = req.t2i_model or settings.get(f"t2i_model_{t2i_backend}") or None
        workflow = settings.get("comfyui_workflow", "default") if t2i_backend == "comfyui" else ""
        width = int(settings.get("session_t2i_width") or settings.get("t2i_width", 512))
        height = int(settings.get("session_t2i_height") or settings.get("t2i_height", 768))
        from def_kari.models.t2i_profiles import get_quality_settings
        quality_tags, default_neg = get_quality_settings(t2i_model)
        prompt_final = f"{image_prompt}, {quality_tags}" if quality_tags else image_prompt
        t2i_debug = {
            "backend": t2i_backend,
            "model": t2i_model or "",
            "workflow": workflow,
            "t2i_prompt_mode": t2i_prompt_mode,
            "prompt_input": image_prompt,
            "quality_tags": quality_tags,
            "prompt_final": prompt_final,
            "negative_prompt": default_neg,
            "width": width,
            "height": height,
        }
        set_t2i_debug(t2i_debug)
        from def_kari.resources.vram_lock import get_vram_lock
        _vram_lock = get_vram_lock()
        if not _vram_lock.acquire(timeout=_VRAM_LOCK_TIMEOUT_SECONDS):
            raise RuntimeError(f"vram_lock busy for over {_VRAM_LOCK_TIMEOUT_SECONDS:.0f}s")
        try:
            image_path = _generate_t2i_image(
                prompt=prompt_final,
                width=width,
                height=height,
                model=t2i_model,
                backend=t2i_backend,
                negative_prompt=default_neg,
                workflow_name=workflow,
            )
        finally:
            _vram_lock.release()
        filename = image_path.split("/")[-1].split("\\")[-1]
        image_url = f"/api/t2i/image/{filename}"
        t2i_debug["url"] = image_url
        set_t2i_debug(t2i_debug)
        session.setdefault("history", []).append({
            "character_id": "_scene_image",
            "content": "",
            "image_url": image_url,
        })
        _autosave(session_id)
        _game_event_bus.emit(session_id, "SESSION_IMAGE", {"url": image_url})
        return {"url": image_url, "prompt": prompt_final}
    except Exception as e:
        return {"error": str(e)}
