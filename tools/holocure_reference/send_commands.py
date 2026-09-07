"""Send timed menu-navigation commands to a running probe's commands.txt.

Usage: start a visible probe first (manage.py probe --visible --seconds 300),
find the trace directory, then run: python send_commands.py <trace_dir>
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

SPACE = 32
LEFT = 65
RIGHT = 68
UP = 87
DOWN = 83


def write_commands(trace_dir: Path, commands: list[str]):
    path = trace_dir / "commands.txt"
    path.write_text("\n".join(commands) + "\n", encoding="ascii")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace_dir", type=Path)
    parser.add_argument("--delay", type=float, default=5.0,
                        help="Seconds between each command batch")
    parser.add_argument("--count", type=int, default=10,
                        help="Number of Space presses to send")
    args = parser.parse_args()

    probe_path = args.trace_dir / "probe.jsonl"
    print(f"Waiting for probe.jsonl in {args.trace_dir}...", flush=True)
    while not probe_path.is_file():
        time.sleep(1.0)
    print("Recorder is running. Sending commands...", flush=True)

    for i in range(args.count):
        time.sleep(args.delay)
        write_commands(args.trace_dir, [f"press {SPACE}", f"release {SPACE}"])
        print(f"  Sent Space press #{i+1}/{args.count}", flush=True)
        # Check if gameplay started
        try:
            with probe_path.open(encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"gameplay_start"' in line:
                        print("Gameplay reached! Sending movement commands.", flush=True)
                        for move in [
                            ([f"press {UP}"], 3.0),
                            ([f"release {UP}", f"press {RIGHT}"], 3.0),
                            ([f"release {RIGHT}", f"press {DOWN}"], 3.0),
                            ([f"release {DOWN}", f"press {LEFT}"], 3.0),
                            ([f"release {LEFT}"], 3.0),
                            ([f"press {SPACE}", f"release {SPACE}"], 3.0),
                            ([f"press {UP}", f"press {RIGHT}"], 5.0),
                            ([f"release {UP}", f"release {RIGHT}"], 5.0),
                            ([f"press {DOWN}", f"press {LEFT}"], 5.0),
                            ([f"release {DOWN}", f"release {LEFT}"], 5.0),
                        ]:
                            cmds, delay = move
                            time.sleep(delay)
                            write_commands(args.trace_dir, cmds)
                            print(f"  Sent: {cmds}", flush=True)
                        return
        except Exception:
            pass
    print("Gameplay not reached after all commands.", flush=True)


if __name__ == "__main__":
    main()
