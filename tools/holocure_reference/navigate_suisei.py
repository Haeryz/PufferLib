"""Replay the observed menu path into Suisei Stage 1; discovery capture only.

No gameplay state/RNG is injected. Menu method calls and all initial profile
modifiers must be retained in the run evidence. Gameplay remains idle.
"""
import argparse
import json
from pathlib import Path
import time


def navigate(root):
    probe = root / "probe.jsonl"
    command = root / "commands.txt"
    deadline = time.monotonic() + 120

    def send(lines):
        while command.exists():
            if time.monotonic() > deadline:
                raise TimeoutError("Previous menu command was not consumed")
            time.sleep(0.1)
        temporary = root / "commands.pending"
        temporary.write_text("\n".join(lines) + "\n", encoding="ascii")
        temporary.replace(command)

    def wait_event(name):
        # Only look for observed event metadata; partial final lines are not
        # converted into canonical evidence by this live navigation helper.
        while time.monotonic() < deadline:
            if probe.exists() and name in probe.read_text(encoding="utf-8"):
                time.sleep(1)
                return
            time.sleep(0.5)
        raise TimeoutError(f"Game did not reach {name}")

    wait_event("gml_Object_obj_Intro_Step_0")
    send(["call obj_Intro EnterKey"])
    wait_event("gml_Object_obj_TitleScreen_Step_0")
    # Observed title default is currentOption 3 (Play), not option 0 (scores).
    time.sleep(2)
    send(["inspect obj_TitleScreen", "call obj_TitleScreen Confirmed"])
    wait_event("gml_Object_obj_CharSelect_Step_0")
    send(["call obj_CharSelect Down"] + ["call obj_CharSelect Right"] * 8 + ["inspect obj_CharSelect"])
    # Confirm character, outfit, stage mode, Stage 1, and preparation in order.
    for _ in range(5):
        time.sleep(1)
        send(["call obj_CharSelect Select"])
    wait_event('"kind":"gameplay_start"')
    send(["screenshot", "catalog"])
    print(json.dumps({"status": "gameplay_reached; verify actual character and stage in trace",
                      "trace": str(root)}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    navigate(parser.parse_args().trace)
