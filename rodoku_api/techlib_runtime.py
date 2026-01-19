from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Tuple

from .techlib_store import load_techlib, save_techlib


_LOCK = threading.Lock()
_TL = load_techlib()
_TECHLIB: Dict[str, Dict[str, Any]] = _TL.items
_ORDER: List[str] = _TL.order


def _box_of_idx(idx: int) -> int:
    r = idx // 9
    c = idx % 9
    return (r // 3) * 3 + (c // 3)


def _type_key(t: str) -> str:
    # compact: cell/rowDigit/colDigit/boxDigit
    if t == "cell":
        return "N"
    if t == "rowDigit":
        return "R"
    if t == "colDigit":
        return "C"
    if t == "boxDigit":
        return "B"
    return "X"


def _count_types(refs: List[Dict[str, Any]]) -> str:
    # output e.g. N1R2C0B1
    cnt = {"N": 0, "R": 0, "C": 0, "B": 0, "X": 0}
    for r in refs:
        k = _type_key(str(r.get("type", "")))
        cnt[k] = cnt.get(k, 0) + 1
    return f"N{cnt['N']}R{cnt['R']}C{cnt['C']}B{cnt['B']}X{cnt['X']}"


def _digits_from_refs(refs: List[Dict[str, Any]]) -> List[int]:
    ds = []
    for r in refs:
        d = r.get("d", None)
        if d is None:
            continue
        try:
            di = int(d)
            if 1 <= di <= 9:
                ds.append(di)
        except Exception:
            pass
    ds = sorted(list(set(ds)))
    return ds


def build_signature(step_meta: Dict[str, Any], deletions: List[Dict[str, Any]]) -> Tuple[str, str, Dict[str, Any]]:
    """
    Returns (kind, signature, features_additions)
    - signature 用于“判定是否新技巧”
    - features_additions 用于存储可解释的分类维度（你要求的：候选种类数、秩、T分类、强弱区域类型等）
    """
    kind = str(step_meta.get("kind", ""))
    # skip if unknown
    if kind not in ("RANK", "UR1", "SUBSET"):
        return "", "", {}

    # derived from deletions
    digits = sorted(list({int(x["d"]) for x in deletions if x.get("d") is not None}))
    boxes = sorted(list({_box_of_idx(int(x["idx"])) for x in deletions if x.get("idx") is not None}))
    digit_count = len(digits)
    boxes_count = len(boxes)
    derived = {
        "digit_count": digit_count,
        "digit_kind": "同数" if digit_count <= 1 else "异数",
        "digits": digits,
        "boxes_count": boxes_count,
        "boxes": boxes,
    }

    if kind == "SUBSET":
        # “同屋 N格=N数” 的基础子集删数（naked subset）
        house_type = str(step_meta.get("house_type", ""))  # row/col/box
        n = int(step_meta.get("n", 0) or 0)
        if house_type not in ("row", "col", "box") or n < 2 or n > 6:
            return "", "", {}
        additions = {
            **derived,
            "n": int(n),
            "house_type": house_type,
        }
        # signature 不包含具体位置（cells），只体现类型/规模/删数覆盖特征，便于“同类自动归并”
        sig = f"SUBSET:{house_type}:N{n}:D{digit_count}:B{boxes_count}"
        return kind, sig, additions

    if kind == "UR1":
        # UR1 本身结构较具体，沿用原 signature 但带上 digit/boxes 分类
        rows = step_meta.get("rows", None)
        cols = step_meta.get("cols", None)
        ab = step_meta.get("ab", None)
        sig = f"UR1:r{rows}c{cols}:ab{ab}:D{digit_count}:B{boxes_count}"
        return kind, sig, derived

    # RANK
    T = int(step_meta.get("T", 0) or 0)
    L = int(step_meta.get("L", 0) or 0)
    R = int(step_meta.get("R", max(0, L - T)) or 0)
    truths = step_meta.get("truths", []) or []
    links = step_meta.get("links", []) or []
    if not isinstance(truths, list) or not isinstance(links, list):
        truths, links = [], []

    truth_types = _count_types(truths)
    link_types = _count_types(links)
    truth_digits = _digits_from_refs(truths)
    link_digits = _digits_from_refs(links)

    additions = {
        **derived,
        "T": T,
        "L": L,
        "R": R,
        "truth_types": truth_types,
        "link_types": link_types,
        "truth_digit_count": len(truth_digits),
        "link_digit_count": len(link_digits),
        "truth_digits": truth_digits,
        "link_digits": link_digits,
    }

    # 你的分类维度体现在 signature：
    # - 秩（R）
    # - T 数量（T）
    # - 覆盖候选种类数（digit_count）
    # - 强弱区域类型组合（truth_types/link_types）
    # - 弱区域候选数字种类数（link_digit_count）
    sig = f"RANK:R{R}:T{T}:D{digit_count}:LD{len(link_digits)}:TT{truth_types}:LT{link_types}"
    return kind, sig, additions


def record_step(puzzle: str, before_key: str, after_key: str, step: Any) -> None:
    meta = getattr(step, "meta", None) or {}
    kind, sig, additions = build_signature(meta, [{"idx": idx, "d": d} for (idx, d) in getattr(step, "affected", []) if d is not None])
    if not sig or not kind:
        return

    rat = getattr(step, "rationale", "")
    dels = [{"idx": idx, "d": d} for (idx, d) in getattr(step, "affected", []) if d is not None]
    features = {**(meta or {}), **additions}

    with _LOCK:
        # 若该 signature 曾被人工合并到 master，则自动记到 master（满足“下次同类型自动合并”的最小版）
        if sig in _TECHLIB and _TECHLIB[sig].get("merged_into"):
            sig = str(_TECHLIB[sig]["merged_into"])

        # 若本步来自技巧库重放：
        # - 不允许“新增技巧”（避免爆炸/漂移）
        # - 但允许“强化已存在技巧”的出现次数（seen_count）
        if meta.get("source") == "techlib":
            if sig in _TECHLIB and not _TECHLIB[sig].get("disabled"):
                _TECHLIB[sig]["seen_count"] = int(_TECHLIB[sig].get("seen_count", 0)) + 1
                _TECHLIB[sig]["last_used_ms"] = int(time.time() * 1000)
                save_techlib(_TECHLIB, _ORDER)
            return

        if sig not in _TECHLIB:
            _TECHLIB[sig] = {
                "id": sig,
                "kind": kind,
                "signature": sig,
                # 可编辑字段（默认空）
                "display_name": "",
                "aliases": [],
                "tags": [],
                "note": "",
                "disabled": False,
                "merged_into": None,
                "merged_from": [],
                "first_seen_ms": int(time.time() * 1000),
                "seen_count": 1,
                "last_used_ms": None,
                "features": features,
                "example": {
                    "puzzle": puzzle,
                    "snapshot_before": before_key,
                    "snapshot_after": after_key,
                    "rationale": rat,
                    "deletions": dels,
                },
            }
            _ORDER.append(sig)
            save_techlib(_TECHLIB, _ORDER)
        else:
            if _TECHLIB[sig].get("disabled"):
                return
            _TECHLIB[sig]["seen_count"] = int(_TECHLIB[sig].get("seen_count", 0)) + 1
            _TECHLIB[sig]["last_used_ms"] = int(time.time() * 1000)
            save_techlib(_TECHLIB, _ORDER)


def record_steps(puzzle: str, snapshots: List[str], steps: List[Any], start_idx: int = 0) -> None:
    for i in range(start_idx, len(steps)):
        before_key = snapshots[i] if i < len(snapshots) else ""
        after_key = snapshots[i + 1] if (i + 1) < len(snapshots) else before_key
        record_step(puzzle, before_key, after_key, steps[i])


def list_items() -> List[Dict[str, Any]]:
    with _LOCK:
        # 默认不返回被合并项（它们会在 master 的 merged_from 里体现）
        out = []
        for k in _ORDER:
            if k not in _TECHLIB:
                continue
            if _TECHLIB[k].get("merged_into"):
                continue
            out.append(_TECHLIB[k])
        return out


def update_item(tech_id: str, patch: Dict[str, Any]) -> bool:
    allowed = {"display_name", "aliases", "tags", "note", "disabled"}
    with _LOCK:
        if tech_id not in _TECHLIB:
            return False
        it = _TECHLIB[tech_id]
        for k, v in patch.items():
            if k not in allowed:
                continue
            it[k] = v
        save_techlib(_TECHLIB, _ORDER)
        return True


def merge_items(master_id: str, ids: List[str]) -> bool:
    with _LOCK:
        if master_id not in _TECHLIB:
            return False
        master = _TECHLIB[master_id]
        if master.get("merged_into"):
            # 不能合并到一个已经被合并的 item
            return False
        merged_from = set(master.get("merged_from") or [])
        for tid in ids:
            if tid == master_id:
                continue
            if tid not in _TECHLIB:
                continue
            it = _TECHLIB[tid]
            if it.get("merged_into"):
                continue
            # 聚合统计
            master["seen_count"] = int(master.get("seen_count", 0)) + int(it.get("seen_count", 0))
            # 保留别名（把被合并的 signature 作为 alias）
            aliases = list(master.get("aliases") or [])
            if tid not in aliases:
                aliases.append(tid)
            master["aliases"] = aliases
            # 合并样例：最多保留 12 个（避免爆炸）
            exs = list(master.get("examples") or [])
            if master.get("example"):
                # 确保 master 的 example 存进 examples 一次
                if not exs:
                    exs.append(master["example"])
            if it.get("example"):
                exs.append(it["example"])
            master["examples"] = exs[-12:]
            # 标记被合并
            it["merged_into"] = master_id
            merged_from.add(tid)
        master["merged_from"] = sorted(list(merged_from))
        save_techlib(_TECHLIB, _ORDER)
        return True


def delete_item(tech_id: str) -> bool:
    with _LOCK:
        if tech_id not in _TECHLIB:
            return False
        _TECHLIB.pop(tech_id, None)
        _ORDER[:] = [k for k in _ORDER if k != tech_id]
        save_techlib(_TECHLIB, _ORDER)
        return True

