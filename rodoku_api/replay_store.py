from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, Generator, Iterable, Optional


_LOCK = threading.Lock()
from .runtime_paths import legacy_path, replay_path, ensure_data_dir


_PATH = replay_path()
_UR_PATH = ensure_data_dir() / "_ur_samples.jsonl"


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
    为优化大文件读取性能：
    1. 估算每行平均大小，直接 seek 到文件末尾附近开始读。
    2. 只解析最后的 chunk。
    """
    path = _PATH
    if not path.exists():
        return
        yield  # pragma: no cover
        
    try:
        buf: deque[Dict[str, Any]] = deque(maxlen=int(max_lines))
        file_size = path.stat().st_size
        
        # 估算：假设每行 500-1000 字节（solve step 可能较大，proof/meta），安全起见取 2KB/行。
        # 如果 max_lines=800，我们读最后 2MB 应该足够。如果是 5000，读 10MB。
        # 我们稍微放宽一点：每行预估 1KB，且至少读 64KB。
        avg_line_size = 1024
        read_size = max(64 * 1024, int(max_lines) * avg_line_size)
        
        with open(path, "rb") as f:
            if file_size > read_size:
                f.seek(-read_size, os.SEEK_END)
                # 丢弃第一行（可能不完整）
                f.readline()
            
            for line_bytes in f:
                line = line_bytes.strip()
                if not line:
                    continue
                try:
                    # decode + parse
                    buf.append(json.loads(line.decode("utf-8")))
                except Exception:
                    continue
                    
        for x in buf:
            yield x
    except Exception:
        return


def iter_ur_samples(*, max_lines: int = 2000) -> Generator[Dict[str, Any], None, None]:
    """
    读取 UR 负样本数据。
    """
    path = _UR_PATH
    if not path.exists():
        return
    
    try:
        buf: deque[Dict[str, Any]] = deque(maxlen=int(max_lines))
        file_size = path.stat().st_size
        
        # UR samples 比较短，假设 500B 一行
        read_size = max(32 * 1024, int(max_lines) * 512)
        
        with open(path, "rb") as f:
            if file_size > read_size:
                f.seek(-read_size, os.SEEK_END)
                f.readline() # discard partial
            
            for line_bytes in f:
                line = line_bytes.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line.decode("utf-8"))
                    # 适配格式：train_jobs 需要 before_key, action_type, affected, ur_label
                    # ur_generator 输出的是: state_key, action_idx, action_d, ur_label
                    # 转换为统一格式:
                    adapted = {
                        "before_key": row.get("state_key"),
                        "action_type": "commit", # UR trap is usually a 'commit' action that leads to ambiguity
                        # 但如果是 'eliminate' 导致的 deadly pattern 呢？目前生成器生成的是 commit。
                        # 待定：policy net 输出的是 commit/eliminate logits。
                        # 这里我们把 trap 视为 "commit(idx, d)" 是坏动作。
                        "affected": [(row.get("action_idx"), row.get("action_d"))],
                        "ur_label": float(row.get("ur_label", 0.0)),
                        "reward": -1.0, # Negative reward for policy (optional)
                        "done": True,
                        "meta": row.get("meta")
                    }
                    buf.append(adapted)
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

