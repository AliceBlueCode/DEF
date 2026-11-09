"""セッション進行の「純粋な手番の状態遷移」（2026-11-09、セッション進行のリファクタリング Step 2 の A）。

session 辞書を受け取って書き換える（または読む）だけの関数を集めたモジュール。I/O（自動保存）・
イベントの配信・タスクの起動は持たない（それらは session_turn_engine.py）。手番の状態のキー
（turn・round・_round_seq・_round_spoken・action_count・指名・_skip_gen・initiative の除外）を
書き換えてよいのは、このモジュールと session_turn_engine.py だけ（tests/test_session_key_ownership.py）。

session_turn_engine.py から移しただけで、中身は変えていない。判定の待ち合わせ（v5.0）のように
「ターンの進行を止める理由」を足すときは、_turn_progress_blocked をここで広げる。
"""

from __future__ import annotations

from fastapi import HTTPException

from def_kari.characters import load_profiles, get_character


def _is_human_char(session: dict, char_id: str, profiles: dict | None = None) -> bool:
    """セッション内で人間扱いかどうかを返す。

    human_char_ids（Phase 3以降）に含まれていれば人間。
    未設定の場合は profiles の player_type にフォールバック。

    以前はguest_chars（持ち込みキャラ）を無条件に人間扱いするフォールバックが
    別途あったが、join_session（session_lobby.py）はcharacter_json持ち込み時
    必ずrole="player"を割り当て、その直後に同じ関数内でhuman_char_idsへも
    追加している（human_char_idsとguest_charsは常に対で揃う）ため、実質的に
    完全な重複だった。しかもこのフォールバックはhuman_char_idsからの明示的な
    除去（ai_takeover・投票expelの「AIに引き継ぐ」）を無視して常にTrueを返し
    続けてしまい、持ち込みキャラに対するAI引き継ぎ機能そのものを無効化する
    実害があった（2026-08-22、投票expelでAI引き継ぎを選んでもセッションが
    進まなくなる不具合として発覚——原因はAIターン再開そのものではなく、
    ここで対象がずっと人間のまま判定され続けていたこと）。
    """
    if char_id in session.get("human_char_ids", []):
        return True
    if profiles is None:
        profiles = load_profiles()
    char = get_character(char_id, profiles)
    return bool(char and char.get("player_type") == "human")


def _get_current_speaker(session: dict) -> str | None:
    """現在のターンのキャラIDを返す。ラウンド境界は % で吸収。"""
    initiative = session.get("initiative", [])
    if not initiative:
        return None
    turn = session.get("turn", 0)
    return initiative[turn % len(initiative)]


def _mark_spoken_and_check_round_complete(session: dict, char_id: str) -> bool:
    """指定キャラがこのラウンドで発言/skip済みであることを記録し、initiativeの
    全員が出そろったらTrueを返す（このラウンドの発言済み集合はTrue時にリセットする）。

    以前はフロントエンド側で「initiative配列の末尾のキャラが喋ったか」という
    ヒューリスティックのみでキーパーの発言タイミングを判定していたが、指名
    （designate、`session["turn"] = initiative.index(designated)`で配列順を
    無視して直接ジャンプする）が絡むと、配列末尾のキャラが一度もそのラウンド中に
    発言しないまま次ラウンドへ巻き戻ることがあり、そのラウンドのキーパー発言が
    何のエラーも無く握り潰されていた（2026-08-23、実機で発覚）。initiativeの
    並び順・turnのモジュロ演算に依存しない、サーバー側の権威データとして
    「誰が発言済みか」の集合を管理する。

    戻り値がTrueの回にサーバーが払い出す`_round_seq`（呼び出し側で加算）を
    フロントの重複発火ガードに使う想定（`session["round"]`自体はこの判定とは
    独立して別経路で遅延更新されるため、ラウンド境界の識別子としては使えない）。
    """
    spoken: list = session.setdefault("_round_spoken", [])
    if char_id not in spoken:
        spoken.append(char_id)
    return _complete_round_if_all_spoken(session)


def _complete_round_if_all_spoken(session: dict) -> bool:
    """initiativeの全員が_round_spokenに出そろっていれば、発言済み集合をリセットして
    _round_seqを進め、Trueを返す。発言の記録時と、initiativeから人が抜けた時に呼ぶ。"""
    spoken = session.get("_round_spoken", [])
    initiative = session.get("initiative", [])
    if initiative and set(initiative) <= set(spoken):
        session["_round_spoken"] = []
        session["_round_seq"] = session.get("_round_seq", 0) + 1
        return True
    return False


def _remove_from_initiative(session: dict, char_id: str) -> bool:
    """セッション進行中にchar_idをinitiativeから外し、手番まわりの状態を整合させる。
    戻り値はラウンド完了フラグ（外したことで残り全員が発言済みになった場合にTrue）。

    以前は投票による追放（vote_expel_resolve）が独自にturnを補正しており、手番が
    回ってきている最後尾のキャラを外すと、ラウンドを進めずturnをlen-1に詰めていた。
    その結果、直前のキャラにもう一度手番が回っていた。また_round_spokenから外さず
    完了判定もしなかったため、残り全員が発言済みでもラウンドが完了せず、キーパーの
    発言が次ラウンドへずれていた（2026-11-08、_normalize_round_turnへ寄せて集約）。
    """
    initiative = session.get("initiative", [])
    if char_id not in initiative:
        return False
    idx = initiative.index(char_id)
    turn = session.get("turn", 0)
    # 除去前のinitiative・turnを持ったまま走っているAIターン（next_turn）が、後から
    # 「古いturn+1」を書き戻してこの補正を潰さないようにする（skip_turnと同じ
    # _skip_genの進め方。_run_ai_turns・_finalize_ai_turnの既存ガードが効く）。
    session["_skip_gen"] = session.get("_skip_gen", 0) + 1
    session["initiative"] = [c for c in initiative if c != char_id]
    # 指名の戻り先はinitiativeの位置（index）で持っているので、同じ規則でずらす
    for key in ("_designated_return_turn", "designated_return_turn"):
        rt = session.get(key)
        if isinstance(rt, int) and idx < rt:
            session[key] = rt - 1
    if session.get("designated_next") == char_id:
        session.pop("designated_next", None)
        session.pop("designated_return_turn", None)
    if idx < turn:
        session["turn"] = turn - 1
    elif idx == turn:
        # 手番中のキャラが抜けた: 手番を新しく始める。指名で割り込んでいたキャラなら、
        # 手番を終えた場合（_finalize_ai_turn・_skip_turn_and_mark_spoken）と同じく
        # 指名前の戻り先へ返す（以前は次のキャラへ進み、戻り先が残ったままのため
        # そのラウンドで同じキャラが2回発言していた）。それ以外は次のキャラが同じ位置に
        # 詰まってくるのでturnはそのまま。最後尾だった場合は_normalize_round_turnが
        # 次ラウンドへ回す。
        session["action_count"] = 0
        return_turn = session.pop("_designated_return_turn", None)
        if return_turn is not None and session["initiative"]:
            session["turn"] = return_turn % len(session["initiative"])
    if not session["initiative"]:
        session["turn"] = 0
        return False
    _normalize_round_turn(session)
    spoken = session.get("_round_spoken", [])
    if char_id in spoken:
        session["_round_spoken"] = [c for c in spoken if c != char_id]
    return _complete_round_if_all_spoken(session) if session.get("_round_spoken") else False


def _set_designation(session: dict, target_id: str) -> None:
    """次の発言者を指名する唯一の窓口。指名されたキャラが話し終えたら、指名した時点の
    手番の次（指名した人の次）へ戻る。

    以前は人間の指名（POST /designate）とAIの指名（_resolve_ai_action の designate）が、
    それぞれ designated_next を書いていた。戻り先（designated_return_turn）を書いていたのは
    人間の側だけで、AIが指名すると、指名されたキャラの次へ進んでいた。指名されたのが
    initiative の最後のキャラなら、間の全員を飛ばしてラウンドが終わり、そのラウンドの
    キーパーの語りも出ていなかった（2026-11-08、E2E の trpg_skip_designate で発覚）。

    指名された人がさらに指名した（指名が続いた）ときは、最初の指名の戻り先を引き継ぐ。
    以前は「いまの手番の次」で書き直していたため、[a,b,c,d,e] で a→d、d→e と続くと、
    e の後に e 自身へ戻り（d の手番の次）、b・c が飛ばされていた（2026-11-08レビュー指摘）。
    """
    initiative = session.get("initiative", [])
    current_turn = session.get("turn", 0)
    inherited = session.get("_designated_return_turn")
    session["designated_next"] = target_id
    if inherited is not None:
        session["designated_return_turn"] = inherited
    else:
        session["designated_return_turn"] = (current_turn + 1) % len(initiative) if initiative else 0


def _normalize_round_turn(session: dict) -> None:
    """session["turn"]が既に書き込まれた（境界超過の可能性がある）値のとき、その場で
    round繰り上げ・turnのmodulo正規化を行う共有ヘルパー(2026-09-19)。

    以前は`_advance_turn`・`_emit_waiting_for_human`・`_resolve_turn_start`の3箇所が
    それぞれ独立に同じ「turn >= len(initiative)ならround+=1・turn%=len(initiative)」
    ロジックを再実装していた。GMの強制スキップ（skip_turn）が_round_seq更新を
    呼び忘れていたバグ（2026-09-08）と同根の「同じ状態を複数箇所が別々に扱う」構造が
    残っていたため、コードレビューを機に1箇所へ集約した。`_resolve_turn_start`の
    旧実装はturn境界超過時に常にturn=0へハードリセットしていた（moduloではない）が、
    これは「AIターンは1ターンにつき+1しか進まない」という前提の下でのみmoduloと
    同じ結果になる。この前提はキャラクタライゼーションテスト
    （tests/test_regression_turn_round_state.py）で確認済みで、moduloへの置き換えは
    その前提が将来崩れても壊れない方向への意図的な頑健化。
    """
    initiative = session.get("initiative", [])
    if not initiative:
        return
    t = session.get("turn", 0)
    if t >= len(initiative):
        session["round"] = session.get("round", 1) + 1
        session["turn"] = t % len(initiative)


def _advance_turn(session: dict, new_turn: int) -> None:
    """human_turn_action(send)・_apply_skip(skip)からターン確定時に呼ぶ、turn/roundの
    同期的な巻き戻り正規化(2026-09-06)。

    以前はここでsession["turn"]に生の値(len(initiative)以上もあり得る)をそのまま
    代入し、巻き戻り正規化（turn %= len(initiative)・round += 1）は
    _emit_waiting_for_human（_run_ai_turns内、asyncio.create_taskで非同期スケジュール
    される）任せだった。ソロ人間セッションで並列にsend/skipが来ると、1件目の処理
    直後はまだ正規化前（turn == len(initiative)）のため、その正規化が実際に走るまでの
    間に届いた後続リクエストは`_check_human_turn_authorization`のround_seqガード
    （expected_round_seq不一致で409）にすら到達せず、その手前の
    `if turn >= len(initiative): return {"error": "invalid turn"}`
    に先に捕まってHTTP 200（bodyはerror）を返してしまい、多重送信ガードの
    回帰テスト(frontend/e2e/ai_turn_dedup.js、200件数で判定)が間欠的に失敗して
    いた。turn/roundをこの場で即座に正規化することで、次のリクエストが読む時点では
    常に正規化済みの状態になり、必ずround_seqガードで一意に判定される。

    正規化そのものは`_normalize_round_turn`に委譲する（2026-09-19、集約）。
    """
    session["turn"] = new_turn
    _normalize_round_turn(session)


VOTE_IN_PROGRESS = "vote_in_progress"


EXPEL_DECISION_PENDING = "expel_decision_pending"


def _turn_discarded() -> dict:
    """投票・追放の決定待ちに入ったため、走っていたAIターンの結果を捨てたことを示す
    next_turn の戻り値。受け取った側が書き換えても他に波及しないよう、毎回作る。"""
    return {"discarded": True}


def _turn_progress_blocked(session: dict) -> str | None:
    """投票中（発議〜確定）と追放の続行方法の決定待ちの間は、ターンを進める操作を
    止める。止める理由のコードを返す（止めないならNone）。

    以前は投票中もサーバー側ではターンが進められ、確定時にturn/round/action_count
    だけを投票前の値へ巻き戻していた。その間の発言の履歴・発言力・発言済みの記録・
    指名は巻き戻らないため、「手番は戻ったのにその人は発言済み」といった食い違いが
    起きていた。巻き戻すのではなく、そもそも進めないことにする（2026-11-08）。
    ターンを進める入口（human_turn_actionのsend/skip・skip_turn・retake_turn・
    ai_resume・切断タイムアウトの自動skip）と_run_ai_turnsが、これを確認する。
    """
    if session.get("_pending_vote"):
        return VOTE_IN_PROGRESS
    if session.get("_pending_expel_followup"):
        return EXPEL_DECISION_PENDING
    return None


def _raise_if_turn_progress_blocked(session: dict) -> None:
    reason = _turn_progress_blocked(session)
    if reason:
        raise HTTPException(409, reason)


def _skip_turn_and_mark_spoken(session: dict, char_id: str, turn: int) -> bool:
    """char_idの手番（turn）をskipで終える共通処理（発言力+1・手番を進めて正規化・
    action_countリセット・発言済み記録）。戻り値はラウンド完了フラグ。

    skipの経路は4つある（プレイヤーの自主skip=_apply_skip、GMの強制skip=skip_turn、
    発言力マイナスによる自動skip=_resolve_turn_start、AIの自発skip=_resolve_ai_action）。
    2026-09-08にskip_turnだけ_mark_spoken_and_check_round_completeを呼び忘れていた
    バグを直したが、残り2経路（自動skip・AI自発skip）は同じ欠落を抱えたままだった。
    そのキャラは_round_spokenに入らず、ラウンド完了（_round_seq更新・キーパー発火）が
    次のラウンドまで遅れる。turnも正規化されずlen(initiative)のまま残っていた
    （2026-11-08）。経路ごとに書き写すと同じ漏れが再発するため、ここを唯一の窓口にする。
    """
    counters = session.setdefault("counters", {})
    counters[char_id] = counters.get(char_id, 0) + 1
    # 指名で割り込んだキャラの手番なら、発言して終えた場合（_finalize_ai_turn）と同じく
    # 指名前の戻り先へ返す。以前はskipだとturn+1へ進み、戻り先のキャラが飛ばされていた
    # （そのキャラが発言済みに入らず、ラウンド完了も遅れる。2026-11-08）。
    return_turn = session.pop("_designated_return_turn", None)
    initiative = session.get("initiative", [])
    if return_turn is not None and initiative:
        _advance_turn(session, return_turn % len(initiative))
    else:
        _advance_turn(session, turn + 1)
    session["action_count"] = 0
    return _mark_spoken_and_check_round_complete(session, char_id)


def _clean_history_for_retake(history: list, remove: int) -> tuple[list, int]:
    """履歴末尾から assistant エントリを remove 件削除する。
    _scene_image エントリ（role なし）はカウントせずスキップして削除する。"""
    new_history = list(history)
    removed = 0
    while new_history:
        entry = new_history[-1]
        if entry.get("character_id") == "_scene_image":
            new_history.pop()
            continue
        if removed < remove and entry.get("role") == "assistant":
            new_history.pop()
            removed += 1
        else:
            break
    return new_history, removed


def _retaken_char_id(history: list) -> str | None:
    """履歴末尾から実際に最後に発言した（_scene_imageを除く）キャラのIDを返す
    （retake_turn用、2026-09-19新設）。

    retake_turnは元々initiative[-1]（配列末尾）を「ラウンド境界で巻き戻す対象の
    キャラ」として無条件に前提していたが、GM指名（designate）で配列順を無視した
    相手が最後に喋っていた場合はこの前提が崩れる
    （tests/test_regression_turn_round_state.py::
    test_retake_round_boundary_after_designate_jump_may_pick_wrong_character で
    実際に食い違いを確認済み）。履歴の実体（_scene_imageをスキップする点は
    _clean_history_for_retakeと同じ）から直接特定することで、配列順の前提を排除する。
    """
    for entry in reversed(history):
        if entry.get("character_id") == "_scene_image":
            continue
        if entry.get("role") == "assistant":
            return entry.get("character_id")
        break
    return None


def _restore_round_spoken_for_retake(session: dict, retaken_char_id: str | None, round_boundary: bool) -> None:
    """retake_turnの3分岐それぞれで、巻き戻したキャラの「発言済み」記録を
    _round_spokenから正しく取り除く（2026-09-19新設）。

    以前はretake_turnが_round_spoken/_round_seqを一切更新しておらず、やり直し後に
    ラウンド完了判定（_mark_spoken_and_check_round_complete）が壊れたままになる
    欠陥があった（tests/test_regression_turn_round_state.pyのキャラクタライゼーション
    テストで実測して発覚）。

    - 途中ターン／同ラウンド内で1人戻るケース: _finalize_ai_turnがaction_countの
      閾値判定より前に無条件で_mark_spoken_and_check_round_completeを呼ぶため、
      retaken_char_idは既に_round_spokenに入っている。それを取り除くだけでよい。
    - ラウンド境界（round_boundary=True）のケース: retaken_char_idの発言完了が
      「全員発言済み」判定を成立させ_round_spokenを[]にリセットした張本人なので、
      単純に取り除くだけでは他の全員の「発言済み」記録も一緒に消えてしまう。
      本人以外全員を再度spoken扱いにして再構築する。

    _round_seq自体はここでは一切変更しない——ラウンドの通し番号ではなく、多重送信
    ガード（expected_round_seq）とキーパー発火の単調増加デデュープトークンであり、
    減算すると古い値をキャッシュしたクライアントが本来拒否されるべき多重送信を
    通してしまう（今週閉じたばかりの穴が再び開く）。ここでの修正でラウンドが
    実際に再度完了すれば_round_seqは自然に前進する。
    """
    if retaken_char_id is None:
        return
    if round_boundary:
        initiative = session.get("initiative", [])
        session["_round_spoken"] = [c for c in initiative if c != retaken_char_id]
    else:
        spoken = session.get("_round_spoken", [])
        if retaken_char_id in spoken:
            spoken.remove(retaken_char_id)
