"""F-15(手動)/F-13-1: T2Iワーカー(基本設計5.5節/5.3節)"""

import os
import threading
import time

from PIL import Image, ImageDraw, ImageFont

from def_kari.core.events import (
    make_event,
    EVENT_IMAGE_COMPLETE,
    EVENT_SYSTEM_NOTIFICATION,
)

ASSET_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "assets")


def _generate_placeholder_image(
    path: str,
    emotion: str,
    prompt: str = "",
    width: int = 512,
    height: int = 768,
) -> str:
    """プレースホルダー画像を生成する(MVP仮実装)。実T2I連携時に置き換える。"""
    colors = {"neutral": "#888888", "happy": "#FFD700", "angry": "#FF4444", "sad": "#4444FF"}
    color = colors.get(emotion, "#888888")
    img = Image.new("RGB", (width, height), color)
    draw = ImageDraw.Draw(img)
    label = f"{emotion}\n{prompt[:60]}" if prompt else emotion
    try:
        draw.text((10, 10), label, fill="white")
    except Exception:
        pass
    img.save(path)
    return path


def handle_image_task(
    task: dict,
    result_q,
    vram_lock: threading.Lock,
) -> None:
    """task = {"kind": "image", "msg_id": str, "emotion": str, "image_prompt_en": str, ...}
    vram_lock取得 → 生成 → IMAGE_COMPLETE → vram_lock解放の順で処理する。"""
    msg_id = task["msg_id"]
    emotion = task.get("emotion", "neutral")
    image_prompt_en = task.get("image_prompt_en", "")
    width = task.get("t2i_width", 512)
    height = task.get("t2i_height", 768)

    from def_kari.models.t2i_profiles import get_quality_settings
    _model_name = task.get("t2i_model")
    _quality_tags, _negative_prompt = get_quality_settings(_model_name)
    if _quality_tags:
        image_prompt_en = ", ".join(filter(None, [image_prompt_en, _quality_tags]))

    vram_lock.acquire()
    result_q.put(make_event(EVENT_SYSTEM_NOTIFICATION, {
        "msg_id": msg_id,
        "message": "vram_lock acquired (T2I開始)",
    }))

    try:
        _save_to = task.get("_save_to")
        if _save_to:
            os.makedirs(os.path.dirname(_save_to), exist_ok=True)
            path = _save_to
        else:
            os.makedirs(ASSET_DIR, exist_ok=True)
            filename = f"{msg_id}_{int(time.time() * 1000)}.png"
            path = os.path.join(ASSET_DIR, filename)

        t2i_backend = task.get("t2i_backend")
        if t2i_backend:
            try:
                from def_kari.workers._t2i_generate import generate_image
                generated_path = generate_image(
                    prompt=image_prompt_en,
                    width=width,
                    height=height,
                    model_name=task.get("t2i_model"),
                    backend=t2i_backend,
                    negative_prompt=_negative_prompt,
                )
                if _save_to:
                    import shutil
                    _abs_save = os.path.abspath(_save_to)
                    os.makedirs(os.path.dirname(_abs_save), exist_ok=True)
                    shutil.copy2(generated_path, _abs_save)
                    path = _abs_save
                    print(f"[T2I] Copied to: {_abs_save}")
                else:
                    path = generated_path
            except Exception as _t2i_err:
                import traceback
                traceback.print_exc()
                _generate_placeholder_image(path, emotion, image_prompt_en, width, height)
                _t2i_error = str(_t2i_err)
            else:
                _t2i_error = None
        else:
            _t2i_error = None
            _generate_placeholder_image(path, emotion, image_prompt_en, width, height)

        _payload = {"msg_id": msg_id, "image_path": path}
        if _t2i_error:
            _payload["error"] = _t2i_error
        result_q.put(make_event(EVENT_IMAGE_COMPLETE, _payload))
    except Exception as exc:
        result_q.put(make_event("IMAGE_FAILED", {
            "msg_id": msg_id,
            "error": str(exc),
        }))
    finally:
        vram_lock.release()
        result_q.put(make_event(EVENT_SYSTEM_NOTIFICATION, {
            "msg_id": msg_id,
            "message": "vram_lock released (T2I完了)",
        }))
