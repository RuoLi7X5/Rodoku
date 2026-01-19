from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path

from rodoku_api.puzzle_bank import parse_puzzle_bank_text
from rodoku_api.solver_core import solve_logic_only


def main() -> None:
    ap = argparse.ArgumentParser(description="Rodoku 批量刷题（本地文本题库 → JSON 输出）")
    ap.add_argument("--input", required=True, help="题库文本文件路径")
    ap.add_argument("--output", required=True, help="输出目录（会生成 run-*.json）")
    ap.add_argument("--limit", type=int, default=0, help="最多处理 N 题（0=不限制）")
    ap.add_argument("--max-steps", type=int, default=500, help="每题最多逻辑步数")
    args = ap.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        raise SystemExit(f"input 不存在: {in_path}")

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    text = in_path.read_text(encoding="utf-8", errors="ignore")
    puzzles = parse_puzzle_bank_text(text)
    if args.limit and args.limit > 0:
        puzzles = puzzles[: args.limit]

    summary = {
        "total": len(puzzles),
        "solved": 0,
        "stuck": 0,
        "invalid": 0,
    }

    for i, p in enumerate(puzzles, start=1):
        res = solve_logic_only(p, max_steps=args.max_steps)
        summary[res.status] = summary.get(res.status, 0) + 1
        out = {
            "index": i,
            "puzzle": p,
            "status": res.status,
            "steps": [asdict(s) for s in res.steps],
            "snapshots": res.snapshots,
        }
        (out_dir / f"run-{i:05d}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("done:", json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()

