from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Generator, Iterable, List, Optional, Tuple
import time
import random


Digit = int  # 1..9


@dataclass(frozen=True)
class RegionRef:
    # 对齐前端：cell / rowDigit / colDigit / boxDigit
    type: str
    idx: Optional[int] = None
    row: Optional[int] = None
    col: Optional[int] = None
    box: Optional[int] = None
    d: Optional[Digit] = None


@dataclass
class FoundStructure:
    T: int
    L: int
    R: int
    truths: List[RegionRef]
    links: List[RegionRef]


def rc_of(idx: int) -> Tuple[int, int]:
    return idx // 9, idx % 9


def idx_of(r: int, c: int) -> int:
    return r * 9 + c


def box_of(r: int, c: int) -> int:
    return (r // 3) * 3 + (c // 3)


class SudokuState:
    """
    只实现秩结构搜索所需的最小状态：
    - grid: 81 位数字（0 表示空）
    - forbidden: 81 个 9-bit mask（bit=1 表示候选已永久删除）
    """

    def __init__(self, grid: List[int], given: Optional[List[bool]] = None):
        self.grid = grid[:]  # 81
        self.given = (given[:] if given else [False] * 81)
        self.forbidden = [0] * 81

    def allowed_mask(self, idx: int) -> int:
        if self.grid[idx] != 0:
            return 0
        r, c = rc_of(idx)
        used = 0
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
        allowed &= ~self.forbidden[idx]
        return allowed


def iter_bits(mask: int) -> Iterable[int]:
    # yields bit positions 0..n
    while mask:
        lsb = mask & -mask
        bit = (lsb.bit_length() - 1)
        yield bit
        mask ^= lsb


def pop_first(mask: int) -> Tuple[Optional[int], int]:
    if mask == 0:
        return None, 0
    lsb = mask & -mask
    bit = (lsb.bit_length() - 1)
    return bit, mask ^ lsb


@dataclass
class Candidate:
    r: int
    c: int
    d: Digit
    cell_idx: int
    box: int


@dataclass
class TruthOption:
    ref: RegionRef
    cand_mask: int  # bitmask over candidate-index space
    cand_idxs: List[int]
    forbid: str  # cell | rowDigit | colDigit | boxDigit
    size: int


@dataclass
class SearchCache:
    key: str
    candidates: List[Candidate]
    truth_options: List[TruthOption]
    house_key_row: List[str]
    house_key_col: List[str]
    house_key_box: List[str]


def state_key(st: SudokuState) -> str:
    # 仅用于 cache：数字盘面+forbidden
    digits = "".join(str(v) for v in st.grid)
    forb = "".join(f"{m:03x}" for m in st.forbidden)  # 不必与前端一致，只用于 cache
    return f"{digits}|{forb}"


def build_search_cache(st: SudokuState, existing: Optional[SearchCache] = None) -> SearchCache:
    key = state_key(st)
    if existing and existing.key == key:
        return existing

    candidates: List[Candidate] = []
    for cell_idx in range(81):
        if st.grid[cell_idx] != 0:
            continue
        r, c = rc_of(cell_idx)
        b = box_of(r, c)
        allowed = st.allowed_mask(cell_idx)
        for bit in iter_bits(allowed):
            d = bit + 1
            candidates.append(Candidate(r=r, c=c, d=d, cell_idx=cell_idx, box=b))

    house_key_row = [f"R:{cand.r}:{cand.d}" for cand in candidates]
    house_key_col = [f"C:{cand.c}:{cand.d}" for cand in candidates]
    house_key_box = [f"B:{cand.box}:{cand.d}" for cand in candidates]

    bit_count = len(candidates)

    def mask_for(predicate) -> Tuple[int, List[int], int]:
        m = 0
        idxs: List[int] = []
        for i, cand in enumerate(candidates):
            if predicate(cand):
                m |= 1 << i
                idxs.append(i)
        return m, idxs, len(idxs)

    truth_options: List[TruthOption] = []

    # cell truth options
    for cell_idx in range(81):
        if st.grid[cell_idx] != 0:
            continue
        m, idxs, size = mask_for(lambda cand, ci=cell_idx: cand.cell_idx == ci)
        if size == 0:
            continue
        truth_options.append(
            TruthOption(
                ref=RegionRef(type="cell", idx=cell_idx),
                cand_mask=m,
                cand_idxs=idxs,
                forbid="cell",
                size=size,
            )
        )

    # row/col/box digit truth options
    for row in range(9):
        for d in range(1, 10):
            m, idxs, size = mask_for(lambda cand, rr=row, dd=d: cand.r == rr and cand.d == dd)
            if size:
                truth_options.append(
                    TruthOption(
                        ref=RegionRef(type="rowDigit", row=row, d=d),
                        cand_mask=m,
                        cand_idxs=idxs,
                        forbid="rowDigit",
                        size=size,
                    )
                )
    for col in range(9):
        for d in range(1, 10):
            m, idxs, size = mask_for(lambda cand, cc=col, dd=d: cand.c == cc and cand.d == dd)
            if size:
                truth_options.append(
                    TruthOption(
                        ref=RegionRef(type="colDigit", col=col, d=d),
                        cand_mask=m,
                        cand_idxs=idxs,
                        forbid="colDigit",
                        size=size,
                    )
                )
    for box in range(9):
        for d in range(1, 10):
            m, idxs, size = mask_for(lambda cand, bb=box, dd=d: cand.box == bb and cand.d == dd)
            if size:
                truth_options.append(
                    TruthOption(
                        ref=RegionRef(type="boxDigit", box=box, d=d),
                        cand_mask=m,
                        cand_idxs=idxs,
                        forbid="boxDigit",
                        size=size,
                    )
                )

    truth_options.sort(key=lambda x: x.size)
    return SearchCache(
        key=key,
        candidates=candidates,
        truth_options=truth_options,
        house_key_row=house_key_row,
        house_key_col=house_key_col,
        house_key_box=house_key_box,
    )


def forbid_code(forbid: str) -> int:
    if forbid == "cell":
        return 0
    if forbid == "rowDigit":
        return 1
    if forbid == "colDigit":
        return 2
    return 3


def link_ref_from_key(key: str) -> RegionRef:
    if key.startswith("N:"):
        return RegionRef(type="cell", idx=int(key.split(":")[1]))
    t, a, b = key.split(":")
    d = int(b)
    if t == "R":
        return RegionRef(type="rowDigit", row=int(a), d=d)
    if t == "C":
        return RegionRef(type="colDigit", col=int(a), d=d)
    return RegionRef(type="boxDigit", box=int(a), d=d)


def search_rank_structures(
    st: SudokuState,
    min_t: int,
    max_t: int,
    max_r: int,
    max_results: int = 200,
    existing_cache: Optional[SearchCache] = None,
    truth_types: Optional[List[str]] = None,
    time_budget_ms: Optional[int] = None,
    on_heartbeat: Optional[Any] = None,
    heartbeat_ms: int = 250,
    link_types: Optional[List[str]] = None,
    rng_seed: Optional[int] = None,
) -> Generator[FoundStructure, None, SearchCache]:
    """
    Python 版秩结构搜索（对齐 src/lib/rankSearch.ts）：
    - Truth 组合不重叠（候选位不重叠）
    - Link 覆盖 Truth 候选位集合
    - 允许额外 Link 以制造重叠，从而产生 R>0
    - 不对 R 做理论限制，但必须给定 max_r 作为搜索上界（否则组合空间无限大）
    """
    cache = build_search_cache(st, existing_cache)
    candidates = cache.candidates
    truth_options = cache.truth_options
    if truth_types:
        allow = set(truth_types)
        truth_options = [x for x in truth_options if x.ref.type in allow]
    # 多样化采样：在不限制 Truth/Link 类型的前提下，仅对枚举顺序做可控随机抖动
    rng: Optional[random.Random] = None
    if rng_seed is not None:
        rng = random.Random(int(rng_seed) & 0xFFFFFFFF)
        try:
            from .learn_params import get_params

            truth_size_jitter = float(get_params().get("truth_size_jitter", 0.15))
        except Exception:
            truth_size_jitter = 0.15
        # 保持“更小 size 更优先”的主趋势，同时允许相近 size 的选项被打散（覆盖更多组合空间）
        if truth_size_jitter > 0:
            truth_options = sorted(
                truth_options,
                key=lambda o: (float(o.size) + truth_size_jitter * float(rng.random()), float(rng.random())),
            )
    bit_count = len(candidates)

    used_truth = [False] * len(truth_options)
    forbid_by_cand = [-1] * bit_count  # 0=cell 1=row 2=col 3=box
    truth_size_by_cand = [0] * bit_count  # Truth 规模（用于 Link/Truth 规模相近偏置）
    chosen_truths: List[RegionRef] = []
    used_cand_mask = 0
    sum_truth_sizes = 0

    found = 0
    truth_iters = 0
    link_nodes = 0
    t0 = time.perf_counter()
    last_hb = t0
    stop = False

    def _elapsed_ms() -> int:
        return int((time.perf_counter() - t0) * 1000)

    def _maybe_stop() -> bool:
        nonlocal stop
        if time_budget_ms is not None and _elapsed_ms() >= int(time_budget_ms):
            stop = True
        return stop

    def _hb(phase: str, extra: Dict[str, Any]) -> None:
        nonlocal last_hb
        if not on_heartbeat:
            return
        now = time.perf_counter()
        if (now - last_hb) * 1000 < heartbeat_ms:
            return
        last_hb = now
        try:
            on_heartbeat(
                {
                    "phase": phase,
                    "elapsed_ms": _elapsed_ms(),
                    "found": int(found),
                    "truth_iters": int(truth_iters),
                    "link_nodes": int(link_nodes),
                    "min_t": int(min_t),
                    "max_t": int(max_t),
                    "max_r": int(max_r),
                    "max_results": int(max_results),
                    **extra,
                }
            )
        except Exception:
            return

    def enumerate_truths(start_idx: int, target_t: int) -> Generator[List[RegionRef], None, None]:
        nonlocal used_cand_mask
        nonlocal sum_truth_sizes
        if len(chosen_truths) == target_t:
            yield list(chosen_truths)
            return
        remaining = target_t - len(chosen_truths)
        for i in range(start_idx, len(truth_options)):
            nonlocal truth_iters
            truth_iters += 1
            if _maybe_stop():
                return
            _hb("truth", {"target_t": int(target_t), "start_idx": int(start_idx), "i": int(i)})
            if len(truth_options) - i < remaining:
                return
            if used_truth[i]:
                continue
            opt = truth_options[i]
            if used_cand_mask & opt.cand_mask:
                continue  # Truth 不重叠

            used_truth[i] = True
            chosen_truths.append(opt.ref)
            used_before = used_cand_mask
            used_cand_mask |= opt.cand_mask
            touched = opt.cand_idxs[:]
            code = forbid_code(opt.forbid)
            for ci in touched:
                forbid_by_cand[ci] = code
                truth_size_by_cand[ci] = int(opt.size)
            sum_truth_sizes += int(opt.size)

            yield from enumerate_truths(i + 1, target_t)

            chosen_truths.pop()
            used_truth[i] = False
            used_cand_mask = used_before
            sum_truth_sizes -= int(opt.size)
            for ci in touched:
                forbid_by_cand[ci] = -1
                truth_size_by_cand[ci] = 0

    def build_cover_maps(bits_mask: int) -> Tuple[Dict[str, int], Dict[int, List[str]], List[str]]:
        key_to_cover: Dict[str, int] = {}
        cand_to_opts: Dict[int, List[str]] = {}

        allow_link = set(link_types) if link_types else None
        def _allow_key(k: str) -> bool:
            if not allow_link:
                return True
            if k.startswith("N:"):
                return "cell" in allow_link
            if k.startswith("R:"):
                return "rowDigit" in allow_link
            if k.startswith("C:"):
                return "colDigit" in allow_link
            return "boxDigit" in allow_link

        for i in range(bit_count):
            if not (bits_mask & (1 << i)):
                continue
            forbid = forbid_by_cand[i]
            cell_key = f"N:{candidates[i].cell_idx}"
            row_key = cache.house_key_row[i]
            col_key = cache.house_key_col[i]
            box_key = cache.house_key_box[i]
            opts: List[str] = []
            if forbid != 0 and _allow_key(cell_key):
                opts.append(cell_key)
            if forbid != 1 and _allow_key(row_key):
                opts.append(row_key)
            if forbid != 2 and _allow_key(col_key):
                opts.append(col_key)
            if forbid != 3 and _allow_key(box_key):
                opts.append(box_key)
            cand_to_opts[i] = opts
            for k in opts:
                key_to_cover[k] = key_to_cover.get(k, 0) | (1 << i)

        all_keys = sorted(key_to_cover.keys())
        return key_to_cover, cand_to_opts, all_keys

    def enumerate_link_covers(bits_mask: int, max_links: int) -> Generator[List[str], None, None]:
        if bits_mask == 0:
            yield []
            return
        key_to_cover, cand_to_opts, all_keys = build_cover_maps(bits_mask)
        target = bits_mask
        selected: List[str] = []
        covered = 0
        dedupe: set[str] = set()

        def dfs(uncovered: int, start_extra_key_idx: int) -> Generator[List[str], None, None]:
            nonlocal covered
            nonlocal link_nodes
            link_nodes += 1
            if _maybe_stop():
                return
            _hb("link", {"uncovered_bits": int(uncovered.bit_count()), "selected": int(len(selected)), "max_links": int(max_links)})
            if len(selected) > max_links:
                return
            if uncovered == 0:
                sig = "|".join(sorted(selected))
                if sig not in dedupe:
                    dedupe.add(sig)
                    yield sorted(selected)
                if len(selected) == max_links:
                    return
                # add extra links
                # 额外 Link 的选择同样按“覆盖强区域并尽量重叠”排序（比纯顺序更容易出删数）
                remain = [all_keys[ki] for ki in range(start_extra_key_idx, len(all_keys)) if all_keys[ki] not in selected]
                try:
                    from .learn_params import get_params
                    overlap_bias = float(get_params().get("overlap_bias", 1.0))
                    size_match_bias = float(get_params().get("size_match_bias", 0.25))
                except Exception:
                    overlap_bias = 1.0
                    size_match_bias = 0.25
                def score2(k: str) -> float:
                    # uncovered==0 时，用与 target（Truth候选集合）的重叠作为主要指标
                    c1 = float((key_to_cover.get(k, 0) & target).bit_count())
                    c2 = float(key_to_cover.get(k, 0).bit_count())
                    desired = float(sum_truth_sizes) / float(max(1, len(chosen_truths)))
                    if desired > 0 and size_match_bias > 0:
                        return overlap_bias * c1 + 0.1 * c2 - size_match_bias * abs(c2 - desired)
                    return overlap_bias * c1 + 0.1 * c2
                if rng:
                    remain.sort(key=lambda k: (-score2(k), float(rng.random())))
                else:
                    remain.sort(key=lambda k: (-score2(k), k))

                for ki, k in enumerate(remain):
                    if _maybe_stop():
                        return
                    if k in selected:
                        continue
                    selected.append(k)
                    before = covered
                    covered |= key_to_cover[k]
                    next_uncovered = target & ~covered
                    yield from dfs(next_uncovered, ki + 1)
                    selected.pop()
                    covered = before
                return

            pick_bit, rest = pop_first(uncovered)
            if pick_bit is None:
                return
            # 倾向“弱区域重叠/覆盖更多”：优先选择能覆盖更多 uncovered 位的区域键，
            # 这样更容易形成同一候选被多次覆盖（从而产生删数）。
            opts = list(cand_to_opts.get(pick_bit, []))
            try:
                from .learn_params import get_params

                overlap_bias = float(get_params().get("overlap_bias", 1.0))
                size_match_bias = float(get_params().get("size_match_bias", 0.25))
            except Exception:
                overlap_bias = 1.0
                size_match_bias = 0.25

            def score(k: str) -> float:
                # 更偏向覆盖更多 uncovered，并可用 overlap_bias 放大这种倾向
                c1 = float((key_to_cover.get(k, 0) & uncovered).bit_count())
                c2 = float(key_to_cover.get(k, 0).bit_count())
                # 规模相近偏置：Truth 与 Link 的候选数相近更容易相关、更易形成结构（不做硬限制）
                desired = float(truth_size_by_cand[pick_bit] or 0)
                if desired > 0 and size_match_bias > 0:
                    return overlap_bias * c1 + 0.1 * c2 - size_match_bias * abs(c2 - desired)
                return overlap_bias * c1 + 0.1 * c2

            if rng:
                opts.sort(key=lambda k: (-score(k), float(rng.random())))
            else:
                opts.sort(key=lambda k: (-score(k), k))
            for k in opts:
                if _maybe_stop():
                    return
                if not (key_to_cover[k] & (1 << pick_bit)):
                    continue
                selected.append(k)
                before = covered
                covered |= key_to_cover[k]
                next_uncovered = target & ~covered
                yield from dfs(next_uncovered, 0)
                selected.pop()
                covered = before

        yield from dfs(bits_mask, 0)

    for target_t in range(max(1, int(min_t)), max(1, int(max_t)) + 1):
        if _maybe_stop():
            _hb("timeout", {"target_t": int(target_t)})
            return cache
        for truth_refs in enumerate_truths(0, target_t):
            if stop:
                _hb("timeout", {"target_t": int(target_t)})
                return cache
            max_links = target_t + max(0, int(max_r))
            for keys in enumerate_link_covers(used_cand_mask, max_links=max_links):
                if stop:
                    _hb("timeout", {"target_t": int(target_t)})
                    return cache
                T = len(truth_refs)
                L = len(keys)
                R = L - T
                if R < 0:
                    continue
                if R > max_r:
                    continue
                found += 1
                links = [link_ref_from_key(k) for k in keys]
                yield FoundStructure(T=T, L=L, R=R, truths=truth_refs, links=links)
                if found >= max_results:
                    return cache

    return cache


def search_rank_t1_house_fast(
    st: SudokuState,
    *,
    max_results: int = 200,
    existing_cache: Optional[SearchCache] = None,
    truth_types: Optional[List[str]] = None,
    link_types: Optional[List[str]] = None,
    time_budget_ms: Optional[int] = None,
    on_heartbeat: Optional[Any] = None,
    heartbeat_ms: int = 250,
) -> Generator[FoundStructure, None, SearchCache]:
    """
    你要求的“最快/最常见”一类：T=1（仅 house-digit Truth：行/列/宫），优先尝试 L=1 的覆盖删数。
    这对应大量经典“区块删数/指向/认领”类结构（不需要技巧名）。
    """
    cache = build_search_cache(st, existing_cache)
    candidates = cache.candidates
    bit_count = len(candidates)

    allow_truth = set(truth_types) if truth_types else {"rowDigit", "colDigit", "boxDigit"}
    allow_truth.discard("cell")
    allow_link = set(link_types) if link_types else {"rowDigit", "colDigit", "boxDigit"}
    allow_link.discard("cell")

    # build index for truth option by (type, house, digit)
    truth_idx: Dict[str, TruthOption] = {}
    for opt in cache.truth_options:
        if opt.ref.type not in ("rowDigit", "colDigit", "boxDigit"):
            continue
        if opt.ref.type not in allow_truth:
            continue
        d = int(opt.ref.d or 0)
        if d < 1 or d > 9:
            continue
        if opt.ref.type == "rowDigit":
            h = int(opt.ref.row or 0)
        elif opt.ref.type == "colDigit":
            h = int(opt.ref.col or 0)
        else:
            h = int(opt.ref.box or 0)
        truth_idx[f"{opt.ref.type}:{h}:{d}"] = opt

    t0 = time.perf_counter()
    last_hb = t0
    found = 0

    def elapsed_ms() -> int:
        return int((time.perf_counter() - t0) * 1000)

    def maybe_stop() -> bool:
        return (time_budget_ms is not None) and (elapsed_ms() >= int(time_budget_ms))

    def hb(phase: str, extra: Dict[str, Any]) -> None:
        nonlocal last_hb
        if not on_heartbeat:
            return
        now = time.perf_counter()
        if (now - last_hb) * 1000 < heartbeat_ms:
            return
        last_hb = now
        try:
            on_heartbeat({"phase": phase, "elapsed_ms": elapsed_ms(), "found": int(found), **extra})
        except Exception:
            return

    def mask_for_link(kind: str, h: int, d: int) -> int:
        m = 0
        for i, cand in enumerate(candidates):
            if cand.d != d:
                continue
            if kind == "rowDigit" and cand.r == h:
                m |= 1 << i
            elif kind == "colDigit" and cand.c == h:
                m |= 1 << i
            elif kind == "boxDigit" and cand.box == h:
                m |= 1 << i
        return m

    # 固定顺序：按 digit 扫描，再按行/列/宫扫描（你的 324 维度思想）
    truth_order = [t for t in ("rowDigit", "colDigit", "boxDigit") if t in allow_truth]
    link_order = [t for t in ("rowDigit", "colDigit", "boxDigit") if t in allow_link]

    for d in range(1, 10):
        if maybe_stop():
            return cache
        for tt in truth_order:
            for h in range(9):
                if maybe_stop():
                    return cache
                opt = truth_idx.get(f"{tt}:{h}:{d}")
                if not opt:
                    continue
                # size==1 的情况应由基础逻辑/隐藏单元直接处理；这里跳过以减少噪音
                if opt.size <= 1:
                    continue
                hb("t1_fast", {"d": d, "truth_type": tt, "house": h, "truth_size": int(opt.size)})

                # 收集 truth 候选的行/列/宫跨度，用于快速判定“是否可被某 link 单域覆盖”
                rows = set()
                cols = set()
                boxes = set()
                for ci in opt.cand_idxs:
                    cand = candidates[ci]
                    rows.add(cand.r)
                    cols.add(cand.c)
                    boxes.add(cand.box)

                # 枚举 L=1（R=0）的覆盖 link：
                # 允许与 truth 同维/跨维混用；是否成立由“link 覆盖 truth”与“差集非空”自然筛掉。
                for lt in link_order:
                    if lt == "rowDigit" and len(rows) == 1:
                        lh = next(iter(rows))
                    elif lt == "colDigit" and len(cols) == 1:
                        lh = next(iter(cols))
                    elif lt == "boxDigit" and len(boxes) == 1:
                        lh = next(iter(boxes))
                    else:
                        continue
                    # link 覆盖集合必须包含 truth 候选集合（对 T=1 这等价于 opt.cand_mask ⊆ link_mask）
                    link_mask = mask_for_link(lt, int(lh), int(d))
                    if (link_mask & opt.cand_mask) != opt.cand_mask:
                        continue
                    # 若 link 没有额外候选，则不会产生删数
                    if (link_mask & ~opt.cand_mask) == 0:
                        continue

                    # FoundStructure：T=1, L=1, R=0
                    if lt == "rowDigit":
                        link_ref = RegionRef(type="rowDigit", row=int(lh), d=int(d))
                    elif lt == "colDigit":
                        link_ref = RegionRef(type="colDigit", col=int(lh), d=int(d))
                    else:
                        link_ref = RegionRef(type="boxDigit", box=int(lh), d=int(d))

                    found += 1
                    yield FoundStructure(T=1, L=1, R=0, truths=[opt.ref], links=[link_ref])
                    if found >= max_results:
                        return cache

    return cache


def search_rank_fish_r0_fast(
    st: SudokuState,
    *,
    n_min: int = 2,
    n_max: int = 4,
    max_results: int = 200,
    existing_cache: Optional[SearchCache] = None,
    truth_types: Optional[List[str]] = None,
    link_types: Optional[List[str]] = None,
    time_budget_ms: Optional[int] = None,
    on_heartbeat: Optional[Any] = None,
    heartbeat_ms: int = 250,
) -> Generator[FoundStructure, None, SearchCache]:
    """
    例①视角的底层结构（rank0 fish）：
    - 固定 digit d
    - 选择 n 个 Truth（同一维度的 house-digit：rowDigit/colDigit/boxDigit）
    - 若这 n 个 Truth 的候选位置只落在 n 个 Link house（另一维度的 house-digit）上，
      则构成 T=n, L=n, R=0 的秩结构，可删除 Link 上除 Truth 外的候选（差集）。
    覆盖：2行对2列、3行对3列、2列对2宫、3宫对3行等（不需要技巧名）。
    """
    cache = build_search_cache(st, existing_cache)
    candidates = cache.candidates

    allow_truth = set(truth_types) if truth_types else {"rowDigit", "colDigit", "boxDigit"}
    allow_truth.discard("cell")
    allow_link = set(link_types) if link_types else {"rowDigit", "colDigit", "boxDigit"}
    allow_link.discard("cell")

    # build index for truth option by (type, house, digit)
    truth_idx: Dict[str, TruthOption] = {}
    for opt in cache.truth_options:
        if opt.ref.type not in ("rowDigit", "colDigit", "boxDigit"):
            continue
        if opt.ref.type not in allow_truth:
            continue
        d = int(opt.ref.d or 0)
        if d < 1 or d > 9:
            continue
        if opt.ref.type == "rowDigit":
            h = int(opt.ref.row or 0)
        elif opt.ref.type == "colDigit":
            h = int(opt.ref.col or 0)
        else:
            h = int(opt.ref.box or 0)
        truth_idx[f"{opt.ref.type}:{h}:{d}"] = opt

    t0 = time.perf_counter()
    last_hb = t0
    found = 0

    def elapsed_ms() -> int:
        return int((time.perf_counter() - t0) * 1000)

    def maybe_stop() -> bool:
        return (time_budget_ms is not None) and (elapsed_ms() >= int(time_budget_ms))

    def hb(phase: str, extra: Dict[str, Any]) -> None:
        nonlocal last_hb
        if not on_heartbeat:
            return
        now = time.perf_counter()
        if (now - last_hb) * 1000 < heartbeat_ms:
            return
        last_hb = now
        try:
            on_heartbeat({"phase": phase, "elapsed_ms": elapsed_ms(), "found": int(found), **extra})
        except Exception:
            return

    def mask_for_link(kind: str, h: int, d: int) -> int:
        m = 0
        for i, cand in enumerate(candidates):
            if cand.d != d:
                continue
            if kind == "rowDigit" and cand.r == h:
                m |= 1 << i
            elif kind == "colDigit" and cand.c == h:
                m |= 1 << i
            elif kind == "boxDigit" and cand.box == h:
                m |= 1 << i
        return m

    def span_houses(lt: str, cand_idxs: List[int]) -> List[int]:
        s: set[int] = set()
        for ci in cand_idxs:
            c = candidates[int(ci)]
            if lt == "rowDigit":
                s.add(int(c.r))
            elif lt == "colDigit":
                s.add(int(c.c))
            else:
                s.add(int(c.box))
        return sorted(list(s))

    truth_order = [t for t in ("rowDigit", "colDigit", "boxDigit") if t in allow_truth]
    link_order = [t for t in ("rowDigit", "colDigit", "boxDigit") if t in allow_link]

    n_min = max(2, int(n_min))
    n_max = max(n_min, int(n_max))
    n_max = min(4, n_max)

    for d in range(1, 10):
        if maybe_stop():
            return cache
        for tt in truth_order:
            # 候选：按 house 枚举 truth option
            houses = []
            for h in range(9):
                opt = truth_idx.get(f"{tt}:{h}:{d}")
                if not opt:
                    continue
                # fish 常见：每个 truth house 候选规模在 [2..n]，过大的 house 候选会造成无谓组合
                if opt.size < 2:
                    continue
                houses.append((h, opt))
            if len(houses) < n_min:
                continue
            for lt in link_order:
                # 组合枚举：n=2..4（稳定且体量小优先）
                for n in range(n_min, n_max + 1):
                    if maybe_stop():
                        return cache
                    if len(houses) < n:
                        break
                    hb("fish_fast", {"d": int(d), "truth_type": tt, "link_type": lt, "n": int(n)})

                    # simple comb loops for n<=4
                    hs = houses
                    L = len(hs)
                    if n == 2:
                        for i in range(L - 1):
                            for j in range(i + 1, L):
                                if maybe_stop():
                                    return cache
                                ops = [hs[i][1], hs[j][1]]
                                # Truth 不允许重叠覆盖同一候选 (r,c,d)
                                if ops[0].cand_mask & ops[1].cand_mask:
                                    continue
                                if ops[0].size > 2 or ops[1].size > 2:
                                    # 对 n=2 更严格，贴近 X-Wing（减少噪音）
                                    continue
                                cand_idxs = ops[0].cand_idxs + ops[1].cand_idxs
                                # span link houses
                                sp = span_houses(lt, cand_idxs)
                                if len(sp) != 2:
                                    continue
                                truth_mask = ops[0].cand_mask | ops[1].cand_mask
                                link_mask = 0
                                for hh in sp:
                                    link_mask |= mask_for_link(lt, int(hh), int(d))
                                # Links 必须覆盖 Truth（子集前提）
                                if (link_mask & truth_mask) != truth_mask:
                                    continue
                                # 必须有差集才能删数
                                if (link_mask & ~truth_mask) == 0:
                                    continue
                                found += 1
                                truths = [ops[0].ref, ops[1].ref]
                                links = []
                                for hh in sp:
                                    if lt == "rowDigit":
                                        links.append(RegionRef(type="rowDigit", row=int(hh), d=int(d)))
                                    elif lt == "colDigit":
                                        links.append(RegionRef(type="colDigit", col=int(hh), d=int(d)))
                                    else:
                                        links.append(RegionRef(type="boxDigit", box=int(hh), d=int(d)))
                                yield FoundStructure(T=2, L=2, R=0, truths=truths, links=links)
                                if found >= max_results:
                                    return cache
                    elif n == 3:
                        for i in range(L - 2):
                            for j in range(i + 1, L - 1):
                                for k in range(j + 1, L):
                                    if maybe_stop():
                                        return cache
                                    ops = [hs[i][1], hs[j][1], hs[k][1]]
                                    # Truth 不允许重叠覆盖同一候选 (r,c,d)
                                    truth_mask = ops[0].cand_mask | ops[1].cand_mask | ops[2].cand_mask
                                    if int(truth_mask.bit_count()) != int(ops[0].cand_mask.bit_count() + ops[1].cand_mask.bit_count() + ops[2].cand_mask.bit_count()):
                                        continue
                                    if any(op.size > 3 for op in ops):
                                        continue
                                    cand_idxs = ops[0].cand_idxs + ops[1].cand_idxs + ops[2].cand_idxs
                                    sp = span_houses(lt, cand_idxs)
                                    if len(sp) != 3:
                                        continue
                                    truth_mask = ops[0].cand_mask | ops[1].cand_mask | ops[2].cand_mask
                                    link_mask = 0
                                    for hh in sp:
                                        link_mask |= mask_for_link(lt, int(hh), int(d))
                                    if (link_mask & truth_mask) != truth_mask:
                                        continue
                                    if (link_mask & ~truth_mask) == 0:
                                        continue
                                    found += 1
                                    truths = [op.ref for op in ops]
                                    links = []
                                    for hh in sp:
                                        if lt == "rowDigit":
                                            links.append(RegionRef(type="rowDigit", row=int(hh), d=int(d)))
                                        elif lt == "colDigit":
                                            links.append(RegionRef(type="colDigit", col=int(hh), d=int(d)))
                                        else:
                                            links.append(RegionRef(type="boxDigit", box=int(hh), d=int(d)))
                                    yield FoundStructure(T=3, L=3, R=0, truths=truths, links=links)
                                    if found >= max_results:
                                        return cache
                    else:  # n == 4
                        for i in range(L - 3):
                            for j in range(i + 1, L - 2):
                                for k in range(j + 1, L - 1):
                                    for q in range(k + 1, L):
                                        if maybe_stop():
                                            return cache
                                        ops = [hs[i][1], hs[j][1], hs[k][1], hs[q][1]]
                                        truth_mask = ops[0].cand_mask | ops[1].cand_mask | ops[2].cand_mask | ops[3].cand_mask
                                        if int(truth_mask.bit_count()) != int(ops[0].cand_mask.bit_count() + ops[1].cand_mask.bit_count() + ops[2].cand_mask.bit_count() + ops[3].cand_mask.bit_count()):
                                            continue
                                        if any(op.size > 4 for op in ops):
                                            continue
                                        cand_idxs = ops[0].cand_idxs + ops[1].cand_idxs + ops[2].cand_idxs + ops[3].cand_idxs
                                        sp = span_houses(lt, cand_idxs)
                                        if len(sp) != 4:
                                            continue
                                        truth_mask = ops[0].cand_mask | ops[1].cand_mask | ops[2].cand_mask | ops[3].cand_mask
                                        link_mask = 0
                                        for hh in sp:
                                            link_mask |= mask_for_link(lt, int(hh), int(d))
                                        if (link_mask & truth_mask) != truth_mask:
                                            continue
                                        if (link_mask & ~truth_mask) == 0:
                                            continue
                                        found += 1
                                        truths = [op.ref for op in ops]
                                        links = []
                                        for hh in sp:
                                            if lt == "rowDigit":
                                                links.append(RegionRef(type="rowDigit", row=int(hh), d=int(d)))
                                            elif lt == "colDigit":
                                                links.append(RegionRef(type="colDigit", col=int(hh), d=int(d)))
                                            else:
                                                links.append(RegionRef(type="boxDigit", box=int(hh), d=int(d)))
                                        yield FoundStructure(T=4, L=4, R=0, truths=truths, links=links)
                                        if found >= max_results:
                                            return cache

    return cache


def search_rank_house_to_cells_fast(
    st: SudokuState,
    *,
    t_min: int = 2,
    t_max: int = 3,
    max_results: int = 200,
    existing_cache: Optional[SearchCache] = None,
    truth_types: Optional[List[str]] = None,
    time_budget_ms: Optional[int] = None,
    on_heartbeat: Optional[Any] = None,
    heartbeat_ms: int = 250,
) -> Generator[FoundStructure, None, SearchCache]:
    """
    补充手段（你提出的视角）：
    - Truth：行/列/宫×digit（house-digit），可同维或跨维组合
    - Link ：单元格（cell）
    - 条件：Truth 候选全集仅落在 T 个单元格内（即 union(cells)==T，且 T==L => R=0）
    - 结果：可删除这些单元格内除 Truth digit 外的其它候选（删数发生在单元格里）

    这是一个“非常窄的 fastpass”：只扫 T=2..3，避免组合爆炸。
    """
    cache = build_search_cache(st, existing_cache)
    candidates = cache.candidates

    allow_truth = set(truth_types) if truth_types else {"rowDigit", "colDigit", "boxDigit"}
    allow_truth.discard("cell")

    # build index for truth option by (type, house, digit)
    truth_idx: Dict[str, TruthOption] = {}
    for opt in cache.truth_options:
        if opt.ref.type not in ("rowDigit", "colDigit", "boxDigit"):
            continue
        if opt.ref.type not in allow_truth:
            continue
        d = int(opt.ref.d or 0)
        if d < 1 or d > 9:
            continue
        if opt.ref.type == "rowDigit":
            h = int(opt.ref.row or 0)
        elif opt.ref.type == "colDigit":
            h = int(opt.ref.col or 0)
        else:
            h = int(opt.ref.box or 0)
        truth_idx[f"{opt.ref.type}:{h}:{d}"] = opt

    t0 = time.perf_counter()
    last_hb = t0
    found = 0

    def elapsed_ms() -> int:
        return int((time.perf_counter() - t0) * 1000)

    def maybe_stop() -> bool:
        return (time_budget_ms is not None) and (elapsed_ms() >= int(time_budget_ms))

    def hb(extra: Dict[str, Any]) -> None:
        nonlocal last_hb
        if not on_heartbeat:
            return
        now = time.perf_counter()
        if (now - last_hb) * 1000 < heartbeat_ms:
            return
        last_hb = now
        try:
            on_heartbeat({"phase": "hc_fast", "elapsed_ms": elapsed_ms(), "found": int(found), **extra})
        except Exception:
            return

    t_min = max(2, int(t_min))
    t_max = max(t_min, int(t_max))
    t_max = min(3, t_max)

    for d in range(1, 10):
        if maybe_stop():
            return cache
        # collect eligible truth opts for this digit
        opts: List[TruthOption] = []
        for tt in ("rowDigit", "colDigit", "boxDigit"):
            if tt not in allow_truth:
                continue
            for h in range(9):
                opt = truth_idx.get(f"{tt}:{h}:{d}")
                if not opt:
                    continue
                opts.append(opt)
        if len(opts) < t_min:
            continue

        # stable order：小 size 优先（更像“短链”）
        opts.sort(key=lambda x: (int(x.size), str(x.ref.type), int(x.ref.row or x.ref.col or x.ref.box or 0)))

        L = len(opts)
        for T in range(t_min, t_max + 1):
            if maybe_stop():
                return cache
            hb({"d": int(d), "T": int(T), "opts": int(L)})
            if L < T:
                break
            if T == 2:
                for i in range(L - 1):
                    for j in range(i + 1, L):
                        if maybe_stop():
                            return cache
                        a = opts[i]
                        b = opts[j]
                        # Truth 不允许重叠覆盖同一候选 (r,c,d)
                        if a.cand_mask & b.cand_mask:
                            continue
                        # 剪枝：单个 Truth size > T 不可能把 union 压到 T
                        if a.size > 2 or b.size > 2:
                            continue
                        cell_set: set[int] = set()
                        for ci in a.cand_idxs:
                            cell_set.add(int(candidates[int(ci)].cell_idx))
                        for ci in b.cand_idxs:
                            cell_set.add(int(candidates[int(ci)].cell_idx))
                        if len(cell_set) != 2:
                            continue
                        found += 1
                        truths = [a.ref, b.ref]
                        links = [RegionRef(type="cell", idx=int(x)) for x in sorted(cell_set)]
                        yield FoundStructure(T=2, L=2, R=0, truths=truths, links=links)
                        if found >= max_results:
                            return cache
            else:  # T == 3
                for i in range(L - 2):
                    for j in range(i + 1, L - 1):
                        for k in range(j + 1, L):
                            if maybe_stop():
                                return cache
                            a = opts[i]
                            b = opts[j]
                            c = opts[k]
                            truth_mask = a.cand_mask | b.cand_mask | c.cand_mask
                            if int(truth_mask.bit_count()) != int(a.cand_mask.bit_count() + b.cand_mask.bit_count() + c.cand_mask.bit_count()):
                                continue
                            if a.size > 3 or b.size > 3 or c.size > 3:
                                continue
                            cell_set: set[int] = set()
                            for ci in a.cand_idxs:
                                cell_set.add(int(candidates[int(ci)].cell_idx))
                            for ci in b.cand_idxs:
                                cell_set.add(int(candidates[int(ci)].cell_idx))
                            for ci in c.cand_idxs:
                                cell_set.add(int(candidates[int(ci)].cell_idx))
                            if len(cell_set) != 3:
                                continue
                            found += 1
                            truths = [a.ref, b.ref, c.ref]
                            links = [RegionRef(type="cell", idx=int(x)) for x in sorted(cell_set)]
                            yield FoundStructure(T=3, L=3, R=0, truths=truths, links=links)
                            if found >= max_results:
                                return cache

    return cache


def resolve_group(st: SudokuState, ref: RegionRef) -> List[Tuple[int, int, Digit]]:
    # returns list of (r,c,d) 0-based
    out: List[Tuple[int, int, Digit]] = []
    if ref.type == "cell":
        idx = int(ref.idx or 0)
        if st.grid[idx] != 0:
            return out
        r, c = rc_of(idx)
        m = st.allowed_mask(idx)
        for bit in iter_bits(m):
            out.append((r, c, bit + 1))
        return out
    if ref.type == "rowDigit":
        row = int(ref.row or 0)
        d = int(ref.d or 0)
        for c in range(9):
            idx = idx_of(row, c)
            if st.grid[idx] != 0:
                continue
            if st.allowed_mask(idx) & (1 << (d - 1)):
                out.append((row, c, d))
        return out
    if ref.type == "colDigit":
        col = int(ref.col or 0)
        d = int(ref.d or 0)
        for r in range(9):
            idx = idx_of(r, col)
            if st.grid[idx] != 0:
                continue
            if st.allowed_mask(idx) & (1 << (d - 1)):
                out.append((r, col, d))
        return out
    # boxDigit
    box = int(ref.box or 0)
    d = int(ref.d or 0)
    br = (box // 3) * 3
    bc = (box % 3) * 3
    for r in range(br, br + 3):
        for c in range(bc, bc + 3):
            idx = idx_of(r, c)
            if st.grid[idx] != 0:
                continue
            if st.allowed_mask(idx) & (1 << (d - 1)):
                out.append((r, c, d))
    return out


def compute_deletable_candidates(st: SudokuState, s: FoundStructure) -> List[Tuple[int, Digit]]:
    """
    对齐 src/lib/rankDeductions.ts 的删数公理：
    - Truth 覆盖到的候选永远不删
    - 对每个候选统计 Link 覆盖次数 cnt
    - 未被 Truth 覆盖且 cnt >= R+1 => 可删
    """
    truth = set()
    # 关键（你强调的公理）：强区域 Truth 之间不能重复覆盖同一个候选 (r,c,d)
    # 即：同一候选不允许被多个 Truth 同时包含，否则会导致“把同一候选算了两次”的错误结构。
    truth_overlap_invalid = False
    for t in s.truths:
        for (r, c, d) in resolve_group(st, t):
            k = (r, c, d)
            if k in truth:
                truth_overlap_invalid = True
                break
            truth.add(k)
        if truth_overlap_invalid:
            break

    # 关键：Truth 不能为空。
    # techlib 重放/错误输入时可能出现 Truth 引用落在“已填格（含提示数）”上，此时 resolve_group 返回空，
    # 若继续允许删数，会退化为“仅靠 Links 也能删数”的荒谬结论。
    if s.T > 0 and len(truth) == 0:
        return []

    if truth_overlap_invalid:
        return []

    # 关键（你指出的必要条件）：
    # 强区域数量 T 必须 >= Truth 候选中涉及的“数字种类数”（否则无法保证“每种数字都有一个强区域承载”，删数不成立）。
    # 典型反例：单个 cell Truth 含 {5,8} 两种候选，仅 T=1 不允许导出删数。
    if s.T > 0:
        digit_kinds = len({int(x[2]) for x in truth})
        if digit_kinds > int(s.T):
            return []

    link_count: Dict[Tuple[int, int, Digit], int] = {}
    for l in s.links:
        for (r, c, d) in resolve_group(st, l):
            k = (r, c, d)
            link_count[k] = link_count.get(k, 0) + 1

    # 关键前提（你强调的）：弱区域必须覆盖强区域包含的“所有候选集合”
    # 即 Truth 候选集合必须是 Links 覆盖集合的子集，否则该结构不成立，不允许删数。
    if truth:
        covered = set(link_count.keys())
        if not truth.issubset(covered):
            return []

    out: List[Tuple[int, Digit]] = []
    need = s.R + 1
    if need <= 0:
        return out
    for (r, c, d), cnt in link_count.items():
        if (r, c, d) in truth:
            continue
        if cnt < need:
            continue
        out.append((idx_of(r, c), d))

    out.sort(key=lambda x: (x[0], x[1]))
    return out


def compute_deletable_candidates_with_proof(st: SudokuState, s: FoundStructure) -> Tuple[List[Tuple[int, Digit]], Dict[str, Any]]:
    """
    同 compute_deletable_candidates，但返回可审计 proof，并且把关键前提写入 proof：
    - Links 覆盖 Truth 候选全集（truth ⊆ covered）
    - 删除规则：未被 Truth 覆盖且 link覆盖次数 cnt >= R+1
    """
    truth = set()
    truth_overlap_invalid = False
    uncovered_truth_sample: List[Tuple[int, int, Digit]] = []
    for t in s.truths:
        for (r, c, d) in resolve_group(st, t):
            k = (r, c, d)
            if k in truth:
                truth_overlap_invalid = True
                uncovered_truth_sample.append(k)
                break
            truth.add(k)
        if truth_overlap_invalid:
            break

    link_count: Dict[Tuple[int, int, Digit], int] = {}
    for l in s.links:
        for (r, c, d) in resolve_group(st, l):
            k = (r, c, d)
            link_count[k] = link_count.get(k, 0) + 1

    covered = set(link_count.keys())
    uncovered_truth = list(truth - covered) if truth else []
    # Truth 为空时不允许删数（见上面的逻辑说明），因此这里将 truth_covered 视为 False。
    truth_empty = (s.T > 0 and len(truth) == 0)
    digit_kinds = len({int(x[2]) for x in truth}) if truth else 0
    digit_kinds_invalid = (s.T > 0 and truth and digit_kinds > int(s.T))
    truth_covered = (not truth_empty) and (not truth_overlap_invalid) and ((not truth) or (len(uncovered_truth) == 0))

    out: List[Tuple[int, Digit]] = []
    need = s.R + 1
    if need > 0 and truth_covered and (not truth_empty) and (not digit_kinds_invalid) and (not truth_overlap_invalid):
        for (r, c, d), cnt in link_count.items():
            if (r, c, d) in truth:
                continue
            if cnt < need:
                continue
            out.append((idx_of(r, c), d))
        out.sort(key=lambda x: (x[0], x[1]))

    proof: Dict[str, Any] = {
        "kind": "RANK",
        "T": s.T,
        "L": s.L,
        "R": s.R,
        "need": need,
        "truth_candidates_count": len(truth),
        "truth_digit_kinds": int(digit_kinds),
        "truth_digit_kinds_invalid": bool(digit_kinds_invalid),
        "truth_overlap_invalid": bool(truth_overlap_invalid),
        "link_candidates_count": len(covered),
        "truth_covered_by_links": truth_covered,
        "truth_empty_invalid": truth_empty,
        "uncovered_truth_count": len(uncovered_truth),
        # 只保留少量样本，避免 payload 过大
        "uncovered_truth_sample": [
            {"r": int(x[0]), "c": int(x[1]), "d": int(x[2])} for x in uncovered_truth[:12]
        ],
        "deletions_count": len(out),
    }
    return out, proof

