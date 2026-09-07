"""Validate and compare canonical gameplay traces, never render-frame probes.

Format: one header followed by samples. Each sample has decision, tick, action,
state, and events. Both backends must use stable scenario entity identifiers.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def read_trace(path: Path) -> tuple[dict, list[dict]]:
    with path.open(encoding="utf-8") as stream:
        records = [json.loads(line) for line in stream if line.strip()]
    if not records or records[0].get("kind") != "header":
        raise ValueError("Expected canonical gameplay header; discovery probes cannot establish fidelity")
    header, samples = records[0], records[1:]
    required = ("schema_version", "source_sha256", "scenario", "tick_rate", "backend")
    if any(key not in header for key in required) or header["schema_version"] != 1:
        raise ValueError("Incomplete or unsupported trace header")
    if header["backend"] not in ("game", "simulator") or header["tick_rate"] <= 0:
        raise ValueError("Invalid trace backend or tick rate")
    if not samples:
        raise ValueError("Empty traces cannot pass validation")
    previous_tick = -1
    for index, sample in enumerate(samples):
        if sample.get("kind") != "sample" or sample.get("decision") != index:
            raise ValueError("Samples must have consecutive decision indices starting at zero")
        tick = sample.get("tick")
        if type(tick) is not int or tick < 0 or tick < previous_tick:
            raise ValueError("Ticks must be nonnegative, monotonic integers")
        if not all(key in sample for key in ("action", "state", "events")):
            raise ValueError("Incomplete sample")
        previous_tick = tick
    return header, samples


def compare(reference: Path, candidate: Path, tolerance: float = 1.0) -> dict:
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("Position tolerance must be finite and nonnegative")
    ref_header, ref_samples = read_trace(reference)
    sim_header, sim_samples = read_trace(candidate)
    if ref_header["backend"] != "game" or sim_header["backend"] != "simulator":
        raise ValueError("Expected game reference and simulator candidate")
    for key in ("schema_version", "source_sha256", "scenario", "tick_rate"):
        if ref_header[key] != sim_header[key]:
            raise ValueError(f"Incompatible traces: {key}")
    differences = []
    max_position_error = 0.0

    def visit(a, b, path):
        nonlocal max_position_error
        if type(a) is not type(b) and not (type(a) in (int, float) and type(b) in (int, float)):
            differences.append(f"{path}: type mismatch")
        elif isinstance(a, dict):
            if a.keys() != b.keys():
                differences.append(f"{path}: fields differ")
                return
            # Only physical world positions receive a tolerance. Every other
            # quantity, including hp, damage, event order, and clocks, is exact.
            positions = {"x", "y"} <= a.keys() and path.startswith("state.")
            if positions:
                try:
                    delta = math.hypot(a["x"] - b["x"], a["y"] - b["y"])
                except TypeError:
                    delta = math.inf
                if not math.isfinite(delta) or delta > tolerance:
                    differences.append(f"{path}: position error {delta}")
                max_position_error = max(max_position_error, delta)
            for key in a:
                if positions and key in ("x", "y"):
                    continue
                visit(a[key], b[key], f"{path}.{key}")
        elif isinstance(a, list):
            if len(a) != len(b):
                differences.append(f"{path}: lengths differ")
                return
            for i, (left, right) in enumerate(zip(a, b)):
                visit(left, right, f"{path}[{i}]")
        elif isinstance(a, (int, float)) and not isinstance(a, bool):
            if not math.isfinite(a) or not math.isfinite(b) or a != b:
                differences.append(f"{path}: {a} != {b}")
        elif a != b:
            differences.append(f"{path}: values differ")

    if len(ref_samples) != len(sim_samples):
        differences.append("sample counts differ")
    first_divergent_decision = None
    for a, b in zip(ref_samples, sim_samples):
        before = len(differences)
        for key in ("decision", "tick", "action", "state", "events"):
            visit(a[key], b[key], key)
        if len(differences) != before:
            first_divergent_decision = a["decision"]
            break
    return {"passed": not differences, "first_divergent_decision": first_divergent_decision,
            "reference_samples": len(ref_samples), "candidate_samples": len(sim_samples),
            "max_position_error": max_position_error,
            "differences": differences[:30]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--position-tolerance", type=float, default=1.0)
    args = parser.parse_args()
    result = compare(args.reference, args.candidate, args.position_tolerance)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
