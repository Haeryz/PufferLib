"""Extract Suisei's measured configuration, without claiming verified dynamics."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

CHARACTER_FIELDS = ("id", "attackID", "HP", "ATK", "SPD", "crit")
WEAPON_FIELDS = ("attackID", "damage", "attackTime", "image_xscale", "image_yscale",
                 "CritMod", "sureCrit", "knockback", "duration", "hitCD", "hitLimit",
                 "hitbox", "startx", "starty", "stayOnCreator", "faceCreatorDirection",
                 "maxLevel", "attackCount", "attackDelay", "destroyOnHitLimit", "sprite_index")


def extract(trace: Path, manifest: dict) -> dict:
    tables = {}
    with trace.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row.get("kind") == "global_data":
                tables[row["name"]] = row["state"]
    character = tables["characterData"]
    if "suisei" in character:
        character = character["suisei"]
    weapon = tables["attacksLibrary"]
    if "AxeSwing" in weapon:
        weapon = weapon["AxeSwing"]
    if character.get("id") != "suisei" or weapon.get("attackID") != "AxeSwing":
        raise ValueError("Trace does not contain Suisei and AxeSwing")
    config = weapon["config"]
    levels = config["levels"]
    if levels.get("_truncated") or levels.get("length") != 6 or len(levels.get("values", [])) != 6:
        raise ValueError("Need all six upgrade patches; truncated data cannot establish a profile")
    current = {key: config[key] for key in WEAPON_FIELDS if key in config}
    result_levels = [dict(level=1, raw_config=current.copy())]
    for level, patch in enumerate(levels["values"], start=2):
        if "config" not in patch or patch["config"].get("_truncated"):
            raise ValueError(f"Missing level {level} patch")
        current.update({key: value for key, value in patch["config"].items() if key in WEAPON_FIELDS})
        result_levels.append(dict(level=level, raw_config=current.copy()))
    files = {entry["name"]: entry["sha256"] for entry in manifest["files"]}
    return {
        "schema_version": 1,
        "reference": {"game_version": manifest["game_version"], "source_sha256": files},
        "status": "runtime_configuration_extracted; gameplay_parity_unverified",
        "character": {key: character[key] for key in CHARACTER_FIELDS},
        "weapon_levels": result_levels,
        "scope": {"stage": "STAGE 1", "duration_seconds": 300,
                  "skills": False, "special": False, "weapon_upgrades": "agent_selected"},
        "unresolved": ["simulation tick rate and event order", "movement units and collision rules",
                       "attack mask and active animation frames", "damage formula and rounding",
                       "critical-hit formula and RNG", "contact damage and invulnerability",
                       "XP thresholds and upgrade-offer generation", "Stage 1 spawn schedule and enemy behavior",
                       "input/reset bridge and deterministic gameplay replay"],
        "notes": ["raw_config preserves game field names and values; attackTime is not yet labeled in seconds or ticks.",
                  "damage is an extracted coefficient, not a measured HP loss.",
                  "Level configurations apply the extracted per-level patches cumulatively; this merge still needs runtime level-up validation.",
                  "No game sprites, executable, save data, or localized descriptions are included."]
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    profile = extract(args.trace, json.loads(args.manifest.read_text(encoding="utf-8")))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    print(f"Extracted {len(profile['weapon_levels'])} levels to {args.out}; gameplay parity remains unverified.")


if __name__ == "__main__":
    main()
