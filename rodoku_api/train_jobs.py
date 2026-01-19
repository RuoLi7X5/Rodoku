from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import torch
import torch.nn.functional as F

from .nn_models import RodokuPolicyValueNet
from .nn_state import encode_action, state_key_to_tensors
from .replay_store import iter_recent
from .metrics_store import load_metrics, save_metrics


from .runtime_paths import ckpt_dir


CKPT_DIR = ckpt_dir()

_LOCK = threading.Lock()


@dataclass
class TrainJob:
    id: str
    status: str  # running/stopped/error
    started_ms: int
    steps: int
    last_loss: float
    last_ms: int
    error: Optional[str]
    stop_event: threading.Event


_JOB: TrainJob | None = None


def _now_ms() -> int:
    return int(time.time() * 1000)


def _save_ckpt(model: RodokuPolicyValueNet, opt: torch.optim.Optimizer, step: int) -> str:
    name = f"policy_{step:08d}.pt"
    path = CKPT_DIR / name
    payload = {
        "step": int(step),
        "model": model.state_dict(),
        "opt": opt.state_dict(),
        "at_ms": _now_ms(),
        "torch_version": torch.__version__,
    }
    tmp = CKPT_DIR / f"{name}.{os.getpid()}.tmp"
    torch.save(payload, tmp)
    os.replace(tmp, path)
    return str(path)


def list_checkpoints(limit: int = 30) -> List[str]:
    ps = sorted(CKPT_DIR.glob("policy_*.pt"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [str(p.name) for p in ps[: max(1, int(limit))]]


def start_train_job(
    *,
    batch_size: int = 32,
    lr: float = 3e-4,
    max_steps: int = 2000,
    ckpt_every: int = 300,
    mode: str = "bc",  # bc | rl
    gamma: float = 0.99,
) -> TrainJob:
    global _JOB
    with _LOCK:
        if _JOB and _JOB.status == "running":
            return _JOB
        jid = f"train-{_now_ms()}"
        job = TrainJob(
            id=jid,
            status="running",
            started_ms=_now_ms(),
            steps=0,
            last_loss=0.0,
            last_ms=_now_ms(),
            error=None,
            stop_event=threading.Event(),
        )
        _JOB = job

    th = threading.Thread(
        target=_run_job,
        args=(job, int(batch_size), float(lr), int(max_steps), int(ckpt_every), str(mode), float(gamma)),
        daemon=True,
    )
    th.start()
    return job


def get_train_job() -> TrainJob | None:
    with _LOCK:
        return _JOB


def stop_train_job() -> bool:
    with _LOCK:
        if not _JOB:
            return False
        _JOB.stop_event.set()
        return True


def _sample_batch(batch_size: int) -> List[Dict[str, Any]]:
    rows = list(iter_recent(max_lines=5000))
    if not rows:
        return []
    idxs = np.random.randint(0, len(rows), size=(batch_size,))
    return [rows[int(i)] for i in idxs]


def _run_job(job: TrainJob, batch_size: int, lr: float, max_steps: int, ckpt_every: int, mode: str, gamma: float) -> None:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = RodokuPolicyValueNet().to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr)

    try:
        for step in range(max_steps):
            if job.stop_event.is_set():
                with _LOCK:
                    job.status = "stopped"
                    job.last_ms = _now_ms()
                return

            batch = _sample_batch(batch_size)
            if not batch:
                time.sleep(0.2)
                continue

            xs = []
            ys_pi = []
            ys_v = []
            after_keys = []
            dones = []
            for b in batch:
                try:
                    x, _mask = state_key_to_tensors(str(b.get("before_key", "")))
                    xs.append(x)
                    reward = float(b.get("reward", 0.0) or 0.0)
                    ys_v.append(reward)
                    after_keys.append(str(b.get("after_key", "")))
                    dones.append(bool(b.get("done", False)))
                    # multi-action：一个 step 可能包含多个 affected，统一做 multi-label BCE
                    tgt = np.zeros((81 * 9 * 2,), dtype=np.float32)
                    for (idx, d) in b.get("affected", []) or []:
                        if d is None:
                            continue
                        a_elim = encode_action(str(b.get("action_type", "eliminate")), int(idx), int(d))
                        tgt[a_elim] = 1.0
                    ys_pi.append(tgt)
                except Exception:
                    continue

            if not xs:
                continue

            x_t = torch.from_numpy(np.stack(xs, axis=0)).to(device)
            y_pi = torch.from_numpy(np.stack(ys_pi, axis=0)).to(device)
            r_t = torch.from_numpy(np.array(ys_v, dtype=np.float32)).to(device)
            done_t = torch.from_numpy(np.array(dones, dtype=np.float32)).to(device)

            model.train()
            pi_logits, v = model(x_t)

            # policy：masked BCEWithLogits（只在合法动作上计算 loss，避免学“非法动作”）
            # 注意：mask 来自 before_key 的合法候选集
            masks = []
            for b in batch:
                try:
                    _x, m = state_key_to_tensors(str(b.get("before_key", "")))
                    masks.append(m)
                except Exception:
                    masks.append(np.ones((81 * 9 * 2,), dtype=np.float32))
            m_t = torch.from_numpy(np.stack(masks, axis=0)).to(device)
            # value target：bc 模式用 reward 拟合；rl 模式用 TD(0) target
            if mode == "rl":
                # bootstrap V(s')
                xs2 = []
                for ak in after_keys:
                    try:
                        x2, _m2 = state_key_to_tensors(ak)
                        xs2.append(x2)
                    except Exception:
                        xs2.append(np.zeros((20, 9, 9), dtype=np.float32))
                x2_t = torch.from_numpy(np.stack(xs2, axis=0)).to(device)
                with torch.no_grad():
                    _pi2, v2 = model(x2_t)
                td_target = r_t + (1.0 - done_t) * float(gamma) * v2.detach()
                adv = (td_target - v).detach().clamp(-2.0, 2.0)
            else:
                td_target = r_t
                adv = torch.zeros_like(v).detach()

            # policy：
            # - bc：masked BCE（之前逻辑）
            # - rl：只用正样本动作的 logp 做 REINFORCE（advantage 加权），负样本不强行学习
            if mode == "rl":
                # 只取正样本动作位置
                pos = (y_pi > 0.5) & (m_t > 0.5)
                # 若一个样本无正动作，跳过其 policy 梯度
                logp = torch.zeros((x_t.shape[0],), device=device)
                for bi in range(x_t.shape[0]):
                    idxs = torch.where(pos[bi])[0]
                    if idxs.numel() == 0:
                        continue
                    logp[bi] = F.logsigmoid(pi_logits[bi, idxs]).mean()
                loss_pi = -(adv * logp).mean()
            else:
                bce = F.binary_cross_entropy_with_logits(pi_logits, y_pi, reduction="none")
                denom = torch.clamp(m_t.sum(), min=1.0)
                loss_pi = (bce * m_t).sum() / denom

            loss_v = F.mse_loss(v, td_target)
            loss = loss_pi + 0.2 * loss_v

            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()

            with _LOCK:
                job.steps = step + 1
                job.last_loss = float(loss.detach().cpu().item())
                job.last_ms = _now_ms()

            # 训练曲线落盘（给 /metrics & /viz）
            try:
                m = load_metrics()
                th = list(getattr(m, "train_hist", []) or [])
                th.append({"at_ms": _now_ms(), "step": int(step + 1), "loss": float(job.last_loss), "lr": float(lr)})
                if len(th) > 2000:
                    th = th[-1500:]
                m.train_hist = th  # type: ignore[attr-defined]
                save_metrics(m)
            except Exception:
                pass

            if ckpt_every > 0 and (step + 1) % ckpt_every == 0:
                _save_ckpt(model, opt, step + 1)

    except Exception as e:
        with _LOCK:
            job.status = "error"
            job.error = str(e)
            job.last_ms = _now_ms()
        return

