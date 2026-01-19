from __future__ import annotations

import json
import os
import time
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple


from .runtime_paths import legacy_path, techlib_path


TECHLIB_PATH = techlib_path()
_WRITE_LOCK = threading.Lock()


@dataclass
class TechLib:
    items: Dict[str, Dict[str, Any]]
    order: List[str]


def load_techlib() -> TechLib:
    # 兼容迁移：若新路径不存在但旧路径存在，则读取旧文件（并在后续 save 时写入新路径）
    path = TECHLIB_PATH
    if not path.exists():
        legacy = legacy_path("_techlib.json")
        if legacy.exists():
            path = legacy
        else:
            return TechLib(items={}, order=[])
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        items = obj.get("items", {}) or {}
        order = obj.get("order", []) or []
        # clean order
        order = [k for k in order if k in items]
        # append missing
        for k in items.keys():
            if k not in order:
                order.append(k)
        return TechLib(items=items, order=order)
    except Exception:
        # 若文件损坏，不阻塞服务启动
        return TechLib(items={}, order=[])


def save_techlib(items: Dict[str, Dict[str, Any]], order: List[str]) -> None:
    payload = {"items": items, "order": order}
    with _WRITE_LOCK:
        tmp = TECHLIB_PATH.with_name(f"{TECHLIB_PATH.name}.{os.getpid()}.tmp")
        try:
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            for _ in range(20):
                try:
                    os.replace(tmp, TECHLIB_PATH)
                    return
                except PermissionError:
                    time.sleep(0.03)
            TECHLIB_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            return

