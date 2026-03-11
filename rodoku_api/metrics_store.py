from __future__ import annotations

import json
import os
import time
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


from .runtime_paths import legacy_path, metrics_path


METRICS_PATH = metrics_path()
_WRITE_LOCK = threading.Lock()


@dataclass
class MetricsStore:
    runs: int = 0
    solved: int = 0
    stuck: int = 0
    invalid: int = 0
    step_counts: List[int] = field(default_factory=list)
    durations: List[float] = field(default_factory=list)
    status_hist: List[str] = field(default_factory=list)
    struct_counter: Dict[str, int] = field(default_factory=dict)
    oracle_steps_hist: List[int] = field(default_factory=list)
    # 归因/命中统计（偏 solve_job 实时训练用）
    step_kind_counter: Dict[str, int] = field(default_factory=dict)  # basic/rank/techlib/ur/other
    deletion_kind_counter: Dict[str, int] = field(default_factory=dict)  # 按 kind 统计删数总量
    # 事件序列：用于可视化曲线（限制长度，避免爆炸）
    event_hist: List[Dict[str, Any]] = field(default_factory=list)
    train_hist: List[Dict[str, Any]] = field(default_factory=list)  # {at_ms, step, loss, lr}


def load_metrics() -> MetricsStore:
    path = METRICS_PATH
    if not path.exists():
        return MetricsStore()
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return MetricsStore(
            runs=int(obj.get("runs", 0)),
            solved=int(obj.get("solved", 0)),
            stuck=int(obj.get("stuck", 0)),
            invalid=int(obj.get("invalid", 0)),
            step_counts=[int(x) for x in (obj.get("step_counts", []) or [])],
            durations=[float(x) for x in (obj.get("durations", []) or [])],
            status_hist=[str(x) for x in (obj.get("status_hist", []) or [])],
            struct_counter={str(k): int(v) for (k, v) in (obj.get("struct_counter", {}) or {}).items()},
            oracle_steps_hist=[int(x) for x in (obj.get("oracle_steps_hist", []) or [])],
            step_kind_counter={str(k): int(v) for (k, v) in (obj.get("step_kind_counter", {}) or {}).items()},
            deletion_kind_counter={str(k): int(v) for (k, v) in (obj.get("deletion_kind_counter", {}) or {}).items()},
            event_hist=[x for x in (obj.get("event_hist", []) or []) if isinstance(x, dict)],
            train_hist=[x for x in (obj.get("train_hist", []) or []) if isinstance(x, dict)],
        )
    except Exception:
        # 文件损坏不阻塞启动
        return MetricsStore()


def save_metrics(m: MetricsStore) -> None:
    payload: Dict[str, Any] = {
        "runs": m.runs,
        "solved": m.solved,
        "stuck": m.stuck,
        "invalid": m.invalid,
        "step_counts": m.step_counts,
        "durations": m.durations,
        "status_hist": m.status_hist,
        "struct_counter": m.struct_counter,
        "oracle_steps_hist": m.oracle_steps_hist,
        "step_kind_counter": m.step_kind_counter,
        "deletion_kind_counter": m.deletion_kind_counter,
        "event_hist": m.event_hist,
        "train_hist": m.train_hist,
    }
    with _WRITE_LOCK:
        tmp = METRICS_PATH.with_name(f"{METRICS_PATH.name}.{os.getpid()}.tmp")
        try:
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            for _ in range(20):
                try:
                    os.replace(tmp, METRICS_PATH)
                    return
                except PermissionError:
                    time.sleep(0.03)
            METRICS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            return


def record_step_event(*, kind: str, source: str | None, action_type: str, deletions_count: int, progressed: bool, at_ms: int) -> None:
    """
    归因事件（用于 /solve_job 的实时训练曲线）：
    - kind: RANK/UR1/basic/...
    - source: techlib 或 None
    """
    k = "other"
    if kind == "RANK" and source == "techlib":
        k = "techlib"
    elif kind == "RANK":
        k = "rank"
    elif kind == "UR1":
        k = "ur"
    elif action_type == "commit":
        k = "basic"

    m = load_metrics()
    m.step_kind_counter[k] = int(m.step_kind_counter.get(k, 0)) + 1
    if deletions_count > 0:
        m.deletion_kind_counter[k] = int(m.deletion_kind_counter.get(k, 0)) + int(deletions_count)
    m.event_hist.append(
        {
            "t": int(at_ms),
            "k": k,
            "kind": str(kind),
            "source": (str(source) if source is not None else None),
            "action": str(action_type),
            "del": int(deletions_count),
            "progressed": bool(progressed),
        }
    )
    # 限长
    if len(m.event_hist) > 6000:
        m.event_hist = m.event_hist[-5000:]
    save_metrics(m)

