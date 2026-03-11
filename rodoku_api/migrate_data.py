import json
import os
import shutil
from pathlib import Path
from typing import Dict, Any, List

def migrate():
    # Define paths
    root = Path(__file__).resolve().parents[1]
    target_dir = root / "data"
    target_dir.mkdir(exist_ok=True)
    
    # Sources
    src_legacy = root / "rodoku_api"
    src_runtime = root / "rodoku_py" / "_runtime"
    
    print(f"Target Directory: {target_dir}")
    print(f"Source Legacy: {src_legacy}")
    print(f"Source Runtime: {src_runtime}")
    
    # 1. Migrate TechLib (Merge items)
    print("\n--- Migrating TechLib ---")
    techlib_items = {}
    techlib_order = []
    
    # Helper to load techlib
    def load_techlib(p: Path):
        if not p.exists(): return {}, []
        try:
            data = json.loads(p.read_text(encoding='utf-8'))
            return data.get("items", {}), data.get("order", [])
        except:
            return {}, []

    # Load from all sources (priority: runtime > legacy > target(if exists))
    # Actually, we want to UNION all items.
    sources = [
        target_dir / "_techlib.json",
        src_runtime / "_techlib.json",
        src_legacy / "_techlib.json"
    ]
    
    for p in sources:
        if p.exists():
            print(f"Reading {p}...")
            items, order = load_techlib(p)
            print(f"  Found {len(items)} items.")
            # Merge items
            for k, v in items.items():
                if k not in techlib_items:
                    techlib_items[k] = v
                    techlib_order.append(k)
                else:
                    # If duplicate, maybe keep the one with more info?
                    # For now, assume keys are unique hashes and content is static.
                    pass
    
    # Save merged
    if techlib_items:
        print(f"Saving merged TechLib ({len(techlib_items)} items) to {target_dir / '_techlib.json'}")
        (target_dir / "_techlib.json").write_text(
            json.dumps({"items": techlib_items, "order": techlib_order}, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
    
    # 2. Migrate Metrics (Pick best)
    print("\n--- Migrating Metrics ---")
    best_metrics = None
    best_runs = -1
    
    sources = [
        target_dir / "_metrics.json",
        src_runtime / "_metrics.json",
        src_legacy / "_metrics.json"
    ]
    
    for p in sources:
        if p.exists():
            print(f"Reading {p}...")
            try:
                data = json.loads(p.read_text(encoding='utf-8'))
                runs = data.get("runs", 0)
                print(f"  Runs: {runs}")
                if runs > best_runs:
                    best_runs = runs
                    best_metrics = data
            except:
                pass
    
    if best_metrics:
        print(f"Saving best Metrics (Runs: {best_runs}) to {target_dir / '_metrics.json'}")
        (target_dir / "_metrics.json").write_text(
            json.dumps(best_metrics, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )

    # 3. Migrate Learn Params (Pick most recent/valid)
    print("\n--- Migrating Learn Params ---")
    # We just split params, so rodoku_api/_learn_params.json should be the clean one.
    # But let's check runtime one too.
    
    best_params = None
    best_ts = -1
    
    sources = [
        target_dir / "_learn_params.json",
        src_runtime / "_learn_params.json",
        src_legacy / "_learn_params.json"
    ]
    
    for p in sources:
        if p.exists():
            print(f"Reading {p}...")
            try:
                data = json.loads(p.read_text(encoding='utf-8'))
                # Check timestamp
                ts = data.get("updated_at_ms", 0)
                # If no timestamp, maybe it's the old format with history?
                if "history" in data and isinstance(data["history"], list) and data["history"]:
                     ts = data["history"][-1].get("at_ms", 0)
                
                print(f"  Timestamp: {ts}")
                if ts > best_ts:
                    best_ts = ts
                    best_params = data
            except:
                pass

    if best_params:
        # Ensure it's the compact format (no history)
        if "history" in best_params:
            print("  Stripping history from params...")
            del best_params["history"]
            
        print(f"Saving best Params (TS: {best_ts}) to {target_dir / '_learn_params.json'}")
        (target_dir / "_learn_params.json").write_text(
            json.dumps(best_params, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )

    # 4. Migrate Replay (Concat)
    print("\n--- Migrating Replay Logs ---")
    replay_lines = set()
    
    sources = [
        target_dir / "_replay.jsonl",
        src_runtime / "_replay.jsonl",
        src_legacy / "_replay.jsonl"
    ]
    
    for p in sources:
        if p.exists():
            print(f"Reading {p}...")
            try:
                lines = p.read_text(encoding='utf-8').splitlines()
                for line in lines:
                    if line.strip():
                        replay_lines.add(line.strip())
            except:
                pass
    
    if replay_lines:
        print(f"Saving merged Replay ({len(replay_lines)} lines) to {target_dir / '_replay.jsonl'}")
        (target_dir / "_replay.jsonl").write_text(
            "\n".join(replay_lines),
            encoding='utf-8'
        )

    print("\nMigration Completed!")
    print("Please verify the contents of 'data/' directory.")
    print("You can manually delete 'rodoku_py/_runtime' and 'rodoku_api/_*.json' after verification.")

if __name__ == "__main__":
    migrate()
