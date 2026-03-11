from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

class RodokuGraphNet(nn.Module):
    """
    Rank Logic Driven Graph Neural Network for Sudoku.
    
    Nodes:
    - Cell Nodes (81): r1c1...r9c9
    - Candidate Nodes (729): r1c1(1)...r9c9(9)
    - Set Nodes (324): 
      - Row-Digit (9x9=81)
      - Col-Digit (9x9=81)
      - Box-Digit (9x9=81)
      - Cell-Constraint (81) [Implicitly handled by Cell-Candidate relation]
    
    Architecture:
    - Input: (B, 20, 9, 9) standard board representation
    - Internal: 
      - Embeddings for Candidates (B, 729, D)
      - Embeddings for Sets (B, 243, D) [Row/Col/Box x Digit]
    - Interaction (Message Passing): 
      - Candidates attend to the 3 Sets they belong to (Row-D, Col-D, Box-D).
      - Sets attend to the 9 Candidates they contain.
    - Heads:
      - Policy: Action logits (Commit/Eliminate) per candidate.
      - Value: State evaluation.
      - UR Sensor: Global uniqueness probability.
    """

    def __init__(self, action_dim: int = 81 * 9 * 2, embed_dim: int = 128, num_layers: int = 4, in_channels: int = 22):
        super().__init__()
        self.action_dim = int(action_dim)
        self.embed_dim = embed_dim
        
        # 1. Input Encoder
        # Maps the input channels (digits + candidates + masks + explicit features) to an initial embedding per cell
        self.cell_encoder = nn.Sequential(
            nn.Conv2d(in_channels, embed_dim, 1),
            nn.ReLU(),
            nn.Conv2d(embed_dim, embed_dim, 1),
        )
        
        # 2. Candidate Embedding Initialization
        # Expand cell embeddings (81) to candidate embeddings (729).
        # We add a learnable "Digit Embedding" to distinguish candidates 1..9 within a cell.
        self.digit_embed = nn.Parameter(torch.randn(9, embed_dim))
        
        # 3. Set Embedding Initialization
        # 243 Sets: 81 Row-Digit + 81 Col-Digit + 81 Box-Digit
        self.num_sets = 9 * 9 * 3
        self.set_embed = nn.Parameter(torch.randn(self.num_sets, embed_dim))
        
        # 4. Message Passing Layers
        self.layers = nn.ModuleList([
            RankMessagePassingLayer(embed_dim)
            for _ in range(num_layers)
        ])
        
        # 5. Heads
        # Policy Head: Predicts action logits for each candidate (729 * 2)
        # We produce 2 logits per candidate: [Commit, Eliminate]
        self.head_pi = nn.Sequential(
            nn.Linear(embed_dim, 128),
            nn.ReLU(),
            nn.Linear(128, 2)
        )
        
        # Value Head: Aggregates global state
        self.head_v = nn.Sequential(
            nn.Linear(embed_dim, 128),
            nn.ReLU(),
            nn.Linear(128, 1),
            nn.Tanh()
        )
        
        # Global Uniqueness Sensor (UR Head)
        # Predicts probability that the current state leads to a unique solution (1.0) vs multiple/invalid (0.0)
        self.head_ur = nn.Sequential(
            nn.Linear(embed_dim, 128),
            nn.ReLU(),
            nn.Linear(128, 1),
            nn.Sigmoid()
        )
        
        # Aux Rank Head (Optional)
        # Predicts "rank relevance" score for each candidate to guide attention
        self.head_rank = nn.Sequential(
            nn.Linear(embed_dim, 64),
            nn.ReLU(),
            nn.Linear(64, 1),
            nn.Sigmoid()
        )
        
        # Precompute static adjacency matrices for message passing
        self.register_buffer("cand_to_set_idx", self._build_adjacency())

    def _build_adjacency(self):
        # Build mapping: Which 3 sets does each candidate (cell_i, digit_d) belong to?
        # Candidate idx: 0..728 (cell_i * 9 + d_idx)
        # Set idx: 0..242
        #   0..80: Row r, Digit d
        #   81..161: Col c, Digit d
        #   162..242: Box b, Digit d
        
        cand_to_set = torch.zeros(729, 3, dtype=torch.long)
        
        for cell_i in range(81):
            r = cell_i // 9
            c = cell_i % 9
            b = (r // 3) * 3 + (c // 3)
            
            for d_idx in range(9): # 0..8 (representing digits 1..9)
                cand_idx = cell_i * 9 + d_idx
                
                # Set indices
                set_r = r * 9 + d_idx
                set_c = 81 + c * 9 + d_idx
                set_b = 162 + b * 9 + d_idx
                
                cand_to_set[cand_idx, 0] = set_r
                cand_to_set[cand_idx, 1] = set_c
                cand_to_set[cand_idx, 2] = set_b
                
        return cand_to_set

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        B = x.shape[0]
        
        # --- 1. Initialize Nodes ---
        
        # Cell features: (B, 20, 9, 9) -> (B, D, 81) -> (B, 81, D)
        cell_feat = self.cell_encoder(x).flatten(2).permute(0, 2, 1)
        
        # Candidate features: (B, 81, 9, D)
        # cand_feat[b, cell, digit] = cell_feat[b, cell] + digit_embed[digit]
        cand_feat = cell_feat.unsqueeze(2) + self.digit_embed.unsqueeze(0).unsqueeze(0)
        cand_feat = cand_feat.reshape(B, 729, self.embed_dim) # (B, 729, D)
        
        # Set features: (B, 243, D)
        set_feat = self.set_embed.unsqueeze(0).expand(B, -1, -1)
        
        # --- 2. Message Passing ---
        # Perform graph convolution between Candidates and Sets
        for layer in self.layers:
            cand_feat, set_feat = layer(cand_feat, set_feat, self.cand_to_set_idx)
            
        # --- 3. Heads ---
        
        # Policy: (B, 729, D) -> (B, 729, 2)
        logits = self.head_pi(cand_feat)
        
        # Flatten to action dim (B, 1458)
        # Action encoding: 0..728 (Commit), 729..1457 (Eliminate)
        pi_commit = logits[:, :, 0]
        pi_elim = logits[:, :, 1]
        policy_logits = torch.cat([pi_commit, pi_elim], dim=1)
        
        # Global pooling for State Value & UR
        # Max pooling over candidates captures "strongest features"
        global_feat = torch.max(cand_feat, dim=1)[0] # (B, D)
        
        value = self.head_v(global_feat).squeeze(-1) # (B,)
        ur_score = self.head_ur(global_feat).squeeze(-1) # (B,)
        rank_scores = self.head_rank(cand_feat).squeeze(-1) # (B, 729)
        
        return policy_logits, value, ur_score, rank_scores


class RankMessagePassingLayer(nn.Module):
    def __init__(self, embed_dim: int):
        super().__init__()
        # Projections for message passing
        self.val_cand = nn.Linear(embed_dim, embed_dim)
        self.val_set = nn.Linear(embed_dim, embed_dim)
        
        # Updates
        self.norm_set = nn.LayerNorm(embed_dim)
        self.norm_cand = nn.LayerNorm(embed_dim)
        
        # FFN for Candidates
        self.ff = nn.Sequential(
            nn.Linear(embed_dim, embed_dim * 2),
            nn.ReLU(),
            nn.Linear(embed_dim * 2, embed_dim)
        )
        self.norm_ff = nn.LayerNorm(embed_dim)

    def forward(self, cand_feat, set_feat, cand_to_set_idx):
        """
        cand_feat: (B, 729, D)
        set_feat: (B, 243, D)
        cand_to_set_idx: (729, 3) static mapping
        """
        B, C, D = cand_feat.shape
        
        # --- Phase 1: Candidates -> Sets ---
        # Each Set aggregates messages from the 9 Candidates it contains.
        # We use scatter_add for efficiency.
        
        # Messages from candidates
        cand_msgs = self.val_cand(cand_feat) # (B, 729, D)
        
        # Expand messages for the 3 sets each candidate belongs to
        # (B, 729, D) -> (B, 729, 3, D) -> (B, 2187, D)
        cand_msgs_expanded = cand_msgs.unsqueeze(2).expand(-1, -1, 3, -1).reshape(B, -1, D)
        
        # Flatten indices: (729, 3) -> (2187) -> (B, 2187)
        set_indices = cand_to_set_idx.view(-1).unsqueeze(0).expand(B, -1)
        
        # Aggregate
        set_updates = torch.zeros_like(set_feat)
        # scatter_add_(dim, index, src)
        set_updates.scatter_add_(1, set_indices.unsqueeze(-1).expand(-1, -1, D), cand_msgs_expanded)
        
        # Normalize (mean aggregation): divide by 9 (candidates per set)
        set_updates = set_updates / 9.0
        
        # Update Sets
        set_feat = self.norm_set(set_feat + set_updates)
        
        # --- Phase 2: Sets -> Candidates ---
        # Each Candidate aggregates messages from the 3 Sets it belongs to.
        
        # Gather set features
        # Flatten indices: (B, 2187)
        # Gather from set_feat (B, 243, D) -> (B, 2187, D)
        flat_indices = cand_to_set_idx.view(-1).unsqueeze(0).expand(B, -1)
        gathered_sets = torch.gather(
            set_feat, 
            1, 
            flat_indices.unsqueeze(-1).expand(-1, -1, D)
        )
        
        # Reshape to (B, 729, 3, D)
        gathered_sets = gathered_sets.view(B, 729, 3, D)
        
        # Aggregate (Mean over the 3 sets)
        cand_updates = gathered_sets.mean(dim=2) # (B, 729, D)
        cand_updates = self.val_set(cand_updates)
        
        # Update Candidates
        cand_feat = self.norm_cand(cand_feat + cand_updates)
        
        # --- Phase 3: FFN ---
        cand_feat = self.norm_ff(cand_feat + self.ff(cand_feat))
        
        return cand_feat, set_feat


# Alias for backward compatibility
RodokuPolicyValueNet = RodokuGraphNet
