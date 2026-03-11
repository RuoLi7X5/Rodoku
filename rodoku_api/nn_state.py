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


import itertools

def _get_als_and_conj_maps(grid: np.ndarray, forb_masks: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    计算 ALS (Almost Locked Sets) 和 Conjugate Pairs (强链) 热力图。
    - als_map: (9, 9) float, 每个格子参与 ALS 的次数
    - conj_map: (9, 9) float, 每个格子参与强链的次数
    """
    als_map = np.zeros((9, 9), dtype=np.float32)
    conj_map = np.zeros((9, 9), dtype=np.float32)
    
    # Precompute allowed candidates per cell
    ALL = (1 << 9) - 1
    row_used = np.zeros(9, dtype=int)
    col_used = np.zeros(9, dtype=int)
    box_used = np.zeros(9, dtype=int)
    
    for i in range(81):
        v = grid[i]
        if v != 0:
            mask = 1 << (v - 1)
            r, c = i // 9, i % 9
            b = _box_of(r, c)
            row_used[r] |= mask
            col_used[c] |= mask
            box_used[b] |= mask
            
    allowed_masks = np.zeros(81, dtype=int)
    for i in range(81):
        if grid[i] == 0:
            r, c = i // 9, i % 9
            b = _box_of(r, c)
            used = row_used[r] | col_used[c] | box_used[b]
            allowed_masks[i] = (ALL & ~used) & ~int(forb_masks[i])

    # Helper to get indices for regions
    region_indices = []
    # Rows
    for r in range(9): region_indices.append(list(range(r*9, (r+1)*9)))
    # Cols
    for c in range(9): region_indices.append(list(range(c, 81, 9)))
    # Boxes
    for b in range(9):
        br, bc = (b // 3) * 3, (b % 3) * 3
        indices = []
        for dr in range(3):
            for dc in range(3):
                indices.append((br + dr) * 9 + (bc + dc))
        region_indices.append(indices)

    # 1. Conjugate Pairs (Strong Links)
    # 某个区域内，某个数字只能填在两个位置
    for indices in region_indices:
        # Count occurrences of each digit 1..9
        digit_counts = np.zeros(10, dtype=int)
        digit_locs = [[] for _ in range(10)]
        
        for idx in indices:
            if grid[idx] != 0: continue
            mask = allowed_masks[idx]
            for d in range(1, 10):
                if (mask >> (d-1)) & 1:
                    digit_counts[d] += 1
                    digit_locs[d].append(idx)
                    
        for d in range(1, 10):
            if digit_counts[d] == 2:
                # Found conjugate pair
                idx1, idx2 = digit_locs[d]
                r1, c1 = idx1 // 9, idx1 % 9
                r2, c2 = idx2 // 9, idx2 % 9
                conj_map[r1, c1] += 1.0
                conj_map[r2, c2] += 1.0

    # 2. ALS (Almost Locked Sets)
    # N cells contain N+1 candidates
    # Search for size N=1..4
    for indices in region_indices:
        # Filter empty cells
        empty_indices = [idx for idx in indices if grid[idx] == 0]
        n_empty = len(empty_indices)
        if n_empty < 1: continue
        
        # Limit N to 4 for performance (ALS typically small)
        max_n = min(n_empty, 4)
        
        for n in range(1, max_n + 1):
            # Check combinations of size n
            for combo in itertools.combinations(empty_indices, n):
                union_mask = 0
                for idx in combo:
                    union_mask |= allowed_masks[idx]
                
                num_candidates = bin(union_mask).count('1')
                if num_candidates == n + 1:
                    # Found ALS
                    for idx in combo:
                        r, c = idx // 9, idx // 9  # Wait, i // 9, i % 9
                        r, c = idx // 9, idx % 9
                        als_map[r, c] += 1.0

    return als_map, conj_map


def state_key_to_tensors(state_key: str) -> Tuple[np.ndarray, np.ndarray]:
    """
    把 digits|forbiddenKey 转为网络输入：
    - x: (C, 9, 9) float32
      C=22：
        - 0-8: one-hot digits (1..9)
        - 9-17: allowed candidates (1..9)
        - 18: filled mask
        - 19: empty mask
        - 20: ALS heatmap (Explicit Feature)
        - 21: Conjugate Pair heatmap (Explicit Feature)
    - mask: (A,) float32
    """
    if "|" not in state_key:
        raise ValueError("bad state_key")
    digits, forb = state_key.split("|", 1)
    if len(digits) != 81:
        raise ValueError("bad digits")
    forb_masks = _parse_forbidden_key(forb)
    
    # Update Channel Count to 22
    x = np.zeros((22, 9, 9), dtype=np.float32)
    grid = np.array([int(ch) for ch in digits], dtype=np.int32)
    
    # Compute Explicit Features
    als_map, conj_map = _get_als_and_conj_maps(grid, forb_masks)
    x[20] = als_map
    x[21] = conj_map

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

