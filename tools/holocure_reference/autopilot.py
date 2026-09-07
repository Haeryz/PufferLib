"""Drive the game from menu into Stage 1 gameplay and capture a reference trace.

Sends timed input commands via the recorder's commands.txt bridge so the
probe captures actual gameplay (obj_Player_Step_0) instead of only menu state.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCAL = ROOT / "local"
GAME = LOCAL / "game"

SPACE = 32
ENTER = 13
LEFT = 65    # A
RIGHT = 68   # D
UP = 87      # W
DOWN = 83    # S


def environment():
    return {key.upper(): value for key, value in os.environ.items()}


def write_commands(trace_dir: Path, commands: list[str]):
    path = trace_dir / "commands.txt"
    path.write_text("\n".join(commands) + "\n", encoding="ascii")


def autopilot_thread(trace_dir: Path, stop_event: threading.Event, visible: bool):
    """Wait for gameplay to start, then send movement commands."""
    probe_path = trace_dir / "probe.jsonl"
    while not stop_event.is_set() and not probe_path.is_file():
        if stop_event.wait(1.0):
            return
    if stop_event.is_set():
        return

    # Wait for the user to manually navigate menus and start Stage 1.
    gameplay_started = False
    while not stop_event.is_set() and not gameplay_started:
        if probe_path.is_file():
            with probe_path.open(encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"gameplay_start"' in line:
                        gameplay_started = True
                        break
        if not gameplay_started:
            if stop_event.wait(2.0):
                return

    if not gameplay_started or stop_event.is_set():
        return

    # Gameplay has started. Send movement commands to exercise the simulation.
    start = time.monotonic()
    moves: list[tuple[float, list[str]]] = [
        (3.0, [f"press {UP}"]),
        (6.0, [f"release {UP}", f"press {RIGHT}"]),
        (9.0, [f"release {RIGHT}", f"press {DOWN}"]),
        (12.0, [f"release {DOWN}", f"press {LEFT}"]),
        (15.0, [f"release {LEFT}"]),
        (18.0, [f"press {SPACE}", f"release {SPACE}"]),
        (21.0, [f"press {UP}", f"press {RIGHT}"]),
        (26.0, [f"release {UP}", f"release {RIGHT}"]),
        (31.0, [f"press {DOWN}", f"press {LEFT}"]),
        (36.0, [f"release {DOWN}", f"release {LEFT}"]),
        (41.0, [f"press {SPACE}", f"release {SPACE}"]),
    ]
    for target, commands in moves:
        elapsed = time.monotonic() - start
        if elapsed < target:
            if stop_event.wait(target - elapsed):
                return
        if stop_event.is_set():
            return
        write_commands(trace_dir, commands)


def wait_for_gameplay(trace_path: Path, timeout: float = 40) -> bool:
    """Poll probe.jsonl for a gameplay_start record."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if trace_path.is_file():
            with trace_path.open(encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"gameplay_start"' in line:
                        return True
        time.sleep(1.0)
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=90)
    parser.add_argument("--visible", action="store_true")
    args = parser.parse_args()
    if not 10 <= args.seconds <= 300:
        raise ValueError("Duration must be 10..300 seconds")
    if not (GAME / "steam_appid.txt").is_file():
        raise RuntimeError("Staged game not found; run manage.py stage first")

    profile = LOCAL / "profile"
    trace = LOCAL / "traces" / time.strftime("%Y%m%d-%H%M%S")
    profile.mkdir(parents=True, exist_ok=True)
    trace.mkdir(parents=True, exist_ok=False)
    env = environment()
    env.update(HOLOCURE_PROFILE_DIR=str(profile), HOLOCURE_TRACE_DIR=str(trace),
               LOCALAPPDATA=str(profile), APPDATA=str(profile))
    if args.visible:
        env["HOLOCURE_PROBE_VISIBLE"] = "1"

    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 1 if args.visible else 0

    stop_event = threading.Event()
    autopilot = threading.Thread(target=autopilot_thread,
                                 args=(trace, stop_event, args.visible), daemon=True)
    autopilot.start()

    proc = subprocess.Popen(
        [str(GAME / "HoloCure.exe"), "-inawindow",
         "-nosteamrestart", "-debugoutput", str(trace / "runner.log")],
        cwd=GAME, env=env, startupinfo=startup)
    print(json.dumps({"pid": proc.pid, "trace": str(trace)}), flush=True)
    timed_out = False
    try:
        proc.wait(timeout=args.seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=10)
    stop_event.set()
    autopilot.join(timeout=5)

    import shutil
    for name in ("aurie.log", "YYToolkit.log"):
        src = GAME / name
        if src.is_file():
            shutil.copy2(src, trace / name)

    gameplay = wait_for_gameplay(trace / "probe.jsonl", timeout=10)
    result = {
        "exit_code": proc.returncode,
        "bounded_probe_stopped": timed_out,
        "trace_exists": (trace / "probe.jsonl").is_file(),
        "gameplay_reached": gameplay,
        "trace": str(trace),
    }
    (trace / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
