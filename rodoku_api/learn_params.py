from __future__ import annotations

import json
import os
import time
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple


from .runtime_paths import legacy_path, learn_params_path


LEARN_PATH = learn_params_path()
_WRITE_LOCK = threading.Lock()


DEFAULT_PARAMS: Dict[str, float] = {
    # 这些是“策略参数向量”（可视化雷达图/曲线用）
    # 也会影响求解时尝试顺序（体现“自我迭代”）
    "w_basic": 1.0,
    "w_rank": 1.0,
    "w_techlib": 1.0,
    "w_ur": 1.0,
    # 倾向弱区域重叠覆盖的偏好强度（>1 更偏向重叠）
    "overlap_bias": 1.0,
    # rank 搜索：Truth 枚举顺序的“随机抖动强度”（0=完全按 size 从小到大；>0 更探索）
    # 该参数不限制任何 Truth/Link 类型，只改变搜索路径覆盖。
    "truth_size_jitter": 0.15,
    # rank 搜索：倾向“Link 覆盖规模与 Truth 规模相近”（候选数相近更容易相关，形成结构）
    "size_match_bias": 0.25,
    # rank 搜索：每轮多样化随机重启次数（越大越探索，但更耗时）
    "rank_restarts": 3.0,
}


@dataclass
class LearnState:
    params: Dict[str, float]
    history: List[Dict[str, Any]]  # [{"at_ms":..., "params":{...}, "event":{...}}]


def _now_ms() -> int:
    return int(time.time() * 1000)


def load_learn_state() -> LearnState:
    path = LEARN_PATH
    if not path.exists():
        legacy = legacy_path("_learn_params.json")
        if legacy.exists():
            path = legacy
        else:
            return LearnState(params=dict(DEFAULT_PARAMS), history=[])
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        p = obj.get("params", {}) or {}
        params = dict(DEFAULT_PARAMS)
        for k, v in p.items():
            try:
                params[str(k)] = float(v)
            except Exception:
                pass
        hist = obj.get("history", []) or []
        if not isinstance(hist, list):
            hist = []
        return LearnState(params=params, history=hist)
    except Exception:
        return LearnState(params=dict(DEFAULT_PARAMS), history=[])


def save_learn_state(st: LearnState) -> None:
    payload = {"params": st.params, "history": st.history[-2000:]}
    # Windows 上可能因 uvicorn reload/多进程短暂锁文件导致 WinError 5，做锁+重试，避免训练任务直接报错。
    with _WRITE_LOCK:
        tmp = LEARN_PATH.with_name(f"{LEARN_PATH.name}.{os.getpid()}.tmp")
        try:
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            for _ in range(20):
                try:
                    os.replace(tmp, LEARN_PATH)
                    return
                except PermissionError:
                    time.sleep(0.03)
            # 最后兜底：直接写（非原子），但保证不抛出打断训练
            LEARN_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            # 任何写盘失败都不应打断训练：保留内存态即可
            return


def get_params() -> Dict[str, float]:
    return load_learn_state().params


def update_params(event_counts: Dict[str, int], solved: bool, progressed: bool) -> Dict[str, float]:
    """
    一个非常轻量的“学习规则”（先让你能看到进化）：
    - 发生进展：把贡献来源的权重略微上调（w_*）
    - 无进展：轻微衰减，避免一直偏向无效策略
    - solved：额外奖励
    """
    st = load_learn_state()
    p = st.params

    # 学习率（后续可接 PyTorch / PPO，这里先是可解释的权重表）
    lr = 0.03
    decay = 0.995 if not progressed else 0.999

    # decay
    for k in list(p.keys()):
        if k.startswith("w_") or k in ("overlap_bias", "truth_size_jitter", "size_match_bias", "rank_restarts"):
            p[k] = max(0.05, float(p.get(k, 1.0)) * decay)

    # reward shaping
    bonus = 2.0 if solved else 0.0
    if progressed:
        # 按事件计数加权增强
        for name, cnt in event_counts.items():
            if cnt <= 0:
                continue
            key = f"w_{name}"
            if key in p:
                p[key] = float(p.get(key, 1.0)) + lr * float(cnt) + bonus * 0.02
        # 如果 rank/techlib 产生了删数，通常需要“重叠偏好”更强一点
        if (event_counts.get("rank", 0) + event_counts.get("techlib", 0)) > 0:
            p["overlap_bias"] = min(3.0, float(p.get("overlap_bias", 1.0)) + 0.02 + bonus * 0.01)
            # 有进展：略微增强“规模匹配”偏置，但降低随机抖动（更偏 exploitation）
            p["size_match_bias"] = min(2.0, float(p.get("size_match_bias", 0.25)) + 0.01 + bonus * 0.005)
            p["truth_size_jitter"] = max(0.0, float(p.get("truth_size_jitter", 0.15)) * 0.98)
    else:
        # 长时间无进展时，轻微降低 overlap_bias
        p["overlap_bias"] = max(0.7, float(p.get("overlap_bias", 1.0)) * 0.995)
        # 无进展：增加随机抖动（更偏 exploration），并轻微降低规模匹配偏置
        p["truth_size_jitter"] = min(1.5, float(p.get("truth_size_jitter", 0.15)) * 1.02 + 0.01)
        p["size_match_bias"] = max(0.0, float(p.get("size_match_bias", 0.25)) * 0.995)

    # 简单归一化（避免无限变大）：让 4 个 w_* 总和稳定在 4 左右
    s = float(p.get("w_basic", 1)) + float(p.get("w_rank", 1)) + float(p.get("w_techlib", 1)) + float(p.get("w_ur", 1))
    if s > 0:
        scale = 4.0 / s
        for k in ("w_basic", "w_rank", "w_techlib", "w_ur"):
            p[k] = max(0.05, float(p.get(k, 1.0)) * scale)

    st.history.append({"at_ms": _now_ms(), "params": dict(p), "event": {"counts": dict(event_counts), "solved": solved, "progressed": progressed}})
    save_learn_state(st)
    return p


def params_for_metrics() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Returns:
      - params: [{name,value,max}, ...] for radar
      - history: raw history records for curves (optional)
    """
    st = load_learn_state()
    p = st.params
    params = [
        {"name": "w_basic", "value": float(p.get("w_basic", 1.0)), "max": 2.5},
        {"name": "w_rank", "value": float(p.get("w_rank", 1.0)), "max": 2.5},
        {"name": "w_techlib", "value": float(p.get("w_techlib", 1.0)), "max": 2.5},
        {"name": "w_ur", "value": float(p.get("w_ur", 1.0)), "max": 2.5},
        {"name": "overlap_bias", "value": float(p.get("overlap_bias", 1.0)), "max": 3.0},
        {"name": "truth_size_jitter", "value": float(p.get("truth_size_jitter", 0.15)), "max": 1.5},
        {"name": "size_match_bias", "value": float(p.get("size_match_bias", 0.25)), "max": 2.0},
        {"name": "rank_restarts", "value": float(p.get("rank_restarts", 3.0)), "max": 8.0},
    ]
    return params, st.history

