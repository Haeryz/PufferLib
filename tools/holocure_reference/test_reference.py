import struct
import unittest
import json
from pathlib import Path
import tempfile

from trace_check import compare, read_trace

from inspect_game import DataWin


def container(*chunks):
    body = b"".join(tag.encode("ascii") + struct.pack("<I", len(payload)) + payload
                    for tag, payload in chunks)
    return b"FORM" + struct.pack("<I", len(body)) + body


def fixture():
    # FORM(8), STRG header(8), count/pointer(8), record length(4), string.
    strings = struct.pack("<III", 1, 24, 6) + b"suisei\0"
    # OBJT chunk starts at 35; its payload starts at 43 and record at 51.
    objects = struct.pack("<III", 1, 51, 28)
    return container(("STRG", strings), ("OBJT", objects))


class DataWinTests(unittest.TestCase):
    def test_catalog_preserves_resource_index_and_name(self):
        data = DataWin(fixture())
        self.assertEqual(data.records("OBJT"), [{"index": 0, "offset": 51, "name": "suisei"}])
        self.assertEqual(data.records("SCPT"), [])

    def test_rejects_bad_form(self):
        for raw in (b"", b"FORM", b"NOPE\0\0\0\0", fixture()[:-1]):
            with self.subTest(raw=raw[:8]), self.assertRaises(ValueError):
                DataWin(raw)

    def test_rejects_duplicate_chunk(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            DataWin(container(("GEN8", b""), ("GEN8", b"")))

    def test_rejects_count_beyond_chunk(self):
        with self.assertRaisesRegex(ValueError, "count"):
            DataWin(container(("STRG", struct.pack("<I", 0xffffffff))))

    def test_rejects_string_pointer_outside_chunk(self):
        raw = bytearray(fixture())
        struct.pack_into("<I", raw, 20, 51)
        with self.assertRaisesRegex(ValueError, "outside"):
            DataWin(raw)

    def test_rejects_unterminated_string(self):
        raw = bytearray(fixture())
        raw[34] = 65
        with self.assertRaisesRegex(ValueError, "Unterminated"):
            DataWin(raw)

    def test_rejects_bad_resource_name(self):
        raw = bytearray(fixture())
        struct.pack_into("<I", raw, 51, 12345)
        with self.assertRaisesRegex(ValueError, "name pointer"):
            DataWin(raw).records("OBJT")


class TraceTests(unittest.TestCase):
    def test_retired_injection_replay_cannot_produce_parity_output(self):
        from replay_trace import replay
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "simulator.jsonl"
            with self.assertRaisesRegex(RuntimeError, "copied reference states"):
                replay(Path(directory) / "game.jsonl", output)
            self.assertFalse(output.exists())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, backend, x=0, hp=100, tick=1, version=1, events=None):
        path = self.root / (backend + ".jsonl")
        records = [{"kind": "header", "schema_version": version,
                    "source_sha256": "0" * 64, "scenario": "synthetic-unit-test",
                    "tick_rate": 60, "backend": backend},
                   {"kind": "sample", "decision": 0, "tick": tick,
                    "action": [0, 0, 0], "state": {"player": {"x": x, "y": 0, "hp": hp}},
                    "events": events or []}]
        path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
        return path

    def test_position_tolerance_does_not_tolerate_damage_difference(self):
        reference = self.write("game")
        self.assertTrue(compare(reference, self.write("simulator", x=0.75))["passed"])
        self.assertFalse(compare(reference, self.write("simulator", hp=99.9))["passed"])

    def test_reports_first_divergence(self):
        result = compare(self.write("game"), self.write("simulator", x=1.01))
        self.assertFalse(result["passed"])
        self.assertEqual(result["first_divergent_decision"], 0)

    def test_timing_and_event_order_are_exact(self):
        self.assertFalse(compare(self.write("game"), self.write("simulator", tick=2))["passed"])
        self.assertFalse(compare(self.write("game", events=["hit", "kill"]),
                                 self.write("simulator", events=["kill", "hit"]))["passed"])

    def test_rejects_nan_positions(self):
        self.assertFalse(compare(self.write("game"), self.write("simulator", x=float("nan")))["passed"])

    def test_rejects_discovery_probe_as_evidence(self):
        path = self.root / "probe.jsonl"
        path.write_text('{"kind":"probe_header","schema_version":1}\n')
        with self.assertRaisesRegex(ValueError, "discovery"):
            read_trace(path)

    def test_rejects_unknown_schema(self):
        with self.assertRaisesRegex(ValueError, "unsupported"):
            read_trace(self.write("game", version=2))


if __name__ == "__main__":
    unittest.main()
