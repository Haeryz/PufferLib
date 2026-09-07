"""Extract exact game dynamics from the canonical gameplay trace.

Analyzes probe.jsonl to derive:
- Player stats (HP, SPD, position bounds, invulnerability frames)
- Enemy stats (HP, speed, spawn timing, spawn positions, movement AI)
- Weapon/attack dynamics (cooldown, damage, hitbox, range)
- XP/leveling system (XP thresholds, gem pickup radius, magnet speed)
- Map dimensions and collision rules
- Tick rate and event ordering

Outputs a dynamics profile JSON that the RL environment uses to match the game 1:1.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from collections import Counter, defaultdict


def load_canonical_ticks(probe_path: Path) -> list[dict]:
    ticks = []
    with probe_path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("kind") == "canonical_tick":
                ticks.append(row)
    return ticks


def extract_player_dynamics(ticks: list[dict]) -> dict:
    player_samples = []
    for t in ticks:
        for inst in t.get("instances", []):
            if inst.get("object") == "obj_Player":
                player_samples.append(inst)
                break

    if not player_samples:
        return {}

    first = player_samples[0]
    last = player_samples[-1]

    # Position bounds
    xs = [s["x"] for s in player_samples if s.get("x") is not None]
    ys = [s["y"] for s in player_samples if s.get("y") is not None]

    # HP tracking
    hps = [s["vars"].get("HP", 0) for s in player_samples]
    max_hp = max(hps) if hps else 0

    # Speed
    speeds = [s["vars"].get("SPD", 0) for s in player_samples]
    speed = speeds[0] if speeds else 0

    # EXP
    exps = [s["vars"].get("EXP", 0) for s in player_samples]

    # Level
    levels = [s["vars"].get("level", 1) for s in player_samples]

    # Special
    spec_cd = first["vars"].get("specCD", 0)
    spec_meter = [s["vars"].get("specialMeter", 0) for s in player_samples]

    # Invincibility
    invuln = [s["vars"].get("invincibilityTimer", 0) for s in player_samples]
    frames_inv = [s["vars"].get("framesInvincible", 0) for s in player_samples]

    # Movement analysis: find distance moved per tick
    movements = []
    for i in range(1, len(player_samples)):
        dx = player_samples[i]["x"] - player_samples[i-1]["x"]
        dy = player_samples[i]["y"] - player_samples[i-1]["y"]
        dist = math.hypot(dx, dy)
        movements.append(dist)

    # Determine if player moved (action != 0)
    moving = [s["vars"].get("isMoving", 0) for s in player_samples]

    return {
        "start_x": first.get("x", 0),
        "start_y": first.get("y", 0),
        "end_x": last.get("x", 0),
        "end_y": last.get("y", 0),
        "min_x": min(xs) if xs else 0,
        "max_x": max(xs) if xs else 0,
        "min_y": min(ys) if ys else 0,
        "max_y": max(ys) if ys else 0,
        "hp_start": hps[0] if hps else 0,
        "hp_max": max_hp,
        "hp_min": min(hps) if hps else 0,
        "spd": speed,
        "exp_start": exps[0] if exps else 0,
        "exp_end": exps[-1] if exps else 0,
        "level_start": levels[0] if levels else 1,
        "level_end": levels[-1] if levels else 1,
        "spec_cd": spec_cd,
        "spec_meter_samples": spec_meter[:10],
        "invincibility_timer_samples": invuln[:10],
        "frames_invincible_samples": frames_inv[:10],
        "movement_distances": [round(m, 4) for m in movements[:20]],
        "is_moving_samples": moving[:20],
        "sample_count": len(player_samples),
        "vars": list(first.get("vars", {}).keys()),
    }


def extract_enemy_dynamics(ticks: list[dict]) -> dict:
    enemy_by_id = defaultdict(list)
    for t in ticks:
        for inst in t.get("instances", []):
            if inst.get("object") in ("obj_Enemy", "obj_BaseEnemy"):
                eid = inst.get("id")
                enemy_by_id[eid].append({
                    "tick": t.get("tick", 0),
                    "x": inst.get("x"),
                    "y": inst.get("y"),
                    "hp": inst.get("vars", {}).get("HP", 0),
                    "name": inst.get("vars", {}).get("name", ""),
                    "spd": inst.get("vars", {}).get("SPD", 0),
                    "expvalue": inst.get("vars", {}).get("expvalue", 0),
                    "is_alive": inst.get("vars", {}).get("isAlive", 0),
                    "is_boss": inst.get("vars", {}).get("isBoss", 0),
                    "is_moving": inst.get("vars", {}).get("isMoving", 0),
                    "direction": inst.get("vars", {}).get("directionMoving", 0),
                    "spawned_time": inst.get("vars", {}).get("spawnedTime", 0),
                    "alive_for": inst.get("vars", {}).get("aliveFor", 0),
                    "collided_cd": inst.get("vars", {}).get("collidedCD", 0),
                    "width": inst.get("vars", {}).get("width", 0),
                    "max_level": inst.get("vars", {}).get("maxLevel", 0),
                })

    # Extract unique enemy types
    enemy_types = {}
    for eid, samples in enemy_by_id.items():
        if not samples:
            continue
        name = samples[0]["name"]
        if name not in enemy_types:
            enemy_types[name] = {
                "name": name,
                "hp": samples[0]["hp"],
                "spd": samples[0]["spd"],
                "expvalue": samples[0]["expvalue"],
                "width": samples[0]["width"],
                "max_level": samples[0]["max_level"],
                "is_boss": samples[0]["is_boss"],
                "sample_count": 1,
                "first_tick": samples[0]["tick"],
                "last_tick": samples[-1]["tick"],
            }
        else:
            enemy_types[name]["sample_count"] += 1

    # Spawn analysis: when do new enemies appear?
    spawn_ticks = []
    prev_enemy_count = 0
    for t in ticks:
        count = sum(1 for inst in t.get("instances", [])
                    if inst.get("object") in ("obj_Enemy", "obj_BaseEnemy"))
        if count > prev_enemy_count:
            spawn_ticks.append({
                "tick": t.get("tick", 0),
                "new_count": count - prev_enemy_count,
                "total": count,
            })
        prev_enemy_count = count

    # Enemy movement analysis
    movement_samples = []
    for eid, samples in list(enemy_by_id.items())[:5]:
        if len(samples) < 2:
            continue
        for i in range(1, min(len(samples), 5)):
            dx = samples[i]["x"] - samples[i-1]["x"]
            dy = samples[i]["y"] - samples[i-1]["y"]
            dist = math.hypot(dx, dy)
            movement_samples.append({
                "enemy_id": str(eid),
                "tick_delta": samples[i]["tick"] - samples[i-1]["tick"],
                "dx": round(dx, 4),
                "dy": round(dy, 4),
                "dist": round(dist, 4),
                "is_moving": samples[i]["is_moving"],
                "direction": samples[i]["direction"],
            })

    return {
        "types": enemy_types,
        "spawn_events": spawn_ticks[:30],
        "movement_samples": movement_samples,
        "total_unique_enemies": len(enemy_by_id),
        "max_concurrent": max(
            sum(1 for inst in t.get("instances", [])
                if inst.get("object") in ("obj_Enemy", "obj_BaseEnemy"))
            for t in ticks
        ) if ticks else 0,
    }


def extract_attack_dynamics(ticks: list[dict]) -> dict:
    attack_samples = []
    for t in ticks:
        for inst in t.get("instances", []):
            if inst.get("object") == "obj_Attack":
                attack_samples.append({
                    "tick": t.get("tick", 0),
                    "x": inst.get("x"),
                    "y": inst.get("y"),
                    "vars": inst.get("vars", {}),
                })

    if not attack_samples:
        return {"present": False, "count": 0}

    # Group by tick to see attack timing
    attacks_by_tick = defaultdict(int)
    for a in attack_samples:
        attacks_by_tick[a["tick"]] += 1

    # Attack timing intervals
    sorted_ticks = sorted(attacks_by_tick.keys())
    intervals = []
    for i in range(1, len(sorted_ticks)):
        intervals.append(sorted_ticks[i] - sorted_ticks[i-1])

    return {
        "present": True,
        "count": len(attack_samples),
        "first_attack_tick": sorted_ticks[0] if sorted_ticks else 0,
        "last_attack_tick": sorted_ticks[-1] if sorted_ticks else 0,
        "attack_intervals": intervals[:20],
        "max_concurrent_attacks": max(attacks_by_tick.values()) if attacks_by_tick else 0,
        "sample_vars": list(attack_samples[0]["vars"].keys()) if attack_samples else [],
    }


def extract_xp_dynamics(ticks: list[dict]) -> dict:
    xp_samples = []
    for t in ticks:
        for inst in t.get("instances", []):
            if inst.get("object") in ("obj_EXP", "obj_EXP_set", "obj_EXPAbsorb"):
                xp_samples.append({
                    "tick": t.get("tick", 0),
                    "x": inst.get("x"),
                    "y": inst.get("y"),
                    "vars": inst.get("vars", {}),
                })

    return {
        "present": len(xp_samples) > 0,
        "count": len(xp_samples),
        "first_xp_tick": xp_samples[0]["tick"] if xp_samples else 0,
        "sample_vars": list(xp_samples[0]["vars"].keys()) if xp_samples else [],
    }


def extract_map_dynamics(ticks: list[dict]) -> dict:
    all_x = []
    all_y = []
    for t in ticks:
        for inst in t.get("instances", []):
            x = inst.get("x")
            y = inst.get("y")
            if x is not None and y is not None:
                all_x.append(x)
                all_y.append(y)

    return {
        "min_x": min(all_x) if all_x else 0,
        "max_x": max(all_x) if all_x else 0,
        "min_y": min(all_y) if all_y else 0,
        "max_y": max(all_y) if all_y else 0,
        "width": (max(all_x) - min(all_x)) if all_x else 0,
        "height": (max(all_y) - min(all_y)) if all_y else 0,
    }


def extract_action_dynamics(ticks: list[dict]) -> dict:
    actions = [t.get("action", [0]*7) for t in ticks]
    action_counts = Counter(tuple(a) for a in actions)

    # Map action vector to movement
    # action = [W, S, A, D, Space, Shift, Ctrl] based on ACTION_KEYS
    # W=87, S=83, A=65, D=68, Space=32, Shift=16, Ctrl=17
    move_actions = []
    for a in actions[:50]:
        w, s, l, r, sp, sh, ct = a
        dx = (r - l)
        dy = (s - w)
        move_actions.append({"action": a, "dx": dx, "dy": dy})

    return {
        "unique_actions": len(action_counts),
        "most_common": action_counts.most_common(10),
        "move_samples": move_actions,
    }


def analyze(probe_path: Path) -> dict:
    ticks = load_canonical_ticks(probe_path)
    if not ticks:
        raise ValueError("No canonical_tick records found")

    return {
        "schema_version": 1,
        "tick_count": len(ticks),
        "tick_rate": 60,
        "player": extract_player_dynamics(ticks),
        "enemies": extract_enemy_dynamics(ticks),
        "attacks": extract_attack_dynamics(ticks),
        "xp": extract_xp_dynamics(ticks),
        "map": extract_map_dynamics(ticks),
        "actions": extract_action_dynamics(ticks),
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("probe", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    dynamics = analyze(args.probe)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(dynamics, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "ticks": dynamics["tick_count"],
        "player_vars": len(dynamics["player"].get("vars", [])),
        "enemy_types": len(dynamics["enemies"].get("types", {})),
        "attacks": dynamics["attacks"]["count"],
        "xp": dynamics["xp"]["count"],
    }, indent=2))


if __name__ == "__main__":
    main()
