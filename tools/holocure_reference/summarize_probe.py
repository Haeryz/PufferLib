"""Summarize a finished raw probe without treating it as parity evidence."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from probe_to_canonical import build_state, compute_events


def summarize(path):
    counts, deltas = Counter(), Counter()
    players, hp, exp = set(), [], []
    previous = None
    tick_count = 0
    max_enemies = 0
    omitted = set()
    first_player = None
    first_delta_ticks = {}
    enemy_hp_losses = Counter()
    player_hp_losses = Counter()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for number, line in enumerate(stream, 1):
            digest.update(line)
            row = json.loads(line)
            counts[row.get("kind")] += 1
            if row.get("kind") != "canonical_tick":
                continue
            if row["tick"] != tick_count:
                raise ValueError(f"Nonconsecutive gameplay tick on line {number}")
            tick_count += 1
            state = build_state(row)
            if previous:
                changes = compute_events(previous, state)
                deltas.update(changes)
                for change in changes:
                    first_delta_ticks.setdefault(change, row["tick"])
                old_enemies = {e["id"]: e for e in previous["enemies"]}
                for enemy in state["enemies"]:
                    before_hp = old_enemies.get(enemy["id"], {}).get("HP")
                    after_hp = enemy.get("HP")
                    if isinstance(before_hp, (int, float)) and isinstance(after_hp, (int, float)) and before_hp > after_hp:
                        enemy_hp_losses[str(before_hp - after_hp)] += 1
                before_hp = previous.get("player", {}).get("HP")
                after_hp = state.get("player", {}).get("HP")
                if isinstance(before_hp, (int, float)) and isinstance(after_hp, (int, float)) and before_hp > after_hp:
                    player_hp_losses[str(before_hp - after_hp)] += 1
            previous = state
            max_enemies = max(max_enemies, len(state["enemies"]))
            for instance in row["instances"]:
                omitted.update(f'{instance["object"]}.{name}' for name in instance.get("omitted_members", []))
            player = state.get("player", {})
            if first_player is None:
                first_player = player
            players.add(player.get("id"))
            if "HP" in player:
                hp.append(player["HP"])
            if "EXP" in player:
                exp.append(player["EXP"])
    return {"status": "discovery_only; no parity claim", "probe_sha256": digest.hexdigest(),
            "record_counts": dict(counts), "gameplay_ticks": tick_count,
            "player_ids": sorted(players), "max_enemies": max_enemies,
            "hp_range": [min(hp), max(hp)] if hp else None,
            "exp_range": [min(exp), max(exp)] if exp else None,
            "observed_state_deltas": dict(deltas), "omitted_members": sorted(omitted),
            "first_delta_ticks": first_delta_ticks,
            "observed_enemy_hp_losses": dict(enemy_hp_losses),
            "observed_player_hp_losses": dict(player_hp_losses),
            "initial_player": first_player}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("probe", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    result = summarize(args.probe)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("initial_player", "omitted_members")}, indent=2))
