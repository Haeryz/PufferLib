"""Convert a probe.jsonl discovery trace into a canonical gameplay trace.

The canonical format is what trace_check.py validates:
  header  = {schema_version, source_sha256, scenario, tick_rate, backend}
  sample  = {decision, tick, action, state, events}

State is partitioned by object role (player/enemies/attacks/xp/items/manager).
Events are derived from per-tick state diffs (hit, kill, spawn, damage, level_up, pickup).
Discovery-only records (probe_header, event_discovered, heartbeat, catalog_snapshot,
global_data, global_names, probe_command, object_step) are skipped — they cannot
establish gameplay fidelity on their own.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


PLAYER_ROLES = {"obj_Player", "TEST_PLAYER", "obj_PlayerPlatformer"}
ENEMY_ROLES = {"obj_Enemy", "obj_BaseEnemy", "obj_EnemyDead"}
ATTACK_ROLES = {"obj_Attack", "obj_cautionattack", "obj_FightPitAttack"}
XP_ROLES = {"obj_EXP", "obj_EXP_set", "obj_EXPAbsorb"}
ITEM_ROLES = {"obj_ItemCrate"}
MANAGER_ROLES = {"obj_StageManager", "obj_PlayerManager", "obj_MobManager",
                 "obj_FandomManager", "obj_InputManager", "obj_AttackController",
                 "obj_EnemySpawner", "obj_EnemySpawn"}

INSTANCE_FIELDS = ("object", "id", "x", "y", "sprite_index", "image_index",
                   "image_xscale", "image_yscale", "image_angle", "image_alpha",
                   "speed", "direction", "visible")


def classify(object_name: str) -> str:
    if object_name in PLAYER_ROLES:
        return "player"
    if object_name in ENEMY_ROLES:
        return "enemies"
    if object_name in ATTACK_ROLES:
        return "attacks"
    if object_name in XP_ROLES:
        return "xp"
    if object_name in ITEM_ROLES:
        return "items"
    if object_name in MANAGER_ROLES:
        return "managers"
    return "other"


def instance_state(inst: dict) -> dict:
    result = {k: inst.get(k) for k in INSTANCE_FIELDS if k in inst}
    result.update(inst.get("vars", {}))
    return result


def build_state(canonical_tick: dict) -> dict:
    state: dict = {"enemies": [], "attacks": [], "xp": [], "items": [],
                   "managers": {}, "other": []}
    for inst in canonical_tick.get("instances", []):
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


def instance_key(inst: dict) -> str:
    return f'{inst.get("object")}:{inst.get("id")}'


def compute_events(prev_state: dict, state: dict) -> list[str]:
    events: list[str] = []

    prev_player = prev_state.get("player")
    player = state.get("player")
    if prev_player and player:
        prev_hp = prev_player.get("hp")
        hp = player.get("hp")
        if isinstance(prev_hp, (int, float)) and isinstance(hp, (int, float)):
            if hp < prev_hp:
                events.append("damage_taken")
        prev_level = prev_player.get("level")
        level = player.get("level")
        if isinstance(prev_level, (int, float)) and isinstance(level, (int, float)):
            if level > prev_level:
                events.append("level_up")
        prev_xp = prev_player.get("xp")
        xp = player.get("xp")
        if isinstance(prev_xp, (int, float)) and isinstance(xp, (int, float)):
            if xp > prev_xp:
                events.append("xp_gain")

    prev_enemies = {instance_key(e): e for e in prev_state.get("enemies", [])}
    enemies = {instance_key(e): e for e in state.get("enemies", [])}
    for key in prev_enemies:
        if key not in enemies:
            events.append("kill")
    for key in enemies:
        if key not in prev_enemies:
            events.append("spawn")
        else:
            prev_hp = prev_enemies[key].get("hp")
            hp = enemies[key].get("hp")
            if isinstance(prev_hp, (int, float)) and isinstance(hp, (int, float)):
                if hp < prev_hp:
                    events.append("hit")

    prev_attacks = {instance_key(a): a for a in prev_state.get("attacks", [])}
    attacks = {instance_key(a): a for a in state.get("attacks", [])}
    for key in attacks:
        if key not in prev_attacks:
            events.append("attack_created")

    prev_xp = {instance_key(x): x for x in prev_state.get("xp", [])}
    xp = {instance_key(x): x for x in state.get("xp", [])}
    for key in prev_xp:
        if key not in xp:
            events.append("xp_collected")

    return events


def convert(probe_path: Path, manifest: dict, scenario: str) -> tuple[dict, list[dict]]:
    source_sha = "0" * 64
    files = manifest.get("files", [])
    if files:
        for f in files:
            if f.get("name") == "HoloCure.exe":
                source_sha = f.get("sha256", source_sha)
                break
        else:
            source_sha = files[0].get("sha256", source_sha)

    tick_rate = 60
    samples: list[dict] = []
    prev_state: dict = {}
    started = False

    with probe_path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = row.get("kind")
            if kind == "gameplay_start":
                started = True
                if isinstance(row.get("tick_rate"), (int, float)):
                    tick_rate = int(row["tick_rate"])
                prev_state = {}
                continue
            if not started or kind != "canonical_tick":
                continue
            tick = row.get("tick", len(samples))
            action = row.get("action", [0] * 7)
            state = build_state(row)
            events = compute_events(prev_state, state) if prev_state else []
            samples.append({
                "kind": "sample",
                "decision": len(samples),
                "tick": tick,
                "action": action,
                "state": state,
                "events": events,
            })
            prev_state = state

    if not samples:
        raise ValueError("No canonical_tick records found — gameplay was never reached")

    header = {
        "kind": "header",
        "schema_version": 1,
        "source_sha256": source_sha,
        "scenario": scenario,
        "tick_rate": tick_rate,
        "backend": "game",
    }
    return header, samples


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("probe", type=Path, help="probe.jsonl from a gameplay probe")
    parser.add_argument("--manifest", required=True, type=Path,
                        help="manifest.json from inspect_game or local/source_manifest.json")
    parser.add_argument("--scenario", default="suisei_stage1")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    header, samples = convert(args.probe, manifest, args.scenario)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(header, separators=(",", ":"))]
    lines.extend(json.dumps(s, separators=(",", ":")) for s in samples)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"samples": len(samples), "tick_rate": header["tick_rate"],
                      "scenario": header["scenario"], "output": str(args.out)}, indent=2))


if __name__ == "__main__":
    main()
