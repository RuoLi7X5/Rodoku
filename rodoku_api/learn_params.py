from __future__ import annotations

import json
import os
import time
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple


from .runtime_paths import legacy_path, learn_params_path, ensure_data_dir


LEARN_PATH = learn_params_path() # Store only the current params (small, fast)
HISTORY_PATH = ensure_data_dir() / "_learn_history.jsonl" # Append-only log (large)

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


_GLOBAL_LEARN_STATE: LearnState | None = None
_STATE_LOCK = threading.Lock()


def load_learn_state() -> LearnState:
    global _GLOBAL_LEARN_STATE
    with _STATE_LOCK:
        if _GLOBAL_LEARN_STATE is not None:
            return _GLOBAL_LEARN_STATE

        path = LEARN_PATH
        if not path.exists():
            _GLOBAL_LEARN_STATE = LearnState(params=dict(DEFAULT_PARAMS), history=[])
            return _GLOBAL_LEARN_STATE
        
        try:
            content = path.read_text(encoding="utf-8")
            obj = json.loads(content)
            p = obj.get("params", {}) or {}
            params = dict(DEFAULT_PARAMS)
            for k, v in p.items():
                try:
                    params[str(k)] = float(v)
                except Exception:
                    pass
            
            _GLOBAL_LEARN_STATE = LearnState(params=params, history=[])
        except Exception:
            _GLOBAL_LEARN_STATE = LearnState(params=dict(DEFAULT_PARAMS), history=[])
        
        return _GLOBAL_LEARN_STATE


def save_learn_state(st: LearnState) -> None:
    # 1. Update Global Cache
    global _GLOBAL_LEARN_STATE
    with _STATE_LOCK:
        _GLOBAL_LEARN_STATE = st
    
    # 2. Persist Current Params (Small JSON, Atomic Replace)
    payload = {"params": st.params, "updated_at_ms": _now_ms()}
    
    # 3. Append to History Log (JSONL)
    # We grab the last event if it exists (st.history is ephemeral now)
    latest_event = st.history[-1] if st.history else None
    
    with _WRITE_LOCK:
        # A. Save Params
        tmp = LEARN_PATH.with_name(f"{LEARN_PATH.name}.{os.getpid()}.tmp")
        try:
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            for _ in range(20):
                try:
                    os.replace(tmp, LEARN_PATH)
                    break
                except PermissionError:
                    time.sleep(0.03)
            else:
                print(f"Warning: Failed to atomic replace {LEARN_PATH}, trying direct overwrite...")
                LEARN_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"Error saving learn params to {LEARN_PATH}: {e}")

        # B. Append History
        if latest_event:
            try:
                line = json.dumps(latest_event, ensure_ascii=False)
                with open(HISTORY_PATH, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception as e:
                print(f"Error appending history: {e}")
    
    # Clear ephemeral history to prevent memory leak
    st.history.clear()


def get_params() -> Dict[str, float]:
    return load_learn_state().params


def update_params(event_counts: Dict[str, int], solved: bool, progressed: bool) -> Dict[str, float]:
    """
    一个非常轻量的“学习规则”（先让你能看到进化）：
    - 发生进展：把贡献来源的权重略微上调（w_*）
    - 无进展：轻微衰减，避免一直偏向无效策略
    - solved：额外奖励
    """
    # 关键：全程加锁，确保 read-modify-write 是原子的，且基于内存态
    with _STATE_LOCK:
        # load_learn_state 内部会处理初始化
        # 注意：这里我们不直接调用 load_learn_state()，而是直接使用 _GLOBAL_LEARN_STATE
        # 因为 load_learn_state 也会拿锁，导致重入死锁（RLock 可解，但 threading.Lock 不可重入）
        # 所以我们将 load 逻辑内联或确保 load_learn_state 不加锁
        pass
    
    # 修正策略：让 load_learn_state 负责“确保已加载”，而 update_params 在持有锁的情况下操作
    st = load_learn_state() # 这一步获取锁并释放，确保 _GLOBAL_LEARN_STATE 可用
    
    with _STATE_LOCK:
        p = st.params # 引用
        
        # 学习率（后续可接 PyTorch / PPO，这里先是可解释的权重表）
        lr = 0.03
        decay = 0.995 if not progressed else 0.999

        # decay
        # 修正：数独技巧（w_*）不应随时间自然衰减（稀有不代表无用）
        # 仅对“搜索偏置（Bias/Jitter）”进行回归，让搜索策略在探索后慢慢回归稳态
        for k in list(p.keys()):
            if k in ("overlap_bias", "truth_size_jitter", "size_match_bias", "rank_restarts"):
                # 偏置类参数：向默认值回归（而不是向0衰减）
                # 例如 overlap_bias 默认 1.0
                defaults = {"overlap_bias": 1.0, "truth_size_jitter": 0.15, "size_match_bias": 0.25, "rank_restarts": 3.0}
                target = defaults.get(k, 1.0)
                current = float(p.get(k, 1.0))
                # 渐进回归：current = current * 0.995 + target * 0.005
                p[k] = current * decay + target * (1 - decay)

        # reward shaping
        bonus = 2.0 if solved else 0.0
        if progressed:
            # 按事件计数加权增强
            for name, cnt in event_counts.items():
                if cnt <= 0:
                    continue
                key = f"w_{name}"
                if key in p:
                    # 稀有技巧补偿：UR 和 Rank 出现频率低，单次奖励应更高，防止被 Basic 淹没
                    multiplier = 5.0 if name in ("rank", "ur") else 1.0
                    p[key] = float(p.get(key, 1.0)) + lr * float(cnt) * multiplier + bonus * 0.02
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
    # 修正：不强制归一化，避免高频 Basic 把 Rank 挤压下去。
    # 改为“软顶（Soft Cap）”：超过一定值后增长变慢，但不因别人增长而变小。
    for k in ("w_basic", "w_rank", "w_techlib", "w_ur"):
        val = float(p.get(k, 1.0))
        if val > 5.0:
            # 超过 5.0 后，对其进行平滑限制，防止数值爆炸
            # 例如：每次只允许极其微小的增长，或按比例回缩
            p[k] = 5.0 + (val - 5.0) * 0.9 # 软顶抑制

        st.history.append({"at_ms": _now_ms(), "params": dict(p), "event": {"counts": dict(event_counts), "solved": solved, "progressed": progressed}})
        
    # save_learn_state 内部会再次拿写文件锁（注意：不是 STATE_LOCK，是 WRITE_LOCK，或者是同一个？）
    # 之前的代码：_WRITE_LOCK 用于文件操作。
    # 这里我们把文件操作移出 _STATE_LOCK 范围，避免 IO 阻塞内存读写。
    # 只要 st 是对象引用，且 update_params 是串行的（或者加了锁），那么 st 的状态就是最新的。
    # 但为了防止 save 时 st 又被改了（list append 是原子的吗？），我们最好 copy 一份 payload
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
    
    # Read history from disk (tail 300)
    history = []
    if HISTORY_PATH.exists():
        try:
            # Simple readlines for now. If file > 100MB, consider seek.
            lines = HISTORY_PATH.read_text(encoding='utf-8').splitlines()
            for line in lines[-300:]:
                if line.strip():
                    try:
                        history.append(json.loads(line))
                    except: pass
        except:
            pass
            
    return params, history

