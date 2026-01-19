from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
import time


Digit = int  # 1..9


def rc_of(idx: int) -> Tuple[int, int]:
    return idx // 9, idx % 9


def idx_of(r: int, c: int) -> int:
    return r * 9 + c


def box_of(r: int, c: int) -> int:
    return (r // 3) * 3 + (c // 3)


def fmt_elims(pairs: Iterable[Tuple[int, Optional[int]]]) -> str:
    """
    输出紧凑删数格式：r7c4<>16 r2c3<>8
    - 自动按单元格合并多个数字
    - 数字升序去重
    """
    by_cell: Dict[Tuple[int, int], set[int]] = {}
    for idx, d in pairs:
        if d is None:
            continue
        r0 = (int(idx) // 9) + 1
        c0 = (int(idx) % 9) + 1
        by_cell.setdefault((r0, c0), set()).add(int(d))
    parts: List[str] = []
    for (r0, c0), ds in sorted(by_cell.items(), key=lambda x: (x[0][0], x[0][1])):
        ds_str = "".join(str(x) for x in sorted(ds))
        parts.append(f"r{r0}c{c0}<>{ds_str}")
    return " ".join(parts) if parts else ""


def _filter_new_elims(st: "SudokuState", dels: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """
    性能/稳定性：避免对“已经被删掉的候选”反复做 referee 校验。
    - 只保留尚未被 forbidden 的删数
    - 已填格直接忽略
    """
    out: List[Tuple[int, int]] = []
    for idx, d in dels:
        if st.grid[idx] != 0:
            continue
        bit = 1 << (int(d) - 1)
        if st.forbidden[idx] & bit:
            continue
        out.append((idx, int(d)))
    return out


def parse_puzzle_81(puzzle: str) -> Tuple[List[int], List[bool]]:
    s = puzzle.strip()
    if len(s) != 81:
        raise ValueError("puzzle 必须是 81 位（支持 0 或 . 表示空格）")
    grid: List[int] = [0] * 81
    given: List[bool] = [False] * 81
    for i, ch in enumerate(s):
        if ch == ".":
            v = 0
        elif "0" <= ch <= "9":
            v = int(ch)
        else:
            raise ValueError("puzzle 含非法字符（仅允许 0-9 或 . ）")
        if v != 0:
            if v < 1 or v > 9:
                raise ValueError("puzzle 含非法数字")
            grid[i] = v
            given[i] = True
    return grid, given


def has_conflict(grid: List[int]) -> bool:
    # 行/列/宫重复检测（忽略 0）
    for r in range(9):
        seen = set()
        for c in range(9):
            v = grid[idx_of(r, c)]
            if v == 0:
                continue
            if v in seen:
                return True
            seen.add(v)
    for c in range(9):
        seen = set()
        for r in range(9):
            v = grid[idx_of(r, c)]
            if v == 0:
                continue
            if v in seen:
                return True
            seen.add(v)
    for b in range(9):
        br = (b // 3) * 3
        bc = (b % 3) * 3
        seen = set()
        for rr in range(br, br + 3):
            for cc in range(bc, bc + 3):
                v = grid[idx_of(rr, cc)]
                if v == 0:
                    continue
                if v in seen:
                    return True
                seen.add(v)
    return False


def bit_count(x: int) -> int:
    return x.bit_count()


def digits_from_mask(mask: int) -> List[Digit]:
    out: List[Digit] = []
    for d in range(1, 10):
        if mask & (1 << (d - 1)):
            out.append(d)
    return out


def only_digit(mask: int) -> Optional[Digit]:
    if mask == 0:
        return None
    if mask & (mask - 1) != 0:
        return None
    # lowest set bit
    return (mask.bit_length() - 1) + 1


def base36_2(mask: int) -> str:
    # 0..511 -> 2 chars base36
    return format(mask, "x")  # placeholder, overwritten below


_B36 = "0123456789abcdefghijklmnopqrstuvwxyz"


def mask_to_b36_2(mask: int) -> str:
    if mask < 0 or mask > 511:
        raise ValueError("mask out of range")
    hi = mask // 36
    lo = mask % 36
    return _B36[hi] + _B36[lo]


@dataclass
class Step:
    action_type: str  # "eliminate" | "commit"
    rationale: str
    affected: List[Tuple[int, Optional[int]]]  # (idx, d or None)
    meta: Optional[Dict[str, Any]] = None
    proof: Optional[Dict[str, Any]] = None


@dataclass
class SolveResult:
    status: str  # solved | stuck | invalid
    steps: List[Step]
    snapshots: List[str]  # digits|forbiddenKey


class SudokuState:
    def __init__(self, grid: List[int], given: List[bool]):
        self.grid = grid[:]  # 81 ints
        self.given = given[:]  # 81 bool
        # forbidden: 9-bit mask per cell, bit=1 means eliminated and must not re-add
        self.forbidden = [0] * 81

    def export_digits(self) -> str:
        return "".join(str(v) for v in self.grid)

    def export_forbidden_key(self) -> str:
        return "".join(mask_to_b36_2(m) for m in self.forbidden)

    def export_state_key(self) -> str:
        return f"{self.export_digits()}|{self.export_forbidden_key()}"

    def allowed_mask(self, idx: int) -> int:
        if self.grid[idx] != 0:
            return 0
        r, c = rc_of(idx)
        used = 0
        # row/col/box
        for cc in range(9):
            v = self.grid[idx_of(r, cc)]
            if v:
                used |= 1 << (v - 1)
        for rr in range(9):
            v = self.grid[idx_of(rr, c)]
            if v:
                used |= 1 << (v - 1)
        br = (r // 3) * 3
        bc = (c // 3) * 3
        for rr in range(br, br + 3):
            for cc in range(bc, bc + 3):
                v = self.grid[idx_of(rr, cc)]
                if v:
                    used |= 1 << (v - 1)
        all_mask = (1 << 9) - 1
        allowed = all_mask & ~used
        # respect forbidden
        allowed &= ~self.forbidden[idx]
        return allowed

    def eliminate(self, idx: int, d: Digit) -> bool:
        if self.grid[idx] != 0:
            return False
        bit = 1 << (d - 1)
        if self.forbidden[idx] & bit:
            return False
        self.forbidden[idx] |= bit
        return True

    def commit(self, idx: int, d: Digit) -> bool:
        if self.given[idx]:
            return False
        if self.grid[idx] != 0:
            return False
        # basic legality
        # (we rely on allowed_mask to ensure not conflicting)
        if not (self.allowed_mask(idx) & (1 << (d - 1))):
            return False
        self.grid[idx] = d
        # 填数后：同行/同列/同宫删该数字候选（只删不加）
        r, c = rc_of(idx)
        for cc in range(9):
            j = idx_of(r, cc)
            if j != idx and self.grid[j] == 0:
                self.forbidden[j] |= 1 << (d - 1)
        for rr in range(9):
            j = idx_of(rr, c)
            if j != idx and self.grid[j] == 0:
                self.forbidden[j] |= 1 << (d - 1)
        br = (r // 3) * 3
        bc = (c // 3) * 3
        for rr in range(br, br + 3):
            for cc in range(bc, bc + 3):
                j = idx_of(rr, cc)
                if j != idx and self.grid[j] == 0:
                    self.forbidden[j] |= 1 << (d - 1)
        return True


def _quick_consistent(st: "SudokuState") -> bool:
    # 1) 任意未填格必须还有候选
    for idx in range(81):
        if st.grid[idx] != 0:
            continue
        if st.allowed_mask(idx) == 0:
            return False
    # 2) 任意 house 内任意未完成数字必须至少有一个候选落点
    all_mask = (1 << 9) - 1
    # rows
    for r in range(9):
        used = 0
        empties = []
        for c in range(9):
            v = st.grid[idx_of(r, c)]
            if v:
                used |= 1 << (v - 1)
            else:
                empties.append(idx_of(r, c))
        need = all_mask & ~used
        if need == 0:
            continue
        for d in digits_from_mask(need):
            bit = 1 << (d - 1)
            if not any((st.allowed_mask(i) & bit) for i in empties):
                return False
    # cols
    for c in range(9):
        used = 0
        empties = []
        for r in range(9):
            v = st.grid[idx_of(r, c)]
            if v:
                used |= 1 << (v - 1)
            else:
                empties.append(idx_of(r, c))
        need = all_mask & ~used
        if need == 0:
            continue
        for d in digits_from_mask(need):
            bit = 1 << (d - 1)
            if not any((st.allowed_mask(i) & bit) for i in empties):
                return False
    # boxes
    for b in range(9):
        br = (b // 3) * 3
        bc = (b % 3) * 3
        used = 0
        empties = []
        for rr in range(br, br + 3):
            for cc in range(bc, bc + 3):
                v = st.grid[idx_of(rr, cc)]
                if v:
                    used |= 1 << (v - 1)
                else:
                    empties.append(idx_of(rr, cc))
        need = all_mask & ~used
        if need == 0:
            continue
        for d in digits_from_mask(need):
            bit = 1 << (d - 1)
            if not any((st.allowed_mask(i) & bit) for i in empties):
                return False
    return True




def _has_any_solution_referee(
    st: "SudokuState",
    node_budget: int = 8000,
    time_budget_ms: Optional[int] = None,
) -> Tuple[Optional[bool], int]:
    """
    裁判（仅用于校验“是否仍有解”）：
    - 不产出步骤
    - 不用于兜底求解
    - 节点预算耗尽返回 None（不做结论）
    """
    ALL = (1 << 9) - 1
    grid = st.grid[:]
    forb = st.forbidden[:]

    row_used = [0] * 9
    col_used = [0] * 9
    box_used = [0] * 9
    for i, v in enumerate(grid):
        if v == 0:
            continue
        r = i // 9
        c = i % 9
        b = box_of(r, c)
        bit = 1 << (v - 1)
        if (row_used[r] & bit) or (col_used[c] & bit) or (box_used[b] & bit):
            return False, 0
        row_used[r] |= bit
        col_used[c] |= bit
        box_used[b] |= bit

    nodes = 0
    t0 = time.perf_counter()

    def allowed_mask_local(i: int) -> int:
        if grid[i] != 0:
            return 0
        r = i // 9
        c = i % 9
        b = box_of(r, c)
        used = row_used[r] | col_used[c] | box_used[b]
        return (ALL & ~used) & ~forb[i]

    def dfs() -> Optional[bool]:
        nonlocal nodes
        nodes += 1
        if time_budget_ms is not None:
            if (time.perf_counter() - t0) * 1000.0 >= float(time_budget_ms):
                return None
        if nodes > node_budget:
            return None
        best = -1
        best_mask = 0
        best_cnt = 99
        for i in range(81):
            if grid[i] != 0:
                continue
            m = allowed_mask_local(i)
            cnt = m.bit_count()
            if cnt == 0:
                return False
            if cnt < best_cnt:
                best_cnt = cnt
                best = i
                best_mask = m
                if cnt == 1:
                    break
        if best == -1:
            return True

        r = best // 9
        c = best % 9
        b = box_of(r, c)
        m = best_mask
        while m:
            lsb = m & -m
            bit = lsb.bit_length() - 1
            d = bit + 1
            m ^= lsb
            vbit = 1 << bit
            grid[best] = d
            row_used[r] |= vbit
            col_used[c] |= vbit
            box_used[b] |= vbit
            res = dfs()
            if res is True:
                return True
            if res is None:
                return None
            row_used[r] ^= vbit
            col_used[c] ^= vbit
            box_used[b] ^= vbit
            grid[best] = 0
        return False

    r = dfs()
    return r, nodes

def iter_house_cells(kind: str, k: int) -> Iterable[int]:
    if kind == "row":
        r = k
        for c in range(9):
            yield idx_of(r, c)
    elif kind == "col":
        c = k
        for r in range(9):
            yield idx_of(r, c)
    elif kind == "box":
        br = (k // 3) * 3
        bc = (k % 3) * 3
        for rr in range(br, br + 3):
            for cc in range(bc, bc + 3):
                yield idx_of(rr, cc)
    else:
        raise ValueError("unknown house kind")


def solve_logic_only(puzzle: str, max_steps: int = 500) -> SolveResult:
    grid, given = parse_puzzle_81(puzzle)
    if has_conflict(grid):
        return SolveResult(status="invalid", steps=[], snapshots=[SudokuState(grid, given).export_state_key()])

    st = SudokuState(grid, given)
    steps: List[Step] = []
    snapshots: List[str] = [st.export_state_key()]

    def push_snapshot():
        snapshots.append(st.export_state_key())

    for _ in range(max_steps):
        # solved?
        if all(v != 0 for v in st.grid):
            return SolveResult(status="solved", steps=steps, snapshots=snapshots)

        progressed = False

        # 1) Naked single: cell has only one candidate
        for idx in range(81):
            if st.grid[idx] != 0:
                continue
            mask = st.allowed_mask(idx)
            if mask == 0:
                # contradiction -> treat as stuck (no guessing, no backtrack)
                return SolveResult(status="stuck", steps=steps, snapshots=snapshots)
            d = only_digit(mask)
            if d is None:
                continue
            r, c = rc_of(idx)
            ok = st.commit(idx, d)
            if not ok:
                return SolveResult(status="stuck", steps=steps, snapshots=snapshots)
            steps.append(
                Step(
                    action_type="commit",
                    rationale=f"单元格唯一候选：r{r+1}c{c+1} 仅剩 {d}，因此填入",
                    affected=[(idx, d)],
                )
            )
            push_snapshot()
            progressed = True
            break
        if progressed:
            continue

        # 2) Hidden single: in a house, digit appears only in one cell candidate list
        for kind in ("row", "col", "box"):
            for k in range(9):
                pos = {d: [] for d in range(1, 10)}
                for idx in iter_house_cells(kind, k):
                    if st.grid[idx] != 0:
                        continue
                    mask = st.allowed_mask(idx)
                    for d in digits_from_mask(mask):
                        pos[d].append(idx)
                for d, cells in pos.items():
                    if len(cells) == 1:
                        idx = cells[0]
                        r, c = rc_of(idx)
                        ok = st.commit(idx, d)
                        if not ok:
                            continue
                        steps.append(
                            Step(
                                action_type="commit",
                                rationale=f"位置唯一：在{kind}{k+1}中数字 {d} 只能放在 r{r+1}c{c+1}，因此填入",
                                affected=[(idx, d)],
                            )
                        )
                        push_snapshot()
                        progressed = True
                        break
                if progressed:
                    break
            if progressed:
                break
        if progressed:
            continue

        # 3) Naked pair elimination (简化版，示例推理链传递)
        # 在同一屋内，两个格候选完全相同且为 2 个数 -> 其它格删这两个数
        for kind in ("row", "col", "box"):
            for k in range(9):
                masks: List[Tuple[int, int]] = []
                for idx in iter_house_cells(kind, k):
                    if st.grid[idx] != 0:
                        continue
                    m = st.allowed_mask(idx)
                    if bit_count(m) == 2:
                        masks.append((idx, m))
                # group by mask
                by_mask = {}
                for idx, m in masks:
                    by_mask.setdefault(m, []).append(idx)
                for m, idxs in by_mask.items():
                    if len(idxs) != 2:
                        continue
                    ds = digits_from_mask(m)
                    affected: List[Tuple[int, Optional[int]]] = []
                    changed_any = False
                    for idx2 in iter_house_cells(kind, k):
                        if idx2 in idxs or st.grid[idx2] != 0:
                            continue
                        for d in ds:
                            if st.allowed_mask(idx2) & (1 << (d - 1)):
                                if st.eliminate(idx2, d):
                                    changed_any = True
                                    affected.append((idx2, d))
                    if changed_any:
                        a0r, a0c = rc_of(idxs[0])
                        a1r, a1c = rc_of(idxs[1])
                        steps.append(
                            Step(
                                action_type="eliminate",
                                rationale=(
                                    f"数对传递：{kind}{k+1} 中 r{a0r+1}c{a0c+1} 与 r{a1r+1}c{a1c+1} "
                                    f"仅有候选 {ds}，删数 {fmt_elims(affected)}"
                                ),
                                affected=affected,
                            )
                        )
                        push_snapshot()
                        progressed = True
                        break
                if progressed:
                    break
            if progressed:
                break

        if progressed:
            continue

        # no progress -> stuck (按你的要求：不猜测)
        return SolveResult(status="stuck", steps=steps, snapshots=snapshots)

    return SolveResult(status="stuck", steps=steps, snapshots=snapshots)


def solve_with_rank(
    puzzle: str,
    max_steps: int = 800,
    min_t: int = 1,
    max_t: int = 8,
    max_r: int = 6,
    max_structures_per_step: int = 200,
    truth_types: Optional[List[str]] = None,
    enable_ur1: bool = True,
    use_policy: bool = False,
    on_emit: Optional[Callable[[int, Optional[Step], str], None]] = None,
    rank_time_budget_ms: int = 1200,
    on_rank_heartbeat: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> SolveResult:
    """
    后端“秩逻辑（Truth/Link/R）驱动”的求解主循环：
    - 先做基础强制：单元格唯一/位置唯一
    - 再搜索秩结构，按删数公理删除候选
    - 删除后继续强制填数
    - 不猜测：无进展则 stuck
    """
    from .rank_engine import (
        FoundStructure,
        RegionRef,
        SearchCache,
        SudokuState as RankState,
        compute_deletable_candidates,
        compute_deletable_candidates_with_proof,
        resolve_group,
        search_rank_structures,
        search_rank_fish_r0_fast,
        search_rank_house_to_cells_fast,
        search_rank_t1_house_fast,
    )
    from .learn_params import get_params
    from .techlib_store import load_techlib
    from .policy_runtime import score_actions, evaluate_state

    grid, given = parse_puzzle_81(puzzle)
    if has_conflict(grid):
        st0 = SudokuState(grid, given)
        return SolveResult(status="invalid", steps=[], snapshots=[st0.export_state_key()])

    # 默认：暂不考虑单元格维度（你明确要求的 324 维度思想）
    if truth_types is None:
        truth_types = ["rowDigit", "colDigit", "boxDigit"]
    # link_types：允许与 truth_types 同维/跨维混用。
    # 关键约束由 rank_engine 的删数公理保证：
    # - Links 必须覆盖 Truth 候选全集（truth ⊆ covered）
    # - 对于属于 Truth 的候选，不允许被“同类型区域”再次覆盖（避免同维自证）
    # 因此这里不再默认剔除 cell；当用户启用 cell 时，cell 也可作为弱区域参与覆盖/删数。
    link_types = list(truth_types)
    # 单元格维度：当用户显式勾选 cell 时，启用“同屋 N格=N数”的子集删数（naked subset）
    enable_cell_subset = ("cell" in truth_types)

    # 使用同一份 grid/given/forbidden 做求解；rank_engine 用其自身的 SudokuState
    st = SudokuState(grid, given)
    steps: List[Step] = []
    snapshots: List[str] = [st.export_state_key()]

    def push_snapshot():
        snapshots.append(st.export_state_key())

    def _emit(idx: int, step: Optional[Step], snap: str) -> None:
        if not on_emit:
            return
        try:
            on_emit(int(idx), step, str(snap))
        except Exception:
            # 任何 UI 回调失败都不应中断求解
            return

    # 初始化快照（step_index=0）
    _emit(0, None, snapshots[0])

    def _push_step(step: Step) -> None:
        steps.append(step)
        push_snapshot()
        _emit(len(steps), step, snapshots[-1])

    def _invalidate(
        reason: str,
        attempted: Optional[List[Tuple[int, int]]] = None,
        meta: Optional[Dict[str, Any]] = None,
        proof: Optional[Dict[str, Any]] = None,
    ) -> SolveResult:
        # 关键：invalid 也必须把“本步尝试做了什么”呈现出来，便于审计定位错误删数
        attempted2: List[Tuple[int, Optional[int]]] = []
        if attempted:
            try:
                attempted2 = [(int(idx), int(d)) for (idx, d) in attempted]
            except Exception:
                attempted2 = []
        _push_step(
            Step(
                action_type="eliminate",
                rationale=f"INVALID: {reason} {fmt_elims(attempted2) if attempted2 else ''}".strip(),
                affected=attempted2,
                meta=meta,
                proof=proof,
            )
        )
        return SolveResult(status="invalid", steps=steps, snapshots=snapshots)

    def _validate_elims_before_apply(dels: List[Tuple[int, int]], proof: Dict[str, Any], meta: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        # 复制状态并应用删数，做快速一致性 + 有解性裁判
        st2 = SudokuState(st.grid, st.given)
        st2.forbidden = st.forbidden[:]
        for idx, d in dels:
            st2.eliminate(idx, int(d))
        proof2 = dict(proof or {})
        qok = _quick_consistent(st2)
        # 体验：referee 若在某些盘面上耗时过长，会造成 solve_job “卡在最后一步不动”
        # - 增加 time_budget_ms，超时返回 None（不做结论）
        # - None 时不直接否决（否则会把探索完全卡死），但会在 proof 中标记，reward 也会被惩罚
        if on_rank_heartbeat:
            try:
                on_rank_heartbeat({"phase": "referee", "stage": "start", "dels": int(len(dels))})
            except Exception:
                pass
        t0 = time.perf_counter()
        res, nodes = _has_any_solution_referee(st2, node_budget=5000, time_budget_ms=120) if qok else (False, 0)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        if on_rank_heartbeat:
            try:
                on_rank_heartbeat({"phase": "referee", "stage": "done", "elapsed_ms": int(elapsed_ms), "nodes_used": int(nodes), "result": res})
            except Exception:
                pass
        proof2["referee"] = {
            "quick_consistent": qok,
            "has_any_solution": res,
            "node_budget": 5000,
            "nodes_used": nodes,
            "time_budget_ms": 120,
            "elapsed_ms": int(elapsed_ms),
        }
        if not qok:
            proof2["referee_reason"] = "contradiction"
            return False, proof2
        if res is False:
            proof2["referee_reason"] = "no_solution"
            return False, proof2
        if res is None:
            proof2["referee_reason"] = "timeout"
        return True, proof2

    def force_fills() -> bool:
        progressed = False
        while True:
            moved = False
            # naked single
            for idx in range(81):
                if st.grid[idx] != 0:
                    continue
                mask = st.allowed_mask(idx)
                if mask == 0:
                    return progressed
                d = only_digit(mask)
                if d is None:
                    continue
                r, c = rc_of(idx)
                if not st.commit(idx, d):
                    return progressed
                _push_step(Step(action_type="commit", rationale=f"单元格唯一候选：r{r+1}c{c+1} 仅剩 {d}，因此填入", affected=[(idx, d)]))
                progressed = True
                moved = True
                break
            if moved:
                continue
            # hidden single
            for kind in ("row", "col", "box"):
                for k in range(9):
                    pos = {d: [] for d in range(1, 10)}
                    for idx in iter_house_cells(kind, k):
                        if st.grid[idx] != 0:
                            continue
                        mask = st.allowed_mask(idx)
                        for d in digits_from_mask(mask):
                            pos[d].append(idx)
                    for d, cells in pos.items():
                        if len(cells) == 1:
                            idx = cells[0]
                            r, c = rc_of(idx)
                            if not st.commit(idx, d):
                                continue
                            _push_step(
                                Step(
                                    action_type="commit",
                                    rationale=f"位置唯一：在{kind}{k+1}中数字 {d} 只能放在 r{r+1}c{c+1}，因此填入",
                                    affected=[(idx, d)],
                                )
                            )
                            progressed = True
                            moved = True
                            break
                    if moved:
                        break
                if moved:
                    break
            if moved:
                continue

            # naked subset in a house (cell-based): N cells contain exactly N digits in union
            # 仅当用户显式启用 cell 维度时参与（避免默认路径被“投喂”）
            if enable_cell_subset:
                # 体验：SUBSET 在某些盘面上组合数会暴涨，容易造成“看起来卡死在第4题”。
                # 这里给每次 force_fills 的 subset 扫描一个小时间预算，超时就让出给其它策略/下一轮，
                # 并通过 on_rank_heartbeat 上报进度（不改盘面）。
                subset_t0 = time.perf_counter()
                subset_budget_ms = 60

                def _subset_elapsed_ms() -> int:
                    return int((time.perf_counter() - subset_t0) * 1000)

                def _subset_maybe_yield(phase: str, extra: Dict[str, Any]) -> bool:
                    if _subset_elapsed_ms() < subset_budget_ms:
                        return False
                    if on_rank_heartbeat:
                        try:
                            on_rank_heartbeat({"phase": phase, "elapsed_ms": _subset_elapsed_ms(), **extra})
                        except Exception:
                            pass
                    return True

                def _cell_ref(idx: int) -> Dict[str, Any]:
                    return {"type": "cell", "idx": int(idx)}

                def _house_digit_ref(kind: str, k: int, d: int) -> Dict[str, Any]:
                    if kind == "row":
                        return {"type": "rowDigit", "row": int(k), "d": int(d)}
                    if kind == "col":
                        return {"type": "colDigit", "col": int(k), "d": int(d)}
                    return {"type": "boxDigit", "box": int(k), "d": int(d)}

                def _push_rank_subset(
                    kind: str,
                    k: int,
                    digits: List[int],
                    cell_idxs: List[int],
                    affected: List[Tuple[int, Optional[int]]],
                    proof2: Dict[str, Any],
                    mode: str,
                ) -> None:
                    # 统一：把子集逻辑“转化为秩逻辑”的表达（步骤与技巧库均按 RANK）
                    #
                    # 你最新强调的总原则：
                    # - 发现“候选集合归属”的区域 => 强区域 Truth
                    # - 能执行删数（被覆盖后删候选）的区域 => 弱区域 Link
                    #
                    # 两种视角对应不同的 Truth/Link：
                    # - naked（显性）：N格恰好 N数，必然落在这 N格里
                    #   - Truth：这 N 个单元格（子集所在格）
                    #   - Link ：同屋的 digit-house（每个数字在该屋的候选集合）=> 覆盖其它格的候选以产生删数
                    #
                    # - hidden（隐性）：N种数字只分布在同屋 N格里
                    #   - Truth：同屋的 digit-house（这 N 个数字在该屋的候选集合）
                    #   - Link ：这 N 个单元格（删数发生在这些格内：删除“杂候选”）
                    if mode == "hidden":
                        truths = [_house_digit_ref(kind, k, int(d)) for d in digits]
                        links = [_cell_ref(int(ci)) for ci in cell_idxs]
                    else:
                        truths = [_cell_ref(int(ci)) for ci in cell_idxs]
                        links = [_house_digit_ref(kind, k, int(d)) for d in digits]
                    _push_step(
                        Step(
                            action_type="eliminate",
                            rationale=f"RANK:T{len(truths)}L{len(links)}R0 {fmt_elims(affected)}",
                            affected=affected,
                            meta={
                                "kind": "RANK",
                                "T": int(len(truths)),
                                "L": int(len(links)),
                                "R": 0,
                                "truths": truths,
                                "links": links,
                                "phase": "subset",
                                "subset_mode": str(mode),
                                "subset_digits": [int(x) for x in digits],
                                "subset_cells": [int(x) for x in cell_idxs],
                                "subset_house": {"type": kind, "idx": int(k)},
                            },
                            proof=proof2,
                        )
                    )

                def _try_house_naked_subset(kind: str, k: int, n: int) -> bool:
                    nonlocal invalid_res
                    if _subset_maybe_yield("subset_scan", {"house": f"{kind}{k+1}", "n": int(n)}):
                        return False
                    empties: List[int] = []
                    masks: List[int] = []
                    for idx in iter_house_cells(kind, k):
                        if st.grid[idx] != 0:
                            continue
                        m = st.allowed_mask(idx)
                        bc = bit_count(m)
                        # 子集删数通常来自 2..n 的候选规模；太大组合意义不大
                        if bc < 2 or bc > n:
                            continue
                        empties.append(idx)
                        masks.append(m)
                    if len(empties) < n:
                        return False

                    def _apply_subset(cell_idxs: List[int], union_mask: int) -> bool:
                        # 显性视角（naked subset）：N格里恰好 N 种候选数
                        # -> 这 N 种数必须落在这 N 格中
                        # -> 同屋其它格删除这些数字候选
                        digits = digits_from_mask(union_mask)
                        dels: List[Tuple[int, int]] = []
                        cell_set = set(cell_idxs)
                        for idx2 in iter_house_cells(kind, k):
                            if idx2 in cell_set or st.grid[idx2] != 0:
                                continue
                            m2 = st.allowed_mask(idx2)
                            for d2 in digits:
                                if m2 & (1 << (d2 - 1)):
                                    dels.append((idx2, int(d2)))
                        if not dels:
                            return False
                        dels = _filter_new_elims(st, dels)
                        if not dels:
                            return False
                        proof0 = {
                            "kind": "RANK",
                            "house": {"type": kind, "idx": int(k)},
                            "n": int(n),
                            "cells": [int(x) for x in cell_idxs],
                            "digits": [int(x) for x in digits],
                            "mode": "naked",
                        }
                        ok, proof2 = _validate_elims_before_apply(dels, proof0, {"kind": "RANK"})
                        if not ok:
                            # invalid 时也要把结构（Truth/Link）带出来，便于审计
                            truths = [_cell_ref(int(ci)) for ci in cell_idxs]
                            links = [_house_digit_ref(kind, k, int(d)) for d in digits]
                            invalid_res = _invalidate(
                                "子集删数（naked subset）导致矛盾/无解（裁判否决）",
                                attempted=dels,
                                meta={
                                    "kind": "RANK",
                                    "T": int(len(truths)),
                                    "L": int(len(links)),
                                    "R": 0,
                                    "truths": truths,
                                    "links": links,
                                    "phase": "subset",
                                    "subset_mode": "naked",
                                    "subset_digits": [int(x) for x in digits],
                                    "subset_cells": [int(x) for x in cell_idxs],
                                    "subset_house": {"type": kind, "idx": int(k)},
                                },
                                proof=proof2,
                            )
                            return True
                        affected: List[Tuple[int, Optional[int]]] = []
                        for idx2, d2 in dels:
                            if st.eliminate(idx2, int(d2)):
                                affected.append((idx2, int(d2)))
                        if not affected:
                            return False
                        _push_rank_subset(kind, k, [int(x) for x in digits], [int(x) for x in cell_idxs], affected, proof2, "naked")
                        return True

                    # 组合枚举：按 n 从小到大、按索引顺序，保证稳定且“体量小优先”
                    mlen = len(empties)
                    if n == 2:
                        for i in range(mlen - 1):
                            for j in range(i + 1, mlen):
                                if _subset_maybe_yield("subset_scan", {"house": f"{kind}{k+1}", "n": 2}):
                                    return False
                                u = masks[i] | masks[j]
                                if bit_count(u) != 2:
                                    continue
                                if _apply_subset([empties[i], empties[j]], u):
                                    return True
                    elif n == 3:
                        for i in range(mlen - 2):
                            for j in range(i + 1, mlen - 1):
                                if _subset_maybe_yield("subset_scan", {"house": f"{kind}{k+1}", "n": 3}):
                                    return False
                                u2 = masks[i] | masks[j]
                                if bit_count(u2) > 3:
                                    continue
                                for t in range(j + 1, mlen):
                                    if _subset_maybe_yield("subset_scan", {"house": f"{kind}{k+1}", "n": 3}):
                                        return False
                                    u = u2 | masks[t]
                                    if bit_count(u) != 3:
                                        continue
                                    if _apply_subset([empties[i], empties[j], empties[t]], u):
                                        return True
                    else:  # n == 4
                        for i in range(mlen - 3):
                            for j in range(i + 1, mlen - 2):
                                if _subset_maybe_yield("subset_scan", {"house": f"{kind}{k+1}", "n": 4}):
                                    return False
                                u2 = masks[i] | masks[j]
                                if bit_count(u2) > 4:
                                    continue
                                for t in range(j + 1, mlen - 1):
                                    if _subset_maybe_yield("subset_scan", {"house": f"{kind}{k+1}", "n": 4}):
                                        return False
                                    u3 = u2 | masks[t]
                                    if bit_count(u3) > 4:
                                        continue
                                    for q in range(t + 1, mlen):
                                        if _subset_maybe_yield("subset_scan", {"house": f"{kind}{k+1}", "n": 4}):
                                            return False
                                        u = u3 | masks[q]
                                        if bit_count(u) != 4:
                                            continue
                                        if _apply_subset([empties[i], empties[j], empties[t], empties[q]], u):
                                            return True
                    return False

                def _try_house_hidden_subset(kind: str, k: int, n: int) -> bool:
                    # 隐性视角（hidden subset）：N种数字只分布在同屋 N格里（这些格可以有其它候选）
                    # -> 这些 N格里除这 N种数字外的其它候选必须删除（否则会放不下这 N种数字）
                    nonlocal invalid_res
                    if _subset_maybe_yield("subset_scan", {"house": f"{kind}{k+1}", "n": int(n)}):
                        return False
                    empties: List[int] = [idx for idx in iter_house_cells(kind, k) if st.grid[idx] == 0]
                    if len(empties) < n:
                        return False

                    # digit -> bitset of positions (within empties list)
                    pos: Dict[int, int] = {d: 0 for d in range(1, 10)}
                    for i, idx in enumerate(empties):
                        m = st.allowed_mask(idx)
                        if m == 0:
                            continue
                        for d in digits_from_mask(m):
                            pos[int(d)] |= 1 << i

                    digits_list = [d for d in range(1, 10) if pos[d] != 0]
                    if len(digits_list) < n:
                        return False

                    def _cells_from_mask(mask: int) -> List[int]:
                        out: List[int] = []
                        for i in range(len(empties)):
                            if mask & (1 << i):
                                out.append(int(empties[i]))
                        return out

                    # enumerate digit combinations (n=2..4)
                    dl = digits_list
                    L = len(dl)
                    def _handle(ds: List[int]) -> bool:
                        union = 0
                        for d in ds:
                            union |= pos[int(d)]
                        if union == 0 or union.bit_count() != n:
                            return False
                        cell_idxs = _cells_from_mask(union)
                        # 删除这些格中除 ds 之外的候选
                        keep_mask = 0
                        for d in ds:
                            keep_mask |= 1 << (int(d) - 1)
                        dels: List[Tuple[int, int]] = []
                        for idx in cell_idxs:
                            m = st.allowed_mask(idx)
                            other = m & ~keep_mask
                            if other == 0:
                                continue
                            for d2 in digits_from_mask(other):
                                dels.append((int(idx), int(d2)))
                        if not dels:
                            return False
                        dels = _filter_new_elims(st, dels)
                        if not dels:
                            return False
                        proof0 = {
                            "kind": "RANK",
                            "house": {"type": kind, "idx": int(k)},
                            "n": int(n),
                            "cells": [int(x) for x in cell_idxs],
                            "digits": [int(x) for x in ds],
                            "mode": "hidden",
                        }
                        ok, proof2 = _validate_elims_before_apply(dels, proof0, {"kind": "RANK"})
                        if not ok:
                            truths = [_house_digit_ref(kind, k, int(d)) for d in ds]
                            links = [_cell_ref(int(ci)) for ci in cell_idxs]
                            invalid_res = _invalidate(
                                "子集删数（hidden subset）导致矛盾/无解（裁判否决）",
                                attempted=dels,
                                meta={
                                    "kind": "RANK",
                                    "T": int(len(truths)),
                                    "L": int(len(links)),
                                    "R": 0,
                                    "truths": truths,
                                    "links": links,
                                    "phase": "subset",
                                    "subset_mode": "hidden",
                                    "subset_digits": [int(x) for x in ds],
                                    "subset_cells": [int(x) for x in cell_idxs],
                                    "subset_house": {"type": kind, "idx": int(k)},
                                },
                                proof=proof2,
                            )
                            return True
                        affected: List[Tuple[int, Optional[int]]] = []
                        for idx2, d2 in dels:
                            if st.eliminate(idx2, int(d2)):
                                affected.append((idx2, int(d2)))
                        if not affected:
                            return False
                        _push_rank_subset(kind, k, [int(x) for x in ds], [int(x) for x in cell_idxs], affected, proof2, "hidden")
                        return True

                    if n == 2:
                        for i in range(L - 1):
                            for j in range(i + 1, L):
                                if _subset_maybe_yield("subset_scan", {"house": f"{kind}{k+1}", "n": 2}):
                                    return False
                                if _handle([dl[i], dl[j]]):
                                    return True
                    elif n == 3:
                        for i in range(L - 2):
                            for j in range(i + 1, L - 1):
                                for t in range(j + 1, L):
                                    if _subset_maybe_yield("subset_scan", {"house": f"{kind}{k+1}", "n": 3}):
                                        return False
                                    if _handle([dl[i], dl[j], dl[t]]):
                                        return True
                    else:  # n == 4
                        for i in range(L - 3):
                            for j in range(i + 1, L - 2):
                                for t in range(j + 1, L - 1):
                                    for q in range(t + 1, L):
                                        if _subset_maybe_yield("subset_scan", {"house": f"{kind}{k+1}", "n": 4}):
                                            return False
                                        if _handle([dl[i], dl[j], dl[t], dl[q]]):
                                            return True
                    return False

                # 在任意一个 house 命中一次就返回，让主循环逐步展示步骤（并触发后续强制填数链）
                subset_progress = False
                for kind in ("row", "col", "box"):
                    for k in range(9):
                        for n in (2, 3, 4):
                            # 先隐性，再显性：隐性子集往往更关键（能删掉子集格内的“杂候选”）
                            if _try_house_hidden_subset(kind, k, n) or _try_house_naked_subset(kind, k, n):
                                subset_progress = True
                                break
                        if subset_progress:
                            break
                    if subset_progress:
                        break
                if subset_progress:
                    progressed = True
                    moved = True
                    continue
            if not moved:
                return progressed


    def try_ur_type1() -> bool:
        """
        Unique Rectangle（UR）Type-1（与你的例子一致）：
        - 选择两行两列形成 4 格矩形
        - 该矩形必须落在“恰好 2 个宫”内（否则不构成经典 UR 致死结构）
          - 允许：同一 band(三行) + 跨两个 stack(三列)  => 两个宫
          - 允许：同一 stack(三列) + 跨两个 band(三行) => 两个宫
          - 排除：四角跨 4 个宫；排除：四格同一宫
        - 若四格共同包含同一对数字 {a,b}（common=2位）
        - 且其中 3 格候选恰为 {a,b}，另 1 格为 {a,b}+X
        则在“带额外候选”的那一格中，a/b 不能成立（否则会产生两种填法 => 多解），因此可删除 a/b。
        """
        progressed = False
        nonlocal invalid_res
        # 遍历所有 2x2 矩形
        for r1 in range(8):
            for r2 in range(r1 + 1, 9):
                for c1 in range(8):
                    for c2 in range(c1 + 1, 9):
                        # UR 的矩形必须落在“恰好 2 个宫”内：
                        # - r1,r2 同 band 且 c1,c2 不同 stack -> 2 个宫
                        # - c1,c2 同 stack 且 r1,r2 不同 band -> 2 个宫
                        same_band = (r1 // 3) == (r2 // 3)
                        same_stack = (c1 // 3) == (c2 // 3)
                        if same_band == same_stack:
                            # True/True: 同一宫；False/False: 跨 4 宫。两者都不符合 UR 致死结构前提
                            continue
                        idxs = [idx_of(r1, c1), idx_of(r1, c2), idx_of(r2, c1), idx_of(r2, c2)]
                        # 仅考虑未填格
                        if any(st.grid[i] != 0 for i in idxs):
                            continue
                        masks = [st.allowed_mask(i) for i in idxs]
                        if any(m == 0 for m in masks):
                            continue
                        common = masks[0] & masks[1] & masks[2] & masks[3]
                        # common 必须恰好两位
                        if common == 0 or common.bit_count() != 2:
                            continue
                        # 额外候选格：候选数>2
                        extra = [i for i, m in enumerate(masks) if m.bit_count() > 2 and (m & common) == common]
                        pure = [i for i, m in enumerate(masks) if m.bit_count() == 2 and m == common]
                        if len(extra) != 1 or len(pure) != 3:
                            continue

                        extra_idx = idxs[extra[0]]
                        a = (common & -common).bit_length()  # 1..9
                        bmask = common ^ (common & -common)
                        b = bmask.bit_length()

                        dels = [(extra_idx, int(a)), (extra_idx, int(b))]
                        dels = _filter_new_elims(st, dels)
                        if not dels:
                            continue
                        proof0 = {
                            "kind": "UR1",
                            "rows": [r1, r2],
                            "cols": [c1, c2],
                            "ab": [int(a), int(b)],
                            "extra_idx": extra_idx,
                            "box_count": 2,
                        }
                        ok, proof2 = _validate_elims_before_apply(dels, proof0, {"kind": "UR1"})
                        if not ok:
                            invalid_res = _invalidate("UR1 删数导致矛盾/无解（裁判否决）", meta={"kind": "UR1"}, proof=proof2)
                            return True

                        affected = []
                        for idx2, d2 in dels:
                            if st.eliminate(idx2, int(d2)):
                                affected.append((idx2, int(d2)))
                        if not affected:
                            continue

                        rr, cc = rc_of(extra_idx)
                        _push_step(
                            Step(
                                action_type="eliminate",
                                rationale=(
                                    f"UR1:r{r1+1}r{r2+1}c{c1+1}c{c2+1}:ab={a}{b}:extra=r{rr+1}c{cc+1} "
                                    f"{fmt_elims(affected)}"
                                ),
                                affected=affected,
                                meta={
                                    "kind": "UR1",
                                    "rows": [r1, r2],
                                    "cols": [c1, c2],
                                    "ab": [a, b],
                                    "extra_idx": extra_idx,
                                    "box_count": 2,
                                    "same_band": (r1 // 3) == (r2 // 3),
                                    "same_stack": (c1 // 3) == (c2 // 3),
                                },
                                proof=proof2,
                            )
                        )
                        progressed = True
                        return progressed
        return progressed

    cache: SearchCache | None = None
    rank_state = RankState(st.grid, st.given)
    rank_state.forbidden = st.forbidden[:]  # share forbidden

    # 参数约束（按你的要求：默认 Truth<=12，R<=3；并优先小体量组合）
    max_t = min(int(max_t), 12)
    max_r = min(int(max_r), 3)
    min_t = max(1, int(min_t))
    max_structures_per_step = int(max_structures_per_step)

    tl = load_techlib()
    tech_items = list(tl.items.values())
    learn_p = get_params()
    w_rank = float(learn_p.get("w_rank", 1.0))
    w_tech = float(learn_p.get("w_techlib", 1.0))
    w_ur = float(learn_p.get("w_ur", 1.0))

    invalid_res: SolveResult | None = None

    def ref_from_dict(obj: dict) -> RegionRef:
        return RegionRef(
            type=str(obj.get("type")),
            idx=obj.get("idx", None),
            row=obj.get("row", None),
            col=obj.get("col", None),
            box=obj.get("box", None),
            d=obj.get("d", None),
        )

    def try_techlib_rank() -> bool:
        """
        技巧库参与求解：在基础逻辑之后，尝试把技巧库里的 RANK 结构重放到当前盘面：
        - 用 features.truths / features.links 重建 FoundStructure
        - 计算删数（同删数公理）
        - 若能删则落地并记录一步（meta.source=techlib）
        """
        progressed_local = False
        nonlocal invalid_res
        if not tech_items:
            return False
        rank_state.grid = st.grid[:]
        rank_state.forbidden = st.forbidden[:]

        # 基线策略：按出现次数从高到低尝试（更可能命中常见结构）
        items_sorted = sorted((x for x in tech_items if x.get("kind") == "RANK"), key=lambda it: int(it.get("seen_count", 0)), reverse=True)

        # policy 策略：对每条技巧用“删数动作 logits”打分，优先尝试高分条目（仍受裁判闸门约束）
        if use_policy and snapshots:
            try:
                state_key = snapshots[-1]
                scored = []
                for it0 in items_sorted[:600]:
                    ex = (it0.get("example") or {})
                    dels0 = ex.get("deletions") or []
                    acts0 = [("eliminate", int(x.get("idx")), int(x.get("d"))) for x in dels0 if x.get("idx") is not None and x.get("d") is not None]
                    if not acts0:
                        continue
                    ss = score_actions(state_key, acts0)
                    scored.append((float(sum(ss)), it0))
                scored.sort(key=lambda x: x[0], reverse=True)
                if scored:
                    items_sorted = [x[1] for x in scored] + [x for x in items_sorted if x not in {y[1] for y in scored}]
            except Exception:
                pass

        for it in items_sorted[:200]:
            features = it.get("features", {}) or {}
            truths_raw = features.get("truths", []) or []
            links_raw = features.get("links", []) or []
            if not truths_raw or not links_raw:
                continue
            try:
                truths = [ref_from_dict(x) for x in truths_raw]
                links = [ref_from_dict(x) for x in links_raw]
            except Exception:
                continue

            # 性能/正确性剪枝：Truth 组合不应落在已填格（提示数或推导填数）上
            # - cell Truth/Link 指向已填格 => resolve_group 一定为空 => 冤枉路，直接跳过
            dead = False
            for r0 in truths:
                if r0.type == "cell":
                    idx0 = int(r0.idx or 0)
                    if idx0 < 0 or idx0 >= 81 or st.grid[idx0] != 0:
                        dead = True
                        break
            if dead:
                continue
            for r0 in links:
                if r0.type == "cell":
                    idx0 = int(r0.idx or 0)
                    if idx0 < 0 or idx0 >= 81 or st.grid[idx0] != 0:
                        dead = True
                        break
            if dead:
                continue

            # 进一步剪枝：row/col/box digit Truth 若该 house 已经出现该数字，则 Truth 必为空
            # （避免进入 compute_deletable + 裁判）
            def _house_has_digit(hkind: str, hk: int, d: int) -> bool:
                if hkind == "row":
                    return any(st.grid[idx_of(hk, c)] == d for c in range(9))
                if hkind == "col":
                    return any(st.grid[idx_of(r, hk)] == d for r in range(9))
                br = (hk // 3) * 3
                bc = (hk % 3) * 3
                for rr in range(br, br + 3):
                    for cc in range(bc, bc + 3):
                        if st.grid[idx_of(rr, cc)] == d:
                            return True
                return False

            for t0 in truths:
                if t0.type == "rowDigit":
                    if _house_has_digit("row", int(t0.row or 0), int(t0.d or 0)):
                        dead = True
                        break
                elif t0.type == "colDigit":
                    if _house_has_digit("col", int(t0.col or 0), int(t0.d or 0)):
                        dead = True
                        break
                elif t0.type == "boxDigit":
                    if _house_has_digit("box", int(t0.box or 0), int(t0.d or 0)):
                        dead = True
                        break
            if dead:
                continue

            # 最后再做一次轻量检查：Truth 的候选集合若为空，直接跳过（不进入删数计算与裁判）
            truth_any = False
            for t0 in truths:
                if resolve_group(rank_state, t0):
                    truth_any = True
                    break
            if not truth_any:
                continue

            s = FoundStructure(T=len(truths), L=len(links), R=max(0, len(links) - len(truths)), truths=truths, links=links)
            if s.R > max_r:
                continue
            dels, proof = compute_deletable_candidates_with_proof(rank_state, s)
            dels = _filter_new_elims(st, dels)
            if not dels:
                continue
            if not dels:
                continue
            ok, proof2 = _validate_elims_before_apply(dels, proof, {"kind": "RANK", "source": "techlib"})
            if not ok:
                invalid_res = _invalidate(
                    "techlib-RANK 删数导致矛盾/无解（裁判否决）",
                    attempted=dels,
                    meta={
                        "kind": "RANK",
                        "source": "techlib",
                        "T": s.T,
                        "L": s.L,
                        "R": s.R,
                        "truths": [t.__dict__ for t in truths],
                        "links": [l.__dict__ for l in links],
                        "phase": "techlib",
                    },
                    proof=proof2,
                )
                return True
            affected = []
            for idx, d in dels:
                if st.eliminate(idx, d):
                    affected.append((idx, d))
            if not affected:
                continue
            _push_step(
                Step(
                    action_type="eliminate",
                    rationale=f"TECHLIB:RANK:T{s.T}L{s.L}R{s.R} {fmt_elims(affected)}",
                    affected=affected,
                    meta={
                        "kind": "RANK",
                        "source": "techlib",
                        "T": s.T,
                        "L": s.L,
                        "R": s.R,
                        "truths": [t.__dict__ for t in truths],
                        "links": [l.__dict__ for l in links],
                    },
                    proof=proof2,
                )
            )
            progressed_local = True
            return progressed_local
        return progressed_local

    # 1) 先强制填数一轮（基础逻辑：唯一数/唯一位置）
    force_fills()
    # 2) UR（唯一性逻辑）
    if enable_ur1 and try_ur_type1():
        # UR 后可能触发新的强制填数
        force_fills()
    rank_state.grid = st.grid[:]
    rank_state.forbidden = st.forbidden[:]

    for _ in range(max_steps):
        if all(v != 0 for v in st.grid):
            return SolveResult(status="solved", steps=steps, snapshots=snapshots)

        progressed = False

        # 网络主导：本轮阶段调度（phase budget / phase choice）
        # - 目标：让 policy/value 决定先探索哪类推理（techlib / rank）
        # - 输出：心跳中带 phase_policy，日志可导出审计
        phase_order = ["techlib", "rank"]
        rank_budget_ms = int(rank_time_budget_ms)
        if use_policy and snapshots:
            try:
                state_key = snapshots[-1]
                t0p = time.perf_counter()
                # 候选动作：techlib(eliminate) / rank(eliminate) 的小样本
                tech_acts: List[Tuple[str, int, int]] = []
                for it0 in tech_items[:80]:
                    if str(it0.get("kind", "")) != "RANK":
                        continue
                    ex = (it0.get("example") or {})
                    dels0 = ex.get("deletions") or []
                    for x in dels0[:10]:
                        if x.get("idx") is None or x.get("d") is None:
                            continue
                        tech_acts.append(("eliminate", int(x.get("idx")), int(x.get("d"))))
                        if len(tech_acts) >= 160:
                            break
                    if len(tech_acts) >= 160:
                        break

                # rank 候选：快速采样少量结构，抽取其删数动作作为“阶段代表”
                rank_acts: List[Tuple[str, int, int]] = []
                try:
                    rank_state.grid = st.grid[:]
                    rank_state.forbidden = st.forbidden[:]
                    genp = search_rank_structures(
                        rank_state,
                        min_t=1,
                        max_t=min(4, int(max_t)),
                        max_r=min(1, int(max_r)),
                        max_results=80,
                        existing_cache=cache,
                        truth_types=truth_types,
                        time_budget_ms=80,
                        on_heartbeat=None,
                        link_types=link_types,
                    )
                    for _k in range(30):
                        sp = next(genp)
                        dels1, _p1 = compute_deletable_candidates_with_proof(rank_state, sp)
                        for (ii, dd) in dels1[:8]:
                            rank_acts.append(("eliminate", int(ii), int(dd)))
                            if len(rank_acts) >= 180:
                                break
                        if len(rank_acts) >= 180:
                            break
                except Exception:
                    pass

                def score_phase(acts: List[Tuple[str, int, int]]) -> float:
                    if not acts:
                        return -1e18
                    ss = score_actions(state_key, acts)
                    # 用 top-k 均值更稳（避免单个极值噪声）
                    xs = sorted([float(x) for x in ss], reverse=True)[: min(12, len(ss))]
                    return float(sum(xs) / max(1, len(xs)))

                s_tech = score_phase(tech_acts)
                s_rank = score_phase(rank_acts)
                v0 = evaluate_state(state_key)
                scores = {"techlib": s_tech, "rank": s_rank}
                phase_order = sorted(scores.keys(), key=lambda k: float(scores[k]), reverse=True)

                # rank 预算：当 rank 分数显著领先时加预算，否则减一点（避免长时间卡同一轮）
                best = float(scores[phase_order[0]])
                second = float(scores[phase_order[1]]) if len(phase_order) > 1 else -1e18
                gap = best - second
                base = int(rank_time_budget_ms)
                if phase_order[0] == "rank" and gap > 0.5:
                    rank_budget_ms = int(min(3000, max(400, base + 600)))
                elif phase_order[0] != "rank" and gap > 0.5:
                    rank_budget_ms = int(max(300, base - 350))
                else:
                    rank_budget_ms = int(base)

                if on_rank_heartbeat:
                    try:
                        on_rank_heartbeat(
                            {
                                "phase": "phase_policy",
                                "elapsed_ms": int((time.perf_counter() - t0p) * 1000),
                                "order": list(phase_order),
                                "scores": {k: float(v) for k, v in scores.items()},
                                "rank_budget_ms": int(rank_budget_ms),
                                "value": (float(v0) if v0 is not None else None),
                            }
                        )
                    except Exception:
                        pass
            except Exception:
                pass

        # 3) 让“策略权重”影响尝试顺序（体现自我迭代）
        # - 仍然遵守：基础逻辑永远在最前
        # - 在秩结构搜索与技巧库重放之间，按权重决定谁先
        # - UR 作为另一类底层逻辑，可按权重在本轮更早尝试
        prefer_tech_first = w_tech >= w_rank
        prefer_ur_early = w_ur > (w_rank + w_tech) / 2.0

        if enable_ur1 and prefer_ur_early and try_ur_type1():
            if invalid_res is not None:
                return invalid_res
            progressed = True
            if force_fills():
                progressed = True
            continue

        # phase-policy 主导的顺序：techlib / rank（只影响“先试什么”，不改变逻辑正确性）
        if phase_order and phase_order[0] == "techlib":
            if try_techlib_rank():
                if invalid_res is not None:
                    return invalid_res
                progressed = True
                if force_fills():
                    progressed = True
                continue

        # 4) 秩逻辑推理：从体量小/低秩开始尝试（rank0优先）
        rank_state.grid = st.grid[:]
        rank_state.forbidden = st.forbidden[:]

        def try_rank_with_r_limit(r_limit: int) -> bool:
            nonlocal cache
            nonlocal invalid_res

            # 0) 先跑 T=1 的快速遍历（row/col/box×digit），这是最快最常见的区块删数来源
            #    按你的要求：每次新盘面都要先把这类技巧“跑到无进展”为止，再进入多T组合。
            while True:
                rank_state.grid = st.grid[:]
                rank_state.forbidden = st.forbidden[:]
                gen0 = search_rank_t1_house_fast(
                    rank_state,
                    max_results=max_structures_per_step,
                    existing_cache=cache,
                    truth_types=truth_types,
                    link_types=link_types,
                    # T=1 fastpass 必须完整扫一遍（你要求“每次新盘面先把这类技巧过一遍”）
                    # 不应被 rank_time_budget 截断，否则会出现“明明有T=1，但进度里进入多T”的现象。
                    time_budget_ms=None,
                    on_heartbeat=on_rank_heartbeat,
                )
                progressed_t1 = False
                try:
                    while True:
                        s0 = next(gen0)
                        assert isinstance(s0, FoundStructure)
                        dels0, proof0 = compute_deletable_candidates_with_proof(rank_state, s0)
                        dels0 = _filter_new_elims(st, dels0)
                        if not dels0:
                            continue
                        if not dels0:
                            continue
                        ok0, proof02 = _validate_elims_before_apply(dels0, proof0, {"kind": "RANK"})
                        if not ok0:
                            invalid_res = _invalidate(
                                "RANK(T=1) 删数导致矛盾/无解（裁判否决）",
                                attempted=dels0,
                                meta={
                                    "kind": "RANK",
                                    "T": s0.T,
                                    "L": s0.L,
                                    "R": s0.R,
                                    "truths": [t.__dict__ for t in s0.truths],
                                    "links": [l.__dict__ for l in s0.links],
                                    "phase": "t1_fast",
                                },
                                proof=proof02,
                            )
                            return True
                        affected0 = []
                        for idx, d in dels0:
                            if st.eliminate(idx, d):
                                affected0.append((idx, d))
                        if affected0:
                            _push_step(
                                Step(
                                    action_type="eliminate",
                                    rationale=f"RANK:T1L1R0 {fmt_elims(affected0)}",
                                    affected=affected0,
                                    meta={
                                        "kind": "RANK",
                                        "T": s0.T,
                                        "L": s0.L,
                                        "R": s0.R,
                                        "truths": [t.__dict__ for t in s0.truths],
                                        "links": [l.__dict__ for l in s0.links],
                                        "phase": "t1_fast",
                                    },
                                    proof=proof02,
                                )
                            )
                            force_fills()
                            progressed_t1 = True
                            break
                except StopIteration as e:
                    cache = e.value if hasattr(e, "value") else cache
                except Exception:
                    pass
                if progressed_t1:
                    continue
                break

            # 1) rank0 fish fastpass（例①视角）：n个Truth house-digit confined to n个Link house-digit
            # 每次新盘面在进入多T组合前，先把这类结构跑到无进展为止（体量小、命中高）
            while True:
                rank_state.grid = st.grid[:]
                rank_state.forbidden = st.forbidden[:]
                genf = search_rank_fish_r0_fast(
                    rank_state,
                    n_min=2,
                    n_max=4,
                    max_results=max_structures_per_step,
                    existing_cache=cache,
                    truth_types=truth_types,
                    link_types=link_types,
                    time_budget_ms=None,  # fastpass 必须完整扫一遍（与你的“每盘面先过一遍”一致）
                    on_heartbeat=on_rank_heartbeat,
                )
                progressed_f = False
                try:
                    while True:
                        sf = next(genf)
                        assert isinstance(sf, FoundStructure)
                        delsf, prooff = compute_deletable_candidates_with_proof(rank_state, sf)
                        delsf = _filter_new_elims(st, delsf)
                        if not delsf:
                            continue
                        okf, proof2f = _validate_elims_before_apply(delsf, prooff, {"kind": "RANK"})
                        if not okf:
                            invalid_res = _invalidate(
                                "RANK(fish_fast) 删数导致矛盾/无解（裁判否决）",
                                attempted=delsf,
                                meta={
                                    "kind": "RANK",
                                    "T": sf.T,
                                    "L": sf.L,
                                    "R": 0,
                                    "truths": [t.__dict__ for t in sf.truths],
                                    "links": [l.__dict__ for l in sf.links],
                                    "phase": "fish_fast",
                                },
                                proof=proof2f,
                            )
                            return True
                        affectedf = []
                        for idx, d in delsf:
                            if st.eliminate(idx, d):
                                affectedf.append((idx, d))
                        if affectedf:
                            _push_step(
                                Step(
                                    action_type="eliminate",
                                    rationale=f"RANK:T{sf.T}L{sf.L}R0 {fmt_elims(affectedf)}",
                                    affected=affectedf,
                                    meta={
                                        "kind": "RANK",
                                        "T": sf.T,
                                        "L": sf.L,
                                        "R": 0,
                                        "truths": [t.__dict__ for t in sf.truths],
                                        "links": [l.__dict__ for l in sf.links],
                                        "phase": "fish_fast",
                                    },
                                    proof=proof2f,
                                )
                            )
                            force_fills()
                            progressed_f = True
                            break
                except StopIteration as e:
                    cache = e.value if hasattr(e, "value") else cache
                except Exception:
                    pass
                if progressed_f:
                    continue
                break

            # 1.5) house→cell fastpass：Truth=house-digit, Link=cell，删数发生在单元格内（你要求的补充手段）
            while True:
                rank_state.grid = st.grid[:]
                rank_state.forbidden = st.forbidden[:]
                genhc = search_rank_house_to_cells_fast(
                    rank_state,
                    t_min=2,
                    t_max=3,
                    max_results=max_structures_per_step,
                    existing_cache=cache,
                    truth_types=truth_types,
                    time_budget_ms=None,  # fastpass：完整扫一遍
                    on_heartbeat=on_rank_heartbeat,
                )
                progressed_hc = False
                try:
                    while True:
                        shc = next(genhc)
                        assert isinstance(shc, FoundStructure)
                        delshc, proofhc = compute_deletable_candidates_with_proof(rank_state, shc)
                        delshc = _filter_new_elims(st, delshc)
                        if not delshc:
                            continue
                        okhc, proof2hc = _validate_elims_before_apply(delshc, proofhc, {"kind": "RANK"})
                        if not okhc:
                            invalid_res = _invalidate(
                                "RANK(hc_fast) 删数导致矛盾/无解（裁判否决）",
                                attempted=delshc,
                                meta={
                                    "kind": "RANK",
                                    "T": shc.T,
                                    "L": shc.L,
                                    "R": 0,
                                    "truths": [t.__dict__ for t in shc.truths],
                                    "links": [l.__dict__ for l in shc.links],
                                    "phase": "hc_fast",
                                },
                                proof=proof2hc,
                            )
                            return True
                        affectedhc = []
                        for idx, d in delshc:
                            if st.eliminate(idx, d):
                                affectedhc.append((idx, d))
                        if affectedhc:
                            _push_step(
                                Step(
                                    action_type="eliminate",
                                    rationale=f"RANK:T{shc.T}L{shc.L}R0 {fmt_elims(affectedhc)}",
                                    affected=affectedhc,
                                    meta={
                                        "kind": "RANK",
                                        "T": shc.T,
                                        "L": shc.L,
                                        "R": 0,
                                        "truths": [t.__dict__ for t in shc.truths],
                                        "links": [l.__dict__ for l in shc.links],
                                        "phase": "hc_fast",
                                    },
                                    proof=proof2hc,
                                )
                            )
                            force_fills()
                            progressed_hc = True
                            break
                except StopIteration as e:
                    cache = e.value if hasattr(e, "value") else cache
                except Exception:
                    pass
                if progressed_hc:
                    continue
                break

            # 2) cell-truth fastpass（例②视角）：跨区域的少量 cell Truth（T=2..3）优先尝试，
            #    用很小的 R 上限（≤1）捕捉“短链/重叠覆盖”类结构，避免全量 cell 组合爆炸。
            if "cell" in truth_types:
                while True:
                    rank_state.grid = st.grid[:]
                    rank_state.forbidden = st.forbidden[:]

                    def _hb_cell_fast(info: Dict[str, Any]) -> None:
                        if not on_rank_heartbeat:
                            return
                        try:
                            sub = str(info.get("phase", ""))
                            extra = dict(info)
                            extra["phase"] = "cell_fast"
                            extra["subphase"] = sub
                            on_rank_heartbeat(extra)
                        except Exception:
                            return

                    # 仅用 cell 作为 Truth；Link 仍允许同维/跨维混合（由覆盖前提与 forbid_by_cand 约束）
                    gen_cell = search_rank_structures(
                        rank_state,
                        min_t=2,
                        max_t=min(3, int(max_t)),
                        max_r=min(1, int(r_limit)),
                        max_results=max_structures_per_step,
                        existing_cache=cache,
                        truth_types=["cell"],
                        time_budget_ms=min(350, int(rank_time_budget_ms)),
                        on_heartbeat=_hb_cell_fast,
                        link_types=link_types,
                    )
                    progressed_cell = False
                    try:
                        while True:
                            sc = next(gen_cell)
                            assert isinstance(sc, FoundStructure)
                            dels_c, proof_c = compute_deletable_candidates_with_proof(rank_state, sc)
                            dels_c = _filter_new_elims(st, dels_c)
                            if not dels_c:
                                continue
                            okc, proof2c = _validate_elims_before_apply(dels_c, proof_c, {"kind": "RANK"})
                            if not okc:
                                invalid_res = _invalidate(
                                    "RANK(cell_fast) 删数导致矛盾/无解（裁判否决）",
                                    attempted=dels_c,
                                    meta={
                                        "kind": "RANK",
                                        "T": sc.T,
                                        "L": sc.L,
                                        "R": sc.R,
                                        "truths": [t.__dict__ for t in sc.truths],
                                        "links": [l.__dict__ for l in sc.links],
                                        "phase": "cell_fast",
                                    },
                                    proof=proof2c,
                                )
                                return True
                            affectedc = []
                            for idx, d in dels_c:
                                if st.eliminate(idx, d):
                                    affectedc.append((idx, d))
                            if affectedc:
                                _push_step(
                                    Step(
                                        action_type="eliminate",
                                        rationale=f"RANK:T{sc.T}L{sc.L}R{sc.R} {fmt_elims(affectedc)}",
                                        affected=affectedc,
                                        meta={
                                            "kind": "RANK",
                                            "T": sc.T,
                                            "L": sc.L,
                                            "R": sc.R,
                                            "truths": [t.__dict__ for t in sc.truths],
                                            "links": [l.__dict__ for l in sc.links],
                                            "phase": "cell_fast",
                                        },
                                        proof=proof2c,
                                    )
                                )
                                force_fills()
                                progressed_cell = True
                                break
                    except StopIteration as e:
                        cache = e.value if hasattr(e, "value") else cache
                    except Exception:
                        pass
                    if progressed_cell:
                        continue
                    break

            # 多样化采样 + 迭代加深：
            # - 多轮短预算重启（不同 rng_seed 让 Truth/Link 枚举路径不同）
            # - 逐步放开 max_t（仍受 ≤12 硬上限）与预算（从快到慢）
            import zlib

            try:
                from .learn_params import get_params

                learn_p2 = get_params()
                restarts = max(1, min(12, int(float(learn_p2.get("rank_restarts", 3.0)))))
            except Exception:
                restarts = 3

            skey = ""
            try:
                skey = str(snapshots[-1]) if snapshots else ""
            except Exception:
                skey = ""
            base_seed = int(zlib.crc32(skey.encode("utf-8"))) & 0xFFFFFFFF

            # 分层预算：先低 T/低预算快速扫，再逐步加深
            stages: List[Tuple[int, int, int]] = []
            # (stage_max_t, stage_budget_ms, stage_take_structures)
            stages.append((min(4, int(max_t)), min(220, int(rank_budget_ms)), 60))
            stages.append((min(7, int(max_t)), min(520, max(260, int(rank_budget_ms))), 80))
            stages.append((int(max_t), int(rank_budget_ms), 110))

            def _try_apply_structure(s: FoundStructure, policy_flag: bool) -> bool:
                nonlocal invalid_res
                dels, proof = compute_deletable_candidates_with_proof(rank_state, s)
                dels = _filter_new_elims(st, dels)
                if not dels:
                    return False
                ok, proof2 = _validate_elims_before_apply(dels, proof, {"kind": "RANK"})
                if not ok:
                    invalid_res = _invalidate(
                        "RANK 删数导致矛盾/无解（裁判否决）",
                        attempted=dels,
                        meta={
                            "kind": "RANK",
                            "T": s.T,
                            "L": s.L,
                            "R": s.R,
                            "truths": [t.__dict__ for t in s.truths],
                            "links": [l.__dict__ for l in s.links],
                            **({"policy": True} if policy_flag else {}),
                        },
                        proof=proof2,
                    )
                    return True
                affected = []
                for idx, d in dels:
                    if st.eliminate(idx, d):
                        affected.append((idx, d))
                if not affected:
                    return False
                _push_step(
                    Step(
                        action_type="eliminate",
                        rationale=f"RANK:T{s.T}L{s.L}R{s.R} {fmt_elims(affected)}",
                        affected=affected,
                        meta={
                            "kind": "RANK",
                            "T": s.T,
                            "L": s.L,
                            "R": s.R,
                            "truths": [t.__dict__ for t in s.truths],
                            "links": [l.__dict__ for l in s.links],
                            **({"policy": True} if policy_flag else {}),
                        },
                        proof=proof2,
                    )
                )
                if force_fills():
                    pass
                return True

            for stage_idx, (stage_max_t, stage_budget_ms, take_n) in enumerate(stages):
                if stage_max_t < int(min_t):
                    continue
                for ri in range(int(restarts)):
                    rank_state.grid = st.grid[:]
                    rank_state.forbidden = st.forbidden[:]
                    seed = (base_seed + stage_idx * 10007 + ri * 97) & 0xFFFFFFFF
                    gen = search_rank_structures(
                        rank_state,
                        min_t=int(min_t),
                        max_t=int(stage_max_t),
                        max_r=int(r_limit),
                        max_results=int(max_structures_per_step),
                        existing_cache=cache,
                        truth_types=truth_types,
                        time_budget_ms=int(stage_budget_ms),
                        on_heartbeat=on_rank_heartbeat,
                        link_types=link_types,
                        rng_seed=int(seed),
                    )
                    try:
                        # policy：在本轮采样到的一小批结构中按“删数动作 logits”排序先尝试
                        if use_policy and snapshots:
                            state_key = snapshots[-1]
                            cand: List[FoundStructure] = []
                            for _ in range(int(take_n)):
                                s0 = next(gen)
                                assert isinstance(s0, FoundStructure)
                                if r_limit == 0 and s0.R != 0:
                                    continue
                                cand.append(s0)
                            if cand:
                                scored: List[Tuple[float, FoundStructure]] = []
                                for s1 in cand:
                                    dels1, _p1 = compute_deletable_candidates_with_proof(rank_state, s1)
                                    dels1 = _filter_new_elims(st, dels1)
                                    acts1 = [("eliminate", int(ii), int(dd)) for (ii, dd) in dels1]
                                    ss1 = score_actions(state_key, acts1) if acts1 else []
                                    scored.append((float(sum(ss1)) if ss1 else -1e9, s1))
                                scored.sort(key=lambda x: x[0], reverse=True)
                                for _score, s in scored:
                                    if _try_apply_structure(s, policy_flag=True):
                                        return True
                        # non-policy：按生成顺序直接尝试
                        while True:
                            s = next(gen)
                            assert isinstance(s, FoundStructure)
                            if r_limit == 0 and s.R != 0:
                                continue
                            if _try_apply_structure(s, policy_flag=False):
                                return True
                    except StopIteration as e:
                        cache = e.value if hasattr(e, "value") else cache
                    except Exception:
                        pass
            return False

        # 先试 rank0（L==T），再逐步放开到 R<=3
        if try_rank_with_r_limit(0):
            progressed = True
        else:
            for rlim in range(1, max_r + 1):
                if try_rank_with_r_limit(rlim):
                    progressed = True
                    break

        if invalid_res is not None:
            return invalid_res

        if progressed:
            continue

        # 若本轮先做了 rank（或 prefer_tech_first=False），这里再补一次技巧库重放机会
        if (not prefer_tech_first) and try_techlib_rank():
            if invalid_res is not None:
                return invalid_res
            progressed = True
            if force_fills():
                progressed = True
            continue

        if progressed:
            continue

        # 尝试 UR
        if enable_ur1 and try_ur_type1():
            if invalid_res is not None:
                return invalid_res
            progressed = True
            if force_fills():
                progressed = True
            continue

        # 无任何进展 -> stuck（不允许兜底补全；必须依赖核心推理策略自行探索）
        # 重要：某些分支可能在本轮中通过 force_fills 把盘面填满，但未触发下一轮循环的 solved-check，
        # 若此处直接返回 stuck，会出现“盘面已解完但状态仍 stuck/running”的假卡住。
        if all(v != 0 for v in st.grid):
            return SolveResult(status="solved", steps=steps, snapshots=snapshots)
        return SolveResult(status="stuck", steps=steps, snapshots=snapshots)

    # 理论上不会到这；保险起见做一次 solved-check
    if all(v != 0 for v in st.grid):
        return SolveResult(status="solved", steps=steps, snapshots=snapshots)
    return SolveResult(status="stuck", steps=steps, snapshots=snapshots)

