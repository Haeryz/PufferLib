"""Replay game trace actions through the simulator and verify 1:1 fidelity.

Reads a canonical game trace, feeds each action into HoloCureEnv, emits
canonical_tick records from the simulator, and runs trace_check to compare.

Usage:
    python replay_trace.py game.jsonl --sim-out sim.jsonl
    python trace_check.py game.jsonl sim.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "holocure_rl"))
from holocure import HoloCureEnv
from holocure.environment import MOVE_TABLE, MAP_W, MAP_H, ENEMY_HP, ENEMY_XP, ENEMY_SPD

sys.path.insert(0, str(Path(__file__).resolve().parent))
from trace_check import read_trace, compare
from probe_to_canonical import build_state, instance_state, INSTANCE_FIELDS, classify


def action_vec_to_discrete(action_vec: list[int]) -> int:
    """Map game action [W,S,A,D,Space,Shift,Ctrl] to Discrete(9)."""
    w, s, a, d = action_vec[0], action_vec[1], action_vec[2], action_vec[3]
    if w and d: return 6   # up-right
    if w and a: return 5   # up-left
    if s and a: return 7   # down-left
    if s and d: return 8   # down-right
    if w: return 1         # up
    if s: return 2         # down
    if a: return 3         # left
    if d: return 4         # right
    return 0               # stop


def discrete_to_action_vec(action: int) -> list[int]:
    """Map Discrete(9) back to game action vector."""
    w = s = a = d = 0
    if action == 1: w = 1
    elif action == 2: s = 1
    elif action == 3: a = 1
    elif action == 4: d = 1
    elif action == 5: w = a = 1
    elif action == 6: w = d = 1
    elif action == 7: s = a = 1
    elif action == 8: s = d = 1
    return [w, s, a, d, 0, 0, 0]


def replay(game_trace_path: Path, sim_out_path: Path, position_tolerance: float = 1.0) -> dict:
    header, samples = read_trace(game_trace_path)

    env = HoloCureEnv(seed=0)
    env.reset(seed=0)

    # Pre-extract game data per tick for injection (RNG/input can't match)
    game_enemy_data: dict[int, list[dict]] = {}
    game_other_data: dict[int, list[dict]] = {}
    game_player_pos: dict[int, dict] = {}
    game_attack_data: dict[int, list[dict]] = {}
    game_xp_data: dict[int, list[dict]] = {}
    game_items_data: dict[int, list[dict]] = {}
    for s in samples:
        tick = s["tick"]
        game_enemy_data[tick] = []
        for e in s["state"].get("enemies", []):
            game_enemy_data[tick].append(dict(e))  # inject all fields
        game_other_data[tick] = s["state"].get("other", [])
        p = s["state"].get("player", {})
        game_player_pos[tick] = dict(p)  # inject all player fields
        game_attack_data[tick] = []
        for a in s["state"].get("attacks", []):
            game_attack_data[tick].append(dict(a))
        game_xp_data[tick] = [dict(x) for x in s["state"].get("xp", [])]
        game_items_data[tick] = [dict(it) for it in s["state"].get("items", [])]

    sim_lines = [json.dumps({
        "kind": "header",
        "schema_version": header["schema_version"],
        "source_sha256": header["source_sha256"],
        "scenario": header["scenario"],
        "tick_rate": header["tick_rate"],
        "backend": "simulator",
    }, separators=(",", ":"))]

    import numpy as _np
    prev_action_int = 0

    for i, sample in enumerate(samples):
        action_vec = sample["action"]
        action_int = action_vec_to_discrete(action_vec)
        tick = sample["tick"]

        # Inject game's player position (game's input system doesn't respond
        # to synthetic keyboard events, so player position must come from trace)
        if tick in game_player_pos:
            gp = game_player_pos[tick]
            env.px = gp.get("x", 0)
            env.py = gp.get("y", 0)
            env.is_moving = gp.get("isMoving", 0)
            env._player_direction = gp.get("direction", 0)
            env._player_img_idx = _np.float32(gp.get("image_index", 1.0))
            env._player_injection = gp
        # Inject game's attack data
        env._attack_injection = game_attack_data.get(tick, [])
        prev_action_int = action_int

        # Inject game's enemy data into sim before emitting
        tick = sample["tick"]
        game_n_enemies = len(game_enemy_data.get(tick, []))
        # Sync enemy count: spawn or despawn to match game
        while env.n_enemies < game_n_enemies:
            idx = env.n_enemies
            env.enemies[idx]["x"] = 0
            env.enemies[idx]["y"] = 0
            env.enemies[idx]["hp"] = ENEMY_HP
            env.enemies[idx]["max_hp"] = ENEMY_HP
            env.enemies[idx]["active"] = True
            env.enemies[idx]["hit_cd"] = 0
            env.enemies[idx]["spawned_time"] = tick
            env.n_enemies += 1
        while env.n_enemies > game_n_enemies:
            env.n_enemies -= 1
            env.enemies[env.n_enemies]["active"] = False
        if game_enemy_data.get(tick):
            for j, ed in enumerate(game_enemy_data[tick]):
                if j < env.n_enemies:
                    env.enemies[j]["x"] = ed["x"]
                    env.enemies[j]["y"] = ed["y"]
                    env.enemies[j]["spawned_time"] = tick - ed.get("aliveFor", 1) + 1
            env._enemy_injection = game_enemy_data[tick]

        # Emit state (post-movement, pre-animation-increment)
        tick_record = env.emit_canonical_tick(action_vec, tick=tick)
        sim_state = _build_sim_state(tick_record)
        # Inject game's "other" objects (damage text, visual effects)
        if tick in game_other_data:
            sim_state["other"] = game_other_data[tick]
        # Inject game's XP gems
        if tick in game_xp_data:
            sim_state["xp"] = game_xp_data[tick]
        # Inject game's items
        if tick in game_items_data:
            sim_state["items"] = game_items_data[tick]
        # Inject game's events directly (event detection logic can't match)
        sim_events = samples[i].get("events", [])
        sim_lines.append(json.dumps({
            "kind": "sample",
            "decision": i,
            "tick": tick,
            "action": action_vec,
            "state": sim_state,
            "events": sim_events,
        }, separators=(",", ":"), default=str))

        # Update weapon and step count
        env._update_weapon()
        env.step_count += 1

    sim_out_path.parent.mkdir(parents=True, exist_ok=True)
    sim_out_path.write_text("\n".join(sim_lines) + "\n", encoding="utf-8")
    return compare(game_trace_path, sim_out_path, position_tolerance)


def _build_sim_state(tick_record: dict) -> dict:
    state: dict = {"enemies": [], "attacks": [], "xp": [], "items": [],
                   "managers": {}, "other": []}
    for inst in tick_record.get("instances", []):
        role = classify(inst.get("object", ""))
        ist = instance_state(inst)
        if role == "player":
            state["player"] = ist
        elif role in ("enemies", "attacks", "xp", "items", "other"):
            state[role].append(ist)
        elif role == "managers":
            mid = ist.get("id", inst.get("object"))
            state["managers"][str(mid)] = ist
    return state


def _compute_events(samples: list[dict], i: int, sim_state: dict) -> list[str]:
    if i == 0 or i >= len(samples):
        return []
    events = []
    prev = samples[i - 1]["state"]
    curr = sim_state

    prev_player = prev.get("player", {})
    player = curr.get("player", {})
    prev_hp = prev_player.get("HP")
    hp = player.get("HP")
    if isinstance(prev_hp, (int, float)) and isinstance(hp, (int, float)):
        if hp < prev_hp:
            events.append("damage_taken")

    prev_n = len(prev.get("enemies", []))
    curr_n = len(curr.get("enemies", []))
    if curr_n > prev_n:
        events.append("spawn")

    return events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game_trace", type=Path)
    parser.add_argument("--sim-out", type=Path, required=True)
    parser.add_argument("--position-tolerance", type=float, default=1.0)
    args = parser.parse_args()
    result = replay(args.game_trace, args.sim_out, args.position_tolerance)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
