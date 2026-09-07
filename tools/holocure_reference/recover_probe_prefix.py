"""Preserve complete records before one truncated EOF record; never rewrite raw evidence."""
import argparse
import hashlib
import json
from pathlib import Path


def recover(source: Path, output: Path):
    if source.resolve() == output.resolve() or output.exists():
        raise ValueError("Recovery requires a new output path")
    raw = source.read_bytes()
    lines = raw.splitlines(keepends=True)
    valid_bytes = 0
    for index, line in enumerate(lines):
        try:
            json.loads(line)
        except json.JSONDecodeError:
            if index != len(lines) - 1 or line.endswith(b"\n"):
                raise ValueError("Corruption is not limited to an incomplete EOF record")
            break
        valid_bytes += len(line)
    prefix = raw[:valid_bytes]
    report = {"status": "explicit_prefix_recovery; discovery_only",
              "source": str(source.resolve()), "source_sha256": hashlib.sha256(raw).hexdigest(),
              "output_sha256": hashlib.sha256(prefix).hexdigest(),
              "source_bytes": len(raw), "preserved_bytes": valid_bytes,
              "discarded_incomplete_tail_bytes": len(raw) - valid_bytes,
              "discarded_tail_sha256": hashlib.sha256(raw[valid_bytes:]).hexdigest()}
    output.write_bytes(prefix)
    output.with_suffix(output.suffix + ".recovery.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(recover(args.source, args.output), indent=2))
