"""DEF(kari) MVP — 定数集約"""

ACTIVE_POLL_MS = 300
IDLE_POLL_MS = 1000
MAX_VISIBLE_TURNS = 3
LOAD_BATCH = 3
MIN_QUOTED_DIALOGUE_LEN = 5
DEFAULT_UNDO_MAX_HISTORY = 5
IMAGE_INTERVAL_SEC = 30
DEFAULT_STATUS_POLL_SEC = 5

T2I_MODE_END = "end"
T2I_MODE_START = "start"
T2I_MODE_MANUAL = "manual"
T2I_MODE_INTERVAL = "interval"
T2I_MODES = [T2I_MODE_END, T2I_MODE_START, T2I_MODE_MANUAL, T2I_MODE_INTERVAL]
T2I_MODE_LABELS = {
    T2I_MODE_END: "各サイクルの最後(演出先行型)",
    T2I_MODE_START: "各サイクルの最初(状況先行型)",
    T2I_MODE_MANUAL: "手動オンデマンド",
    T2I_MODE_INTERVAL: "時間インターバル自動生成",
}
DEFAULT_T2I_MODE = T2I_MODE_END

T2I_PROMPT_FORMATS = ["danbooru", "natural", "e621", "other"]
T2I_PROMPT_FORMAT_LABELS = {
    "danbooru": "danbooru(タグ形式)",
    "natural": "自然言語(文章をそのまま使用)",
    "e621": "e621(タグ形式)",
    "other": "その他",
}
DEFAULT_T2I_PROMPT_FORMAT = "danbooru"

T2I_PROMPT_MODES = ["current", "passthrough", "dedicated"]
T2I_PROMPT_MODE_LABELS = {
    "current": "LLMで生成 (current)",
    "passthrough": "会話から流用 (passthrough)",
    "dedicated": "強化LLM生成 (dedicated)",
}
DEFAULT_T2I_PROMPT_MODE = "current"

T2I_BACKENDS = ["a1111", "comfyui", "civitai", "huggingface"]
T2I_BACKEND_LABELS = {
    "a1111": "A1111 (ローカル)",
    "comfyui": "ComfyUI (ローカル)",
    "civitai": "Civitai (外部API)",
    "huggingface": "Hugging Face (外部API)",
}
DEFAULT_T2I_BACKEND = "huggingface"
