"""Read-only, bounded inspection of a local GameMaker installation (stdlib only).

Outputs are research artifacts, not a claim that gameplay has been reproduced.
No executable is run and the source installation is never modified.
"""
from __future__ import annotations

import argparse
import configparser
import hashlib
import json
from pathlib import Path
import re
import struct


class DataWin:
    def __init__(self, data: bytes):
        self.data = data
        if len(data) < 8 or data[:4] != b"FORM":
            raise ValueError("Not a GameMaker FORM container")
        if self.u32(4) != len(data) - 8:
            raise ValueError("FORM length does not match file length")
        self.chunks: dict[str, tuple[int, int]] = {}
        pos = 8
        while pos < len(data):
            self.require(pos, 8)
            tag = data[pos:pos + 4].decode("ascii")
            size = self.u32(pos + 4)
            self.require(pos + 8, size)
            if tag in self.chunks:
                raise ValueError(f"Duplicate chunk {tag}")
            self.chunks[tag] = (pos + 8, size)
            pos += 8 + size
        self.strings: dict[int, str] = {}
        for offset in self.offsets("STRG"):
            start, size = self.chunks["STRG"]
            if not start <= offset < start + size - 4:
                raise ValueError("String record outside STRG")
            length = self.u32(offset)
            if offset + 4 + length >= start + size:
                raise ValueError("String extends outside STRG")
            raw = self.data[offset + 4:offset + 4 + length]
            if self.data[offset + 4 + length] != 0:
                raise ValueError("Unterminated string")
            self.strings[offset + 4] = raw.decode("utf-8", errors="replace")

    def require(self, offset: int, length: int):
        if offset < 0 or length < 0 or offset + length > len(self.data):
            raise ValueError(f"Out-of-bounds read at {offset}, length {length}")

    def u32(self, offset: int) -> int:
        self.require(offset, 4)
        return struct.unpack_from("<I", self.data, offset)[0]

    def offsets(self, tag: str) -> list[int]:
        if tag not in self.chunks:
            return []
        start, size = self.chunks[tag]
        if size < 4:
            raise ValueError(f"Missing count in {tag}")
        count = self.u32(start)
        if count > (size - 4) // 4:
            raise ValueError(f"Invalid pointer count in {tag}")
        result = [self.u32(start + 4 + i * 4) for i in range(count)]
        if any(p < start or p + 4 > start + size for p in result):
            raise ValueError(f"Record pointer outside {tag}")
        return result

    def records(self, tag: str) -> list[dict]:
        result = []
        for index, offset in enumerate(self.offsets(tag)):
            name_ptr = self.u32(offset)
            if name_ptr not in self.strings:
                raise ValueError(f"Invalid name pointer in {tag}[{index}]")
            result.append({"index": index, "offset": offset,
                           "name": self.strings[name_ptr]})
        return result


def fingerprint(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"name": path.name, "size_bytes": path.stat().st_size,
            "sha256": digest.hexdigest()}


def inspect(game_dir: Path) -> tuple[dict, dict]:
    version = configparser.ConfigParser()
    version.read(game_dir / "version.ini", encoding="utf-8-sig")
    data = DataWin((game_dir / "data.win").read_bytes())
    manifest = {
        "schema_version": 1,
        "game_version": version.get("Version", "version").strip('"'),
        "files": [fingerprint(game_dir / n) for n in ("HoloCure.exe", "data.win")],
        "code_chunk_present": "CODE" in data.chunks,
        "compilation_assessment": "VM code present" if "CODE" in data.chunks else
            "No CODE chunk; native/YYC logic expected. Runtime verification required.",
        "chunks": {tag: {"offset": start, "size_bytes": size}
                   for tag, (start, size) in data.chunks.items()},
        "validation_status": "static_inspection_only",
    }
    catalog = {tag: data.records(tag) for tag in ("OBJT", "SCPT", "SPRT", "ROOM")}
    # Select actual resource names, not arbitrary strings (which include credits).
    pattern = re.compile(r"suisei|axeswing|player|enemy|stage|exp|level|attack", re.I)
    manifest["research_identifiers"] = {
        tag: [r["name"] for r in records if pattern.search(r["name"])]
        for tag, records in catalog.items()
    }
    return manifest, catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game_dir", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    source = args.game_dir.resolve()
    destination = args.out.resolve()
    if destination == source or source in destination.parents:
        parser.error("Output must be outside the game installation")
    manifest, catalog = inspect(source)
    destination.mkdir(parents=True, exist_ok=True)
    for name, content in (("manifest.json", manifest), ("catalog.json", catalog)):
        (destination / name).write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"version": manifest["game_version"],
                      "code_chunk_present": manifest["code_chunk_present"],
                      "resources": {k: len(v) for k, v in catalog.items()},
                      "output": str(destination)}, indent=2))


if __name__ == "__main__":
    main()
