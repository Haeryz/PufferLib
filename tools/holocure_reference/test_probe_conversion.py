"""Regressions for evidence corruption observed in the old converter."""
import json
from pathlib import Path
import tempfile
import unittest

from probe_to_canonical import build_state, compute_events, convert
from trace_check import compare


class ConversionTests(unittest.TestCase):
    def test_missing_and_duplicate_ids_do_not_collapse_entities(self):
        with self.assertRaisesRegex(ValueError, "instance ID"):
            build_state({"instances": [{"object": "obj_Enemy", "id": None}]})
        enemy = {"object": "obj_Enemy", "id": 100001}
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            build_state({"instances": [enemy, dict(enemy)]})

    def test_actual_field_names_and_weapon_level_semantics(self):
        before = {"player": {"HP": 70, "EXP": 0.2, "wlevel": 1},
                  "enemies": [{"id": 100001, "HP": 8}]}
        after = {"player": {"HP": 69, "EXP": 0.3, "wlevel": 2},
                 "enemies": [{"id": 100001, "HP": 6}]}
        self.assertEqual(compute_events(before, after), [
            "player_hp_decreased", "weapon_level_increased",
            "player_exp_increased", "enemy_hp_decreased"])

    def test_disappearance_does_not_claim_kill_or_pickup(self):
        before = {"enemies": [{"id": 100001}], "xp": [{"id": 100002}]}
        self.assertEqual(compute_events(before, {}), ["enemy_disappeared", "xp_disappeared"])

    def test_object_change_keeps_same_identity(self):
        before = {"enemies": [{"id": 100001, "object": "obj_Enemy", "HP": 2}]}
        after = {"enemies": [{"id": 100001, "object": "obj_EnemyDead", "HP": 0}]}
        self.assertEqual(compute_events(before, after), ["enemy_hp_decreased"])

    def test_discovery_conversion_is_not_parity_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            probe = root / "probe.jsonl"
            rows = [{"kind": "gameplay_start", "tick_rate": 60},
                    {"kind": "canonical_tick", "tick": 0, "action": [0] * 7,
                     "instances": [{"object": "obj_Player", "id": 100001, "vars": {"HP": 70}}]}]
            probe.write_text("\n".join(map(json.dumps, rows)), encoding="utf-8")
            header, samples = convert(probe, {"files": [{"name": "HoloCure.exe", "sha256": "a" * 64}]}, "test")
            self.assertEqual(header["validation_status"], "discovery_only")
            paths = []
            for backend in ("game", "simulator"):
                path = root / (backend + ".jsonl")
                path.write_text("\n".join(map(json.dumps, [dict(header, backend=backend), *samples])))
                paths.append(path)
            with self.assertRaisesRegex(ValueError, "Discovery-only"):
                compare(*paths)
            with probe.open("a") as stream:
                stream.write('\n{"kind":')
            with self.assertRaisesRegex(ValueError, "Malformed"):
                convert(probe, {}, "test")


if __name__ == "__main__":
    unittest.main()
