from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def repo_root() -> Path:
    # .../rodoku_api/runtime_paths.py -> .../ (repo root)
    return Path(__file__).resolve().parents[1]


def data_dir() -> Path:
    """
    运行时数据目录（避免 uvicorn --reload 监控到这些文件变化而重启，导致 solve_job 丢失）。
    - 可用环境变量 RODOKU_DATA_DIR 覆盖
    - 默认：repo_root/rodoku_py/_runtime
    """
    env = os.environ.get("RODOKU_DATA_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return (repo_root() / "rodoku_py" / "_runtime").resolve()


def ensure_data_dir() -> Path:
    p = data_dir()
    p.mkdir(parents=True, exist_ok=True)
    return p


def legacy_path(filename: str) -> Path:
    # 旧版都写在 rodoku_api 同目录下
    return Path(__file__).with_name(filename)


def techlib_path() -> Path:
    return ensure_data_dir() / "_techlib.json"


def metrics_path() -> Path:
    return ensure_data_dir() / "_metrics.json"


def learn_params_path() -> Path:
    return ensure_data_dir() / "_learn_params.json"


def replay_path() -> Path:
    return ensure_data_dir() / "_replay.jsonl"


def events_log_path() -> Path:
    # 运行时事件日志（jsonl）：记录搜索心跳/策略选择/每步落子，供可视化与审计导出
    return ensure_data_dir() / "_events.jsonl"


def ckpt_dir() -> Path:
    p = ensure_data_dir() / "_checkpoints"
    p.mkdir(parents=True, exist_ok=True)
    return p

