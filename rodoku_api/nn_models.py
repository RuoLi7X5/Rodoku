from __future__ import annotations

import torch
import torch.nn as nn


class RodokuPolicyValueNet(nn.Module):
    """
    一个足够小的 policy/value 网络（MVP）：
    - 输入：x (B, 20, 9, 9)
    - 输出：
      - policy_logits (B, A) where A=81*9*2
      - value (B,) in [-1,1] via tanh
    """

    def __init__(self, action_dim: int = 81 * 9 * 2):
        super().__init__()
        self.action_dim = int(action_dim)
        self.trunk = nn.Sequential(
            nn.Conv2d(20, 64, 3, padding=1),
            nn.ReLU(),
            nn.Conv2d(64, 64, 3, padding=1),
            nn.ReLU(),
            nn.Conv2d(64, 32, 3, padding=1),
            nn.ReLU(),
            nn.Flatten(),
        )
        self.head_pi = nn.Sequential(
            nn.Linear(32 * 9 * 9, 512),
            nn.ReLU(),
            nn.Linear(512, self.action_dim),
        )
        self.head_v = nn.Sequential(
            nn.Linear(32 * 9 * 9, 256),
            nn.ReLU(),
            nn.Linear(256, 1),
            nn.Tanh(),
        )

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        h = self.trunk(x)
        pi = self.head_pi(h)
        v = self.head_v(h).squeeze(-1)
        return pi, v

