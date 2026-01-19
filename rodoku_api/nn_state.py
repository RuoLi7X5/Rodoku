from __future__ import annotations

from typing import Tuple

import numpy as np


_B36 = "0123456789abcdefghijklmnopqrstuvwxyz"
_B36_I = {c: i for i, c in enumerate(_B36)}


def _parse_forbidden_key(forb: str) -> np.ndarray:
    # forb: 2 chars base36 per cell => 81 masks in 0..511
    if len(forb) != 162:
        # 兼容空/缺失：当作全 0
        return np.zeros((81,), dtype=np.int32)
    out = np.zeros((81,), dtype=np.int32)
    for i in range(81):
        a = forb[i * 2]
        b = forb[i * 2 + 1]
        hi = _B36_I.get(a, 0)
        lo = _B36_I.get(b, 0)
        out[i] = int(hi * 36 + lo)
    return out


def _box_of(r: int, c: int) -> int:
    return (r // 3) * 3 + (c // 3)


def state_key_to_tensors(state_key: str) -> Tuple[np.ndarray, np.ndarray]:
    """
    把 digits|forbiddenKey 转为网络输入（MVP）：
    - x: (C, 9, 9) float32
      C=20：
        - 9 个通道：已填数字 one-hot（1..9）
        - 9 个通道：allowed candidates one-hot（1..9）
        - 1 个通道：given/filled mask（已填=1）
        - 1 个通道：empties mask（空格=1）
    - mask: (A,) float32，动作可用掩码（MVP 暂只返回全 1；后续可严格根据 allowed 计算）
    """
    if "|" not in state_key:
        raise ValueError("bad state_key")
    digits, forb = state_key.split("|", 1)
    if len(digits) != 81:
        raise ValueError("bad digits")
    forb_masks = _parse_forbidden_key(forb)
    x = np.zeros((20, 9, 9), dtype=np.float32)
    grid = np.array([int(ch) for ch in digits], dtype=np.int32)

    # 预计算 row/col/box 已用数字 bitmask（bit0=>1）
    row_used = np.zeros((9,), dtype=np.int32)
    col_used = np.zeros((9,), dtype=np.int32)
    box_used = np.zeros((9,), dtype=np.int32)
    for i, v in enumerate(grid):
        r = i // 9
        c = i % 9
        if v != 0:
            bit = 1 << (int(v) - 1)
            row_used[r] |= bit
            col_used[c] |= bit
            box_used[_box_of(r, c)] |= bit

    ALL = (1 << 9) - 1
    action_mask = np.zeros((81 * 9 * 2,), dtype=np.float32)

    for i, v in enumerate(grid):
        r = i // 9
        c = i % 9
        if v != 0:
            x[int(v) - 1, r, c] = 1.0
            x[18, r, c] = 1.0
            continue
        x[19, r, c] = 1.0
        used = int(row_used[r] | col_used[c] | box_used[_box_of(r, c)])
        allowed = int(ALL & ~used) & ~int(forb_masks[i])
        # allowed candidates channels + action masks
        for d in range(1, 10):
            bit = 1 << (d - 1)
            if allowed & bit:
                x[9 + (d - 1), r, c] = 1.0
                # commit
                action_mask[i * 9 + (d - 1)] = 1.0
                # eliminate
                action_mask[(81 * 9) + i * 9 + (d - 1)] = 1.0

    return x, action_mask


def count_total_candidates(state_key: str) -> int:
    """
    统计当前盘面的“总候选数”（所有空格 allowed candidates 数之和）。
    用于 reward shaping：before - after 越大说明进展越大。
    """
    if "|" not in state_key:
        return 0
    digits, forb = state_key.split("|", 1)
    if len(digits) != 81:
        return 0
    forb_masks = _parse_forbidden_key(forb)
    grid = np.array([int(ch) for ch in digits], dtype=np.int32)

    row_used = np.zeros((9,), dtype=np.int32)
    col_used = np.zeros((9,), dtype=np.int32)
    box_used = np.zeros((9,), dtype=np.int32)
    for i, v in enumerate(grid):
        r = i // 9
        c = i % 9
        if v != 0:
            bit = 1 << (int(v) - 1)
            row_used[r] |= bit
            col_used[c] |= bit
            box_used[_box_of(r, c)] |= bit

    ALL = (1 << 9) - 1
    total = 0
    for i, v in enumerate(grid):
        if v != 0:
            continue
        r = i // 9
        c = i % 9
        used = int(row_used[r] | col_used[c] | box_used[_box_of(r, c)])
        allowed = int(ALL & ~used) & ~int(forb_masks[i])
        total += int(allowed.bit_count())
    return int(total)


def encode_action(action_type: str, idx: int, d: int) -> int:
    """
    动作编码（A=81*9*2）：
    - commit: base = 0
    - eliminate: base = 81*9
    """
    if not (0 <= idx < 81 and 1 <= d <= 9):
        raise ValueError("bad action")
    base = 0 if action_type == "commit" else (81 * 9)
    return base + idx * 9 + (d - 1)

