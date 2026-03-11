from __future__ import annotations

import random
import time
import json
from typing import List, Tuple, Dict, Optional, Any
from pathlib import Path

from .solver_core import (
    SudokuState, 
    parse_puzzle_81, 
    idx_of, 
    rc_of, 
    box_of, 
    _has_any_solution_referee, 
    SolveResult,
    _quick_consistent,
    has_conflict
)
from .runtime_paths import ensure_data_dir
from .puzzle_bank import get_puzzle_bank, SEED_PUZZLES


def _is_valid_ur_rect(r1, c1, r2, c2) -> bool:
    """Check if 4 corners form a valid Unique Rectangle geometry (2 blocks)"""
    # Same band (r1//3 == r2//3) -> must be different stack (c1//3 != c2//3)
    same_band = (r1 // 3) == (r2 // 3)
    same_stack = (c1 // 3) == (c2 // 3)
    # Valid UR must span exactly 2 boxes
    # Case 1: Same band, diff stack -> 2 boxes
    # Case 2: Diff band, same stack -> 2 boxes
    # Case 3: Same band, same stack -> 1 box (Invalid for UR)
    # Case 4: Diff band, diff stack -> 4 boxes (Invalid for UR)
    return same_band != same_stack

def find_potential_ul_traps(st: SudokuState) -> List[Dict[str, Any]]:
    """
    Search for potential Unique Loop (UL) traps (Length 6, 8, etc.).
    Strategy:
    1. Find bivalue cells (cells with exactly 2 candidates).
    2. Build a graph of these cells (edges if they share a unit and candidates).
    3. Look for paths that almost form a loop, with one 'trap' cell closing it.
    """
    traps = []
    
    # 1. Identify Bivalue Cells & Candidates
    bivalue_cells = []
    cell_cands = {}
    
    for i in range(81):
        if st.grid[i] != 0: continue
        mask = st.allowed_mask(i)
        cnt = bin(mask).count('1')
        if cnt == 2:
            cands = []
            for d in range(1, 10):
                if mask & (1 << (d - 1)):
                    cands.append(d)
            bivalue_cells.append(i)
            cell_cands[i] = set(cands)
    
    # 2. Search for loops
    # DFS from each bivalue cell to find a path
    # We want a path A-B-C-D-E... where each link shares the bivalue pair.
    # Actually ULs often involve the SAME pair {u, v} across the whole loop (simplest Type 1).
    # Let's focus on "Same Pair Loops" first.
    
    # Group cells by pair {u, v}
    pair_groups = {}
    for i in bivalue_cells:
        pair = tuple(sorted(list(cell_cands[i])))
        if pair not in pair_groups:
            pair_groups[pair] = []
        pair_groups[pair].append(i)
        
    for pair, cells in pair_groups.items():
        if len(cells) < 4: continue # Need at least 4 for a loop (rect is 4, loop is 6+)
        
        # Build adjacency for this group
        adj = {i: [] for i in cells}
        for i in range(len(cells)):
            for j in range(i+1, len(cells)):
                u, v = cells[i], cells[j]
                ru, cu = rc_of(u)
                rv, cv = rc_of(v)
                bu = box_of(ru, cu)
                bv = box_of(rv, cv)
                
                # Connect if share row, col, or box
                if ru == rv or cu == cv or bu == bv:
                    adj[u].append(v)
                    adj[v].append(u)
                    
        # Find paths of length 5 (for 6-cell loop) or 3 (for 4-cell rect, covered by UR logic)
        # We want to find a path A-...-Z where A and Z are connected to a 'Trap' cell.
        # The 'Trap' cell is NOT in 'cells' (because it's not bivalue yet, or has extra candidates).
        
        # Simplified: Look for cycles WITHIN the bivalue cells?
        # If a cycle exists, the puzzle is invalid (multiple solutions).
        # We want a "Trap": a cell that, if filled with X, CLOSES the cycle.
        
        # So we look for an OPEN chain of bivalue cells: A-B-C-D-E
        # And a Trap Cell T such that:
        # T sees A and T sees E.
        # T allows candidates {u, v}.
        # If we remove extra candidates from T to make it {u, v}, it becomes part of the loop.
        # OR: If we fill a specific digit in T, it forces the loop into a deadly state.
        
        # Correct UL Logic:
        # If we have a loop of bivalue cells {u, v} except for one cell (the trap),
        # which has {u, v, +others}.
        # If we assume the trap is u or v, we get a deadly loop.
        # Therefore, the trap MUST NOT be u or v.
        # The "Trap Move" is playing u or v in that cell.
        
        # Algorithm:
        # 1. Find chains of length N-1 (N=6, 8).
        # 2. Check endpoints.
        
        visited = set()
        
        def get_chains(start_node, length_limit):
            # DFS to find chains
            stack = [(start_node, [start_node])]
            chains = []
            while stack:
                curr, path = stack.pop()
                if len(path) >= length_limit:
                    chains.append(path)
                    continue
                
                for nxt in adj[curr]:
                    if nxt not in path:
                        stack.append((nxt, path + [nxt]))
            return chains
            
        # Search for chains of length 5 (for 6-loop)
        for start_node in cells:
            chains_5 = get_chains(start_node, 5) # 5 nodes -> need 1 more to close 6-loop
            
            for chain in chains_5:
                start, end = chain[0], chain[-1]
                
                # Check neighbors of start and end to find a common "Trap"
                # The Trap must:
                # 1. Be empty (in st.grid)
                # 2. Not be in the chain
                # 3. Share a unit with start AND end
                # 4. Have candidates {u, v} allowed
                # 5. Have AT LEAST one extra candidate (otherwise it's just a valid loop/puzzle invalid)
                #    OR: user definition: "different fillings... rest of board same"
                #    Actually, if it's a trap, playing u or v creates the Deadly Pattern.
                
                # Iterate all cells to find T? No, iterate peers of start.
                r_s, c_s = rc_of(start)
                b_s = box_of(r_s, c_s)
                
                peers_s = set()
                for k in range(9):
                    peers_s.add(idx_of(r_s, k))
                    peers_s.add(idx_of(k, c_s))
                    
                # Box peers
                br, bc = (b_s // 3) * 3, (b_s % 3) * 3
                for dr in range(3):
                    for dc in range(3):
                        peers_s.add(idx_of(br + dr, bc + dc))
                        
                for t_idx in peers_s:
                    if t_idx in chain: continue
                    if st.grid[t_idx] != 0: continue
                    
                    # Check if T is neighbor of end
                    r_t, c_t = rc_of(t_idx)
                    b_t = box_of(r_t, c_t)
                    r_e, c_e = rc_of(end)
                    b_e = box_of(r_e, c_e)
                    
                    is_neighbor_end = (r_t == r_e) or (c_t == c_e) or (b_t == b_e)
                    if not is_neighbor_end: continue
                    
                    # T is common neighbor. Check candidates.
                    mask_t = st.allowed_mask(t_idx)
                    u, v = pair
                    
                    has_u = (mask_t >> (u-1)) & 1
                    has_v = (mask_t >> (v-1)) & 1
                    
                    if has_u and has_v:
                        # Candidate Trap found!
                        # We report both u and v as traps.
                        if has_u:
                            traps.append({
                                "idx": t_idx, 
                                "d": u,
                                "type": "UL6",
                                "pair": list(pair),
                                "chain": chain
                            })
                        if has_v:
                            traps.append({
                                "idx": t_idx, 
                                "d": v,
                                "type": "UL6",
                                "pair": list(pair),
                                "chain": chain
                            })

    return traps

def find_potential_ur_traps(st: SudokuState) -> List[Dict[str, Any]]:
    """
    Search for potential UR Deadly Patterns.
    Returns a list of 'trap' actions: {idx, d, type='UR1'}
    that WOULD complete a deadly pattern if taken.
    """
    traps = []
    
    # Iterate all 2x2 rectangles
    for r1 in range(8):
        for r2 in range(r1 + 1, 9):
            for c1 in range(8):
                for c2 in range(c1 + 1, 9):
                    if not _is_valid_ur_rect(r1, c1, r2, c2):
                        continue
                        
                    idxs = [idx_of(r1, c1), idx_of(r1, c2), idx_of(r2, c1), idx_of(r2, c2)]
                    
                    # We are looking for a state where:
                    # 3 cells are already filled with [a, b] (or candidates reduced to [a,b])
                    # 1 cell is empty and HAS candidates [a, b] (plus maybe others)
                    # AND taking action 'a' or 'b' on that empty cell would create the deadly pattern.
                    
                    # For simplicity in generation, let's look for:
                    # 3 cells are filled with values from {u, v}
                    # 1 cell is empty
                    
                    vals = []
                    filled_indices = []
                    empty_indices = []
                    
                    for idx in idxs:
                        v = st.grid[idx]
                        if v != 0:
                            vals.append(v)
                            filled_indices.append(idx)
                        else:
                            empty_indices.append(idx)
                            
                    if len(filled_indices) != 3 or len(empty_indices) != 1:
                        continue
                        
                    # Check if the 3 filled values are composed of exactly 2 digits {u, v}
                    # e.g. [5, 8, 5] -> {5, 8}
                    unique_vals = set(vals)
                    if len(unique_vals) != 2:
                        continue
                        
                    u, v = list(unique_vals)
                    
                    # The empty cell is the trap location
                    trap_idx = empty_indices[0]
                    
                    # Check if the empty cell ALLOWS u and v
                    allowed = st.allowed_mask(trap_idx)
                    
                    # If we fill 'u', do we complete the pattern?
                    # The pattern is:
                    # r1c1=u, r1c2=v
                    # r2c1=v, r2c2=u (diagonal symmetry) or similar.
                    # Actually, a Deadly Pattern just needs the 4 cells to contain {u, v}
                    # such that swapping u<->v in these 4 cells is valid.
                    # This happens if the 'floor' is set.
                    
                    # Simplified check: If we put 'u' or 'v' in the last cell, 
                    # do we have 2 u's and 2 v's in the rectangle?
                    # And are they arranged validly (no row/col conflict)?
                    # Since the grid is currently valid (assumed), we just need to check
                    # if placing u or v is locally valid.
                    
                    if allowed & (1 << (u - 1)):
                        # Candidate Trap: u
                        traps.append({
                            "idx": trap_idx,
                            "d": u,
                            "pair": [u, v],
                            "rect": idxs
                        })
                        
                    if allowed & (1 << (v - 1)):
                        # Candidate Trap: v
                        traps.append({
                            "idx": trap_idx,
                            "d": v,
                            "pair": [u, v],
                            "rect": idxs
                        })
                        
    return traps

def verify_non_uniqueness(st: SudokuState, idx: int, d: int) -> bool:
    """
    Oracle: Check if committing (idx, d) leads to a state with MULTIPLE solutions.
    Returns True if multiple solutions exist (Deadly!).
    Returns False if 0 or 1 solution.
    """
    # 1. Commit the move
    # We work on a copy
    grid_next = st.grid[:]
    grid_next[idx] = d
    # Note: We don't strictly need to update forbidden/propagation for the solver 
    # if the solver re-computes allowed masks, but let's do minimal consistency check.
    if has_conflict(grid_next):
        return False # Invalid move, not a trap (just wrong)
        
    st_next = SudokuState(grid_next, st.given)
    
    # 2. Use solver to count solutions
    # _has_any_solution_referee returns True/False.
    # We need something that finds AT LEAST 2 solutions.
    # Let's modify the referee logic slightly or use a specialized one.
    
    # Custom DFS to find 2 solutions
    solutions = 0
    
    # Reuse the fast solver structure from solver_core
    # But we need to break early if solutions >= 2
    
    # We can use _has_any_solution_referee on the state.
    # If it has a solution, let's say S1.
    # Then we try to find a DIFFERENT solution S2.
    
    # To avoid writing a full DLX solver here, let's assume specific UR logic:
    # If it IS a UR pattern (checked by find_potential_ur_traps), 
    # and the REST of the board has a solution, 
    # then swapping the UR digits creates a second solution.
    # SO: checking "is there ANY solution" after filling the trap is often enough 
    # IF we trust the UR geometry implies non-uniqueness.
    
    # However, to be rigorous (and create high quality data):
    # We should prove that the board is solvable with THIS move, 
    # AND that the board allows the 'swapped' UR state which is also valid.
    
    # Actually, simpler:
    # A move is a "UR Trap" if:
    # 1. It completes a UR pattern {u, v} on cells C1..C4
    # 2. The resulting board is Solvable (at least 1 solution)
    # 3. AND the alternative UR configuration is ALSO compatible with the *external* constraints.
    
    # Let's implement a "Count Solutions (Max 2)" solver.
    
    return _count_solutions(st_next, limit=2) == 2

def _count_solutions(st: SudokuState, limit: int = 2) -> int:
    # Simple backtracking solver that stops at 'limit' solutions
    # Re-implements basic DFS from solver_core but with counter
    
    grid = st.grid[:]
    
    # Pre-check consistency
    if has_conflict(grid):
        return 0
        
    # Precompute constraints
    row_used = [0]*9
    col_used = [0]*9
    box_used = [0]*9
    
    empty_indices = []
    
    for i in range(81):
        v = grid[i]
        if v != 0:
            bit = 1 << (v - 1)
            r, c = rc_of(i)
            b = box_of(r, c)
            row_used[r] |= bit
            col_used[c] |= bit
            box_used[b] |= bit
        else:
            empty_indices.append(i)
            
    # Sort empty indices by heuristic (MRV - Minimum Remaining Values) could be faster,
    # but for validation linear scan might suffice if N is small.
    # Let's do a quick pre-sort by allowed count.
    
    def get_allowed(idx):
        r, c = rc_of(idx)
        b = box_of(r, c)
        return 0x1FF & ~(row_used[r] | col_used[c] | box_used[b])
        
    # Sort empties by constraint
    empty_indices.sort(key=lambda i: bin(get_allowed(i)).count('1'))
    
    count = 0
    
    def solve(k):
        nonlocal count
        if k == len(empty_indices):
            count += 1
            return
            
        idx = empty_indices[k]
        r, c = rc_of(idx)
        b = box_of(r, c)
        
        allowed = 0x1FF & ~(row_used[r] | col_used[c] | box_used[b])
        
        while allowed:
            # Pick lowest bit
            lsb = allowed & -allowed
            allowed ^= lsb
            val = lsb.bit_length() # 1-based
            
            # Commit
            row_used[r] |= lsb
            col_used[c] |= lsb
            box_used[b] |= lsb
            grid[idx] = val # debug only
            
            solve(k + 1)
            
            # Backtrack
            row_used[r] &= ~lsb
            col_used[c] &= ~lsb
            box_used[b] &= ~lsb
            grid[idx] = 0
            
            if count >= limit:
                return

    solve(0)
    return count

def generate_ur_dataset(count: int = 1000):
    """
    Main generator loop.
    1. Load puzzle bank
    2. Solve puzzles partially to create intermediate states? 
       No, UR traps can appear in fully generated puzzles.
       Better strategy: 
       - Take a solved valid puzzle.
       - Identify a UR rectangle in the solution.
       - Clear one of the 4 cells.
       - The correct move is the one from the solution.
       - But wait, if we start from a valid unique puzzle, clearing a cell makes it under-specified?
       
       Reverse Logic:
       - UR Trap logic relies on the puzzle INITIALLY having a unique solution.
       - If the player fills a number that FORCES the board into a state with 2 solutions (local ambiguity + rest of board solved), that's the trap.
       
       Recipe:
       1. Take a solved grid G (Solution).
       2. Find a UR structure in G (4 cells having {u, v} in rectangle).
       3. Create a puzzle P from G by masking cells, ensuring P has Unique Solution (standard generator).
          - AND ensure the 4 UR cells are NOT all given.
       4. Solve P partially until we reach a state S where:
          - 3 of the UR cells are determined (or given).
          - 1 is empty.
          - Candidates for empty cell include u (bad) and v (bad)?
          
       Actually, standard UR elimination works because:
       "If I place X here, it creates a Deadly Pattern. Since the puzzle IS unique, X must be false."
       
       So the "Negative Sample" is:
       State: A partial grid where a UR pattern is forming.
       Action: Placing the digit that completes the deadly pattern.
       Label: BAD (0.0).
       
       Simplest Generator:
       1. Generate a valid full grid (Solved).
       2. Find a UR rectangle in it (values u, v).
       3. "Unsolve" the grid: keep the UR cells filled, remove others randomly, 
          BUT ensure the puzzle remains uniquely solvable if we fix the UR cells?
          
       Let's go with the `find_potential_ur_traps` approach on Random Semi-Solved States.
       1. Get valid puzzles.
       2. Use `solver_core` to solve them, collecting snapshots (states).
       3. For each state, check `find_potential_ur_traps`.
       4. If a trap candidate is found, verify with `verify_non_uniqueness`.
       5. If verified, save.
    """
    
    bank = get_puzzle_bank()
    out_path = ensure_data_dir() / "_ur_samples.jsonl"
    
    print(f"Generating UR samples to {out_path}...")
    
    generated = 0
    with open(out_path, "a", encoding="utf-8") as f:
        for puzzle_str in bank:
            if generated >= count:
                break
                
            # 1. Solve to get trajectory
            res = SolveResult("unknown", [], [])
            try:
                # We use logic solve to generate realistic intermediate states
                # We need a solver that records snapshots
                # Use solve_with_rank but lightly
                from .solver_core import solve_with_rank
                res = solve_with_rank(puzzle_str, max_steps=100, rank_time_budget_ms=100)
            except Exception:
                continue
                
            if res.status not in ("solved", "stuck"):
                continue
                
            # 2. Iterate snapshots
            for snap_str in res.snapshots:
                if generated >= count:
                    break
                    
                # Parse snapshot
                if "|" not in snap_str: continue
                digits, _ = snap_str.split("|")
                grid = [int(c) for c in digits]
                # Reconstruct state (approximate given)
                # Ideally we track 'given', but for UR trap check, we treat filled as filled.
                st = SudokuState(grid, [False]*81) 
                
            # 3. Look for traps
            traps = find_potential_ur_traps(st)
            
            # Add UL traps
            ul_traps = find_potential_ul_traps(st)
            if ul_traps:
                traps.extend(ul_traps)
                print(f"DEBUG: Found {len(ul_traps)} UL traps!")
            
            if len(traps) > 0:
                print(f"DEBUG: Found {len(traps)} potential traps in snapshot.")
            
            for trap in traps:
                    idx = trap["idx"]
                    d = trap["d"]
                    
                    # 4. Verify (Expensive step)
                    # Does filling this digit create >1 solution?
                    # Note: We need to respect the ORIGINAL puzzle constraints (givens).
                    # But here we only have the current grid.
                    # The `verify_non_uniqueness` checks if the CURRENT grid leads to multiple solutions.
                    # This is exactly what the "Global Uniqueness Sensor" should predict:
                    # "Is the current state collapsing into ambiguity?"
                    
                    if verify_non_uniqueness(st, idx, d):
                        # FOUND A TRAP!
                        # Save sample
                        row = {
                            "state_key": snap_str,
                            "action_idx": idx,
                            "action_d": d,
                            "ur_label": 0.0, # BAD
                            "meta": {
                                "type": "UR1",
                                "pair": trap["pair"],
                                "rect": trap["rect"]
                            }
                        }
                        f.write(json.dumps(row) + "\n")
                        f.flush()
                        generated += 1
                        print(f"UR Sample #{generated}: {trap}")
                        if generated >= count:
                            break

if __name__ == "__main__":
    generate_ur_dataset(200)
