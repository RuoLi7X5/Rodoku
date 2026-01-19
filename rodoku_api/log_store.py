from __future__ import annotations

import json
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, Generator, Optional

from .runtime_paths import events_log_path, legacy_path

_LOCK = threading.Lock()
_PATH = events_log_path()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _safe_append_line(path: Path, line: str, *, retries: int = 6, sleep_s: float = 0.04) -> None:
    """
    Windows 上多线程写文件容易触发 PermissionError。
    这里用“追加写”+少量重试，保证不中断主流程。
    """
    last_err: Exception | None = None
    for _ in range(max(1, int(retries))):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
                f.write("\n")
            return
        except PermissionError as e:
            last_err = e
            time.sleep(sleep_s)
        except OSError as e:
            last_err = e
            time.sleep(sleep_s)
    if last_err:
        return


def append_event(ev: Dict[str, Any]) -> None:
    """
    追加一条事件日志（JSONL）。
    推荐字段（非强制）：
    - at_ms, type, job_id, puzzle, step_index
    - phase/subphase, message, info
    - use_policy, policy_ckpt
    """
    payload = dict(ev)
    payload.setdefault("at_ms", _now_ms())
    line = json.dumps(payload, ensure_ascii=False)
    with _LOCK:
        _safe_append_line(_PATH, line)


def iter_recent(*, max_lines: int = 2000, job_id: Optional[str] = None) -> Generator[Dict[str, Any], None, None]:
    """
    读取最近 N 条事件（用于导出与 /viz）。
    """
    path = _PATH
    if not path.exists():
        legacy = legacy_path("_events.jsonl")
        if legacy.exists():
            path = legacy
        else:
            return
            yield  # pragma: no cover
    try:
        buf: deque[Dict[str, Any]] = deque(maxlen=int(max_lines))
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if job_id and str(obj.get("job_id", "")) != str(job_id):
                        continue
                    buf.append(obj)
                except Exception:
                    continue
        for x in buf:
            yield x
    except Exception:
        return

