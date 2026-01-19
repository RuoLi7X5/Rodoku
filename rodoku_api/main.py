from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import torch

import time
from collections import Counter
import re
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from .solver_core import SolveResult, solve_logic_only, solve_with_rank
from .techlib_runtime import (
  list_items as techlib_list_items,
  delete_item as techlib_delete_item,
  record_steps as techlib_record_steps,
  update_item as techlib_update_item,
  merge_items as techlib_merge_items,
)
from .metrics_store import load_metrics, save_metrics, MetricsStore
from .solve_jobs import create_job, get_job, stop_job
from .learn_params import params_for_metrics
from .replay_store import stats as replay_stats, iter_recent as replay_iter_recent
from .log_store import iter_recent as log_iter_recent
from .train_jobs import get_train_job, list_checkpoints, start_train_job, stop_train_job


app = FastAPI(title="Rodoku API (MVP)", version="0.1.0")

# 允许前端（Vite dev / 本地部署）跨域访问本 API
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
        # 允许 file:// 打开前端时（某些浏览器表现不同，保险起见）
        "null",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    # 证明：服务端能 import torch 并完成一次张量运算
    x = torch.rand(2, 3)
    y = x @ x.t()
    return {
        "ok": True,
        "torch_version": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "tensor_shape": list(y.shape),
    }


@app.get("/logs")
def get_logs(tail: int = 3000, job_id: str | None = None):
    """
    导出运行日志（JSONL）：
    - 包含 solve_job 的 search heartbeat / step 事件
    - 便于你审计“思考过程/停留时间/发现了什么”
    """
    tail = max(1, min(int(tail), 20000))
    xs = list(log_iter_recent(max_lines=tail, job_id=job_id))
    # 返回 JSONL 文本更适合直接保存到文件
    import json as _json

    text = "\n".join(_json.dumps(x, ensure_ascii=False) for x in xs)
    return {"ok": True, "tail": tail, "job_id": job_id, "lines": len(xs), "jsonl": text}


class SolveRequest(BaseModel):
  puzzle: str = Field(..., description="81位题目串，支持 0 或 . 表示空格")
  # 说明：为满足“必须解完”流程，本地默认给一个很大的上限；真正终止由“已解完”控制。
  max_steps: int = Field(200000, ge=1, le=200000)
  min_t: int = Field(1, ge=1, le=30)
  # 默认：Truth 组合上限 12；R 上限 3（优先搜索小体量/低秩结构）
  max_t: int = Field(12, ge=1, le=12)
  max_r: int = Field(3, ge=0, le=3)
  max_structures_per_step: int = Field(5000, ge=1, le=50000)
  # Truth 类型过滤（可选）：cell/rowDigit/colDigit/boxDigit；空=全部
  truth_types: list[str] | None = None
  # UR1 开关（可选）
  enable_ur1: bool | None = None
  use_policy: bool | None = None
  # solver = "rank" | "basic"
  solver: str = Field("rank")


class SolveJobStartRequest(BaseModel):
  puzzle: str = Field(..., description="81位题目串，支持 0 或 . 表示空格")
  min_t: int = Field(1, ge=1, le=30)
  max_t: int = Field(12, ge=1, le=12)
  max_r: int = Field(3, ge=0, le=3)
  max_structures_per_step: int = Field(200, ge=1, le=50000)
  truth_types: list[str] | None = None
  enable_ur1: bool | None = None
  use_policy: bool | None = None
  rank_time_budget_ms: int | None = None


class StepOut(BaseModel):
  action_type: str
  rationale: str
  affected: list[list[int | None]]  # [[idx, d|null], ...]
  meta: dict | None = None
  proof: dict | None = None


class SolveJobStatusResponse(BaseModel):
  id: str
  status: str
  attempts: int
  params: dict
  last_progress_at_ms: int
  message: str | None = None
  error: str | None = None
  steps: list[StepOut]
  snapshots: list[str]


class SolveResponse(BaseModel):
  status: str
  steps: list[StepOut]
  snapshots: list[str]


class TechlibPatchRequest(BaseModel):
  display_name: str | None = None
  aliases: list[str] | None = None
  tags: list[str] | None = None
  note: str | None = None
  disabled: bool | None = None


class TechlibMergeRequest(BaseModel):
  master_id: str
  merge_ids: list[str]


class TrainStartRequest(BaseModel):
  batch_size: int = Field(32, ge=4, le=256)
  lr: float = Field(3e-4, gt=0.0, lt=1.0)
  max_steps: int = Field(2000, ge=10, le=200000)
  ckpt_every: int = Field(300, ge=50, le=50000)
  mode: str = Field("bc", description="bc | rl")
  gamma: float = Field(0.99, gt=0.0, lt=1.0)


@app.post("/solve", response_model=SolveResponse)
def solve(req: SolveRequest):
  t0 = time.time()
  if req.solver == "basic":
    res: SolveResult = solve_logic_only(req.puzzle, max_steps=req.max_steps)
  else:
    res = solve_with_rank(
      req.puzzle,
      max_steps=req.max_steps,
      min_t=req.min_t,
      max_t=req.max_t,
      max_r=req.max_r,
      max_structures_per_step=req.max_structures_per_step,
      truth_types=req.truth_types,
      enable_ur1=(True if req.enable_ur1 is None else bool(req.enable_ur1)),
      use_policy=(False if req.use_policy is None else bool(req.use_policy)),
    )
  dt = time.time() - t0
  _metrics_add(res.status, len(res.steps), dt, [s.rationale for s in res.steps])
  _techlib_record(req.puzzle, res.snapshots, res.steps)
  return {
    "status": res.status,
    "steps": [
      {
        "action_type": s.action_type,
        "rationale": s.rationale,
        "affected": [[idx, d] for (idx, d) in s.affected],
        "meta": getattr(s, "meta", None),
        "proof": getattr(s, "proof", None),
      }
      for s in res.steps
    ],
    "snapshots": res.snapshots,
  }


@app.post("/solve_job/start")
def solve_job_start(req: SolveJobStartRequest):
  job = create_job(
    req.puzzle,
    min_t=req.min_t,
    max_t=req.max_t,
    max_r=req.max_r,
    max_structures_per_step=req.max_structures_per_step,
    truth_types=req.truth_types,
    enable_ur1=(True if req.enable_ur1 is None else bool(req.enable_ur1)),
    use_policy=(False if req.use_policy is None else bool(req.use_policy)),
    rank_time_budget_ms=(1200 if req.rank_time_budget_ms is None else int(req.rank_time_budget_ms)),
  )
  return {"id": job.id}


@app.get("/solve_job/{job_id}", response_model=SolveJobStatusResponse)
def solve_job_status(job_id: str):
  job = get_job(job_id)
  if not job:
    return {
      "id": job_id,
      "status": "not_found",
      "attempts": 0,
      "params": {},
      "last_progress_at_ms": 0,
      "error": "not_found",
      "steps": [],
      "snapshots": [],
    }
  return {
    "id": job.id,
    "status": job.status,
    "attempts": job.attempts,
    "params": job.params,
    "last_progress_at_ms": job.last_progress_at_ms,
    "message": getattr(job, "message", ""),
    "error": job.error,
    "steps": [
      {
        "action_type": s.action_type,
        "rationale": s.rationale,
        "affected": [[idx, d] for (idx, d) in s.affected],
        "meta": getattr(s, "meta", None),
        "proof": getattr(s, "proof", None),
      }
      for s in job.steps
    ],
    "snapshots": job.snapshots,
  }


@app.post("/solve_job/{job_id}/stop")
def solve_job_stop(job_id: str):
  ok = stop_job(job_id)
  return {"ok": ok}


# --- 统计与指标（MVP）---

_M = load_metrics()
_STRUCT_COUNTER: Counter[str] = Counter(_M.struct_counter)
_RUNS: int = _M.runs
_SOLVED: int = _M.solved
_STUCK: int = _M.stuck
_INVALID: int = _M.invalid
_STEP_COUNTS: list[int] = _M.step_counts
_DURATIONS: list[float] = _M.durations
_STATUS_HIST: list[str] = _M.status_hist
_ORACLE_STEPS_HIST: list[int] = _M.oracle_steps_hist

_RE_RANK = re.compile(r"^RANK:T(\d+)L(\d+)R(\d+)")


def _metrics_add(status: str, steps: int, duration_s: float, step_rationales: list[str]) -> None:
  global _RUNS, _SOLVED, _STUCK, _INVALID
  _RUNS += 1
  if status == "solved":
    _SOLVED += 1
  elif status == "invalid":
    _INVALID += 1
  else:
    _STUCK += 1
  _STEP_COUNTS.append(int(steps))
  _DURATIONS.append(float(duration_s))
  _STATUS_HIST.append(status)
  oracle_steps = sum(1 for r in step_rationales if r.startswith("ORACLE："))
  _ORACLE_STEPS_HIST.append(int(oracle_steps))

  # 结构频率统计：从 rationale 前缀提取（MVP）
  for r in step_rationales:
    if r.startswith("UR1:"):
      _STRUCT_COUNTER["UR1"] += 1
      continue
    m = _RE_RANK.search(r)
    if m:
      T, L, R = m.group(1), m.group(2), m.group(3)
      _STRUCT_COUNTER[f"RANK:T{T}L{L}R{R}"] += 1

  save_metrics(
    MetricsStore(
      runs=_RUNS,
      solved=_SOLVED,
      stuck=_STUCK,
      invalid=_INVALID,
      step_counts=_STEP_COUNTS,
      durations=_DURATIONS,
      status_hist=_STATUS_HIST,
      struct_counter=dict(_STRUCT_COUNTER),
      oracle_steps_hist=_ORACLE_STEPS_HIST,
    )
  )


def _techlib_record(puzzle: str, snapshots: list[str], steps_obj: list[Any]) -> None:
  # 统一由 techlib_runtime 负责 signature/分类与落盘，保证 /solve 与 /solve_job 一致
  techlib_record_steps(puzzle, snapshots, steps_obj, start_idx=0)


@app.get("/stats")
def stats():
  m = load_metrics()
  c = Counter(m.struct_counter or {})
  return {
    "runs": int(m.runs),
    "solved": int(m.solved),
    "stuck": int(m.stuck),
    "invalid": int(m.invalid),
    "structure_freq": [{"name": k, "count": v} for (k, v) in c.most_common(50)],
  }


@app.get("/techlib")
def techlib():
  out = techlib_list_items()
  return {"items": out, "total": len(out)}


@app.delete("/techlib/{tech_id}")
def delete_tech(tech_id: str):
  ok = techlib_delete_item(tech_id)
  return {"ok": ok} if ok else {"ok": False, "error": "not_found"}


@app.patch("/techlib/{tech_id}")
def patch_tech(tech_id: str, req: TechlibPatchRequest):
  patch = {k: v for (k, v) in req.model_dump().items() if v is not None}
  ok = techlib_update_item(tech_id, patch)
  return {"ok": ok} if ok else {"ok": False, "error": "not_found"}


@app.post("/techlib/merge")
def merge_tech(req: TechlibMergeRequest):
  ok = techlib_merge_items(req.master_id, req.merge_ids)
  return {"ok": ok} if ok else {"ok": False, "error": "bad_request"}


@app.get("/metrics")
def metrics():
  m = load_metrics()
  # solve 维度曲线（来自 /solve 的历史）
  steps_axis = list(range(len(m.step_counts)))
  solve_rate = []
  stuck_rate = []
  solved_so_far = 0
  stuck_so_far = 0
  for i, st in enumerate(m.status_hist):
    if st == "solved":
      solved_so_far += 1
    elif st in ("stuck", "invalid"):
      stuck_so_far += 1
    n = i + 1
    solve_rate.append(solved_so_far / n)
    stuck_rate.append(stuck_so_far / n)
  avg_steps = []
  total = 0
  for i, s in enumerate(m.step_counts):
    total += int(s)
    avg_steps.append(total / (i + 1))

  # step 归因曲线（主要来自 /solve_job 的 event_hist）
  ev = (m.event_hist or [])[-1200:]
  xs = list(range(len(ev)))
  cum = {"techlib": 0, "rank": 0, "ur": 0, "basic": 0, "other": 0}
  cum_del = 0
  techlib_hits = []
  rank_steps = []
  ur_steps = []
  basic_steps = []
  deletions = []
  for e in ev:
    k = str(e.get("k", "other"))
    if k not in cum:
      k = "other"
    cum[k] += 1
    cum_del += int(e.get("del", 0) or 0)
    techlib_hits.append(cum["techlib"])
    rank_steps.append(cum["rank"])
    ur_steps.append(cum["ur"])
    basic_steps.append(cum["basic"])
    deletions.append(cum_del)

  oracle_steps_avg = (sum(m.oracle_steps_hist) / len(m.oracle_steps_hist)) if m.oracle_steps_hist else 0

  # replay 进展曲线：cand_drop / forced_chain（来自 replay.jsonl 尾部）
  r_tail = list(replay_iter_recent(max_lines=1200))
  rxs = list(range(len(r_tail)))
  cand_drop_cum = []
  cand_drop_avg = []
  forced_chain_cum = []
  forced_chain_avg = []
  _cd = 0
  _fc = 0
  for i, e in enumerate(r_tail):
    try:
      _cd += int(e.get("cand_drop", 0) or 0)
      _fc += int(e.get("forced_chain", 0) or 0)
    except Exception:
      pass
    cand_drop_cum.append(_cd)
    forced_chain_cum.append(_fc)
    cand_drop_avg.append(_cd / (i + 1))
    forced_chain_avg.append(_fc / (i + 1))
  return {
    "steps": steps_axis,
    "solve_rate": solve_rate,
    "avg_steps": avg_steps,
    "stuck_rate": stuck_rate,
    "oracle_steps_avg": oracle_steps_avg,
    # 归因曲线
    "step_axis": xs,
    "techlib_hits": techlib_hits,
    "rank_steps": rank_steps,
    "ur_steps": ur_steps,
    "basic_steps": basic_steps,
    "deletions": deletions,
    "counters": {
      "step_kind_counter": m.step_kind_counter,
      "deletion_kind_counter": m.deletion_kind_counter,
    },
    # 策略参数向量（可视化雷达图/曲线用）
    "params": params_for_metrics()[0],
    "params_history": params_for_metrics()[1][-300:],
    # 训练管线 / PyTorch 训练 job 的当前状态
    "replay": {
      "stats": (lambda s: (
        # 兼容：旧版 replay_stats 可能是对象（.total/.bytes/.last_ms），新版是 dict
        {
          "total_tail": (s.get("count", 0) if isinstance(s, dict) else getattr(s, "total", 0)),
          "bytes": (s.get("bytes", 0) if isinstance(s, dict) else getattr(s, "bytes", 0)),
          "last_ms": (s.get("last_at_ms", 0) if isinstance(s, dict) else getattr(s, "last_ms", 0)),
          # 附加：把 dict 原样透出，便于排查数据管线
          "raw": s if isinstance(s, dict) else None,
        }
      ))(replay_stats())
    },
    "train": (lambda j: None if not j else {
      "id": j.id,
      "status": j.status,
      "steps": j.steps,
      "last_loss": j.last_loss,
      "started_ms": j.started_ms,
      "last_ms": j.last_ms,
      "error": j.error,
      "checkpoints": list_checkpoints(10),
    })(get_train_job()),
    "train_hist": (m.train_hist or [])[-800:],
    "replay_axis": rxs,
    "cand_drop_cum": cand_drop_cum,
    "cand_drop_avg": cand_drop_avg,
    "forced_chain_cum": forced_chain_cum,
    "forced_chain_avg": forced_chain_avg,
  }


@app.post("/train/start")
def train_start(req: TrainStartRequest):
  j = start_train_job(batch_size=req.batch_size, lr=req.lr, max_steps=req.max_steps, ckpt_every=req.ckpt_every, mode=req.mode, gamma=req.gamma)
  return {"ok": True, "id": j.id}


@app.post("/train/stop")
def train_stop():
  ok = stop_train_job()
  return {"ok": ok}

