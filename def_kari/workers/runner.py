"""ワーカースレッド起動(PoCのstart_workerに対応)"""

import threading

from def_kari.workers.tts_worker import handle_tts_task
from def_kari.workers.t2i_worker import handle_image_task


def start_worker(task_q, result_q, vram_lock: threading.Lock) -> threading.Thread:
    def worker():
        print("[WORKER] thread started, waiting for tasks...")
        while True:
            task = task_q.get()
            kind = task.get("kind")
            print(f"[WORKER] got task: kind={kind}, msg_id={task.get('msg_id')}")
            if kind == "tts":
                try:
                    print(f"[WORKER] tts task received: {task.get('msg_id')}")
                    handle_tts_task(task, result_q)
                except Exception as _e:
                    print(f"[WORKER] tts exception: {_e}")
                    pass
            elif kind == "image":
                try:
                    handle_image_task(task, result_q, vram_lock)
                except Exception:
                    pass

    t = threading.Thread(target=worker, daemon=True, name="def-kari-worker")
    t.start()
    return t
