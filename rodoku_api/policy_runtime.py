from __future__ import annotations

import threading
from pathlib import Path
from typing import List, Optional, Tuple

from .runtime_paths import ckpt_dir


_LOCK = threading.Lock()
_MODEL: object | None = None
_DEVICE: object | None = None
_CKPT_PATH: str | None = None


def _latest_ckpt_path() -> Optional[Path]:
    d = ckpt_dir()
    if not d.exists():
        return None
    ps = sorted(d.glob("policy_*.pt"), key=lambda p: p.stat().st_mtime, reverse=True)
    return ps[0] if ps else None


def ensure_loaded() -> bool:
    """
    懒加载最新 checkpoint。
    - 无 ckpt：返回 False（自动降级）
    """
    # numpy/torch 可能未安装（例如用户误用系统 python 启动）：
    # - 无法加载模型时自动降级，不影响核心逻辑推理
    try:
        import torch  # type: ignore
        from .nn_models import RodokuPolicyValueNet  # type: ignore
    except Exception:
        return False

    global _MODEL, _DEVICE, _CKPT_PATH
    with _LOCK:
        p = _latest_ckpt_path()
        if not p:
            _MODEL = None
            _CKPT_PATH = None
            return False
        if _CKPT_PATH == str(p) and _MODEL is not None:
            return True

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = RodokuPolicyValueNet().to(device)
        payload = torch.load(str(p), map_location=device)
        sd = payload.get("model", payload)
        model.load_state_dict(sd, strict=False)
        model.eval()
        _MODEL = model
        _DEVICE = device
        _CKPT_PATH = str(p)
        return True


def score_actions(state_key: str, actions: List[Tuple[str, int, int]]) -> List[float]:
    """
    对一组动作打分（越大越优先尝试）。
    actions: [(action_type, idx, d), ...]
    返回与 actions 等长的分数数组；若无模型则全 0。
    """
    # 允许在缺少 numpy/torch 时降级为全 0（不影响求解正确性）
    try:
        import numpy as np  # type: ignore
        import torch  # type: ignore
        from .nn_state import encode_action, state_key_to_tensors  # type: ignore
    except Exception:
        return [0.0 for _ in actions]

    if not ensure_loaded():
        return [0.0 for _ in actions]
    assert _MODEL is not None and _DEVICE is not None
    x_np, mask_np = state_key_to_tensors(state_key)
    x = torch.from_numpy(np.expand_dims(x_np, axis=0)).to(_DEVICE)
    mask = torch.from_numpy(mask_np).to(_DEVICE)
    with torch.no_grad():
        logits, _v = _MODEL(x)
        logits = logits.squeeze(0)  # (A,)
        # 用 mask 抑制非法动作
        logits = logits + (mask - 1.0) * 1e9
        out = []
        for (t, idx, d) in actions:
            try:
                a = encode_action(t, int(idx), int(d))
                out.append(float(logits[a].detach().cpu().item()))
            except Exception:
                out.append(-1e9)
        return out


def evaluate_state(state_key: str) -> Optional[float]:
    """
    返回 value head 的评估值（越大越“好/接近解/更有进展潜力”）。
    - 无 ckpt：返回 None
    """
    try:
        import numpy as np  # type: ignore
        import torch  # type: ignore
        from .nn_state import state_key_to_tensors  # type: ignore
    except Exception:
        return None

    if not ensure_loaded():
        return None
    assert _MODEL is not None and _DEVICE is not None
    x_np, _mask_np = state_key_to_tensors(state_key)
    x = torch.from_numpy(np.expand_dims(x_np, axis=0)).to(_DEVICE)
    with torch.no_grad():
        _logits, v = _MODEL(x)
        try:
            return float(v.squeeze(0).detach().cpu().item())
        except Exception:
            return None


def current_ckpt() -> Optional[str]:
    with _LOCK:
        return _CKPT_PATH

