import json
from pathlib import Path
import tempfile
import unittest

from recover_probe_prefix import recover


class RecoveryTests(unittest.TestCase):
    def test_only_incomplete_tail_is_removed_and_original_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = (Path(directory) / name for name in ("raw", "prefix"))
            raw = b'{"kind":"heartbeat"}\n{"kind":"canonical_tick","tick":'
            source.write_bytes(raw)
            report = recover(source, output)
            self.assertEqual(source.read_bytes(), raw)
            self.assertEqual(output.read_bytes(), b'{"kind":"heartbeat"}\n')
            self.assertEqual(report["source_bytes"], len(raw))
            self.assertGreater(report["discarded_incomplete_tail_bytes"], 0)
            self.assertEqual(json.loads(output.with_suffix(".recovery.json").read_text()), report)

    def test_internal_corruption_is_rejected_without_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = (Path(directory) / name for name in ("raw", "prefix"))
            source.write_bytes(b'{broken}\n{"kind":"heartbeat"}\n')
            with self.assertRaisesRegex(ValueError, "Corruption"):
                recover(source, output)
            self.assertFalse(output.exists())

    def test_existing_evidence_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "raw"
            source.write_bytes(b'{}\n')
            with self.assertRaisesRegex(ValueError, "new output"):
                recover(source, source)


if __name__ == "__main__":
    unittest.main()
