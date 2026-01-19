from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, Generator, Iterable, Optional


_LOCK = threading.Lock()
from .runtime_paths import legacy_path, replay_path


_PATH = replay_path()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _safe_append_line(path: Path, line: str, *, retries: int = 6, sleep_s: float = 0.04) -> None:
    """
    Windows 上 uvicorn 多线程/多进程 + 杀毒/索引服务容易触发 PermissionError。
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
    # 非致命：训练/求解继续跑
    if last_err:
        return


def append_transition(t: Dict[str, Any]) -> None:
    """
    记录一条训练数据：(state, action, proof, reward, next_state, meta...) 的扁平 dict。
    """
    payload = dict(t)
    payload.setdefault("at_ms", _now_ms())
    line = json.dumps(payload, ensure_ascii=False)
    with _LOCK:
        _safe_append_line(_PATH, line)


def iter_recent(*, max_lines: int = 800) -> Generator[Dict[str, Any], None, None]:
    """
    读取最近 N 条 replay 记录（用于 /metrics 绘图和训练采样）。
    注意：为简单起见，这里是整文件顺序读 + deque 截断。
    """
    # 兼容迁移：若新路径不存在但旧路径存在，读旧文件
    path = _PATH
    if not path.exists():
        legacy = legacy_path("_replay.jsonl")
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
                    buf.append(json.loads(line))
                except Exception:
                    continue
        for x in buf:
            yield x
    except Exception:
        return


def stats(*, tail: int = 1200) -> Dict[str, Any]:
    """
    轻量统计：用于 /metrics 里展示 replay 状态。
    """
    xs = list(iter_recent(max_lines=int(tail)))
    return {
        "path": str(_PATH),
        "exists": _PATH.exists(),
        "tail": int(tail),
        "count": int(len(xs)),
        "last_at_ms": int(xs[-1].get("at_ms", 0)) if xs else 0,
    }

