"""Build, stage, and run a bounded reference probe in an isolated game copy."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from inspect_game import fingerprint, inspect

ROOT = Path(__file__).resolve().parent
LOCAL = ROOT / "local"


def environment():
    # Windows environments can contain both PATH and Path; MSBuild rejects that.
    return {key.upper(): value for key, value in os.environ.items()}


def build():
    env = environment()
    subprocess.run(["cmake", "-S", str(ROOT), "-B", str(ROOT / "build"),
                    "-G", "Visual Studio 17 2022", "-A", "x64"], env=env, check=True)
    subprocess.run(["cmake", "--build", str(ROOT / "build"), "--config", "Release"],
                   env=env, check=True)


def stage(source: Path):
    source = source.resolve(strict=True)
    destination = LOCAL / "game"
    if destination.exists():
        raise RuntimeError("Test game already exists; refusing to overwrite a running/patched copy")
    manifest, _ = inspect(source)
    if manifest["game_version"] != "0.7.1746645739":
        raise RuntimeError("This probe is scoped to 0.7.1746645739; inspect the new build separately")
    downloads = LOCAL / "downloads"
    required = [downloads / "AuriePatcher.exe", downloads / "AurieCore.dll",
                downloads / "YYToolkit.dll", ROOT / "build/Release/HoloProfile.dll",
                ROOT / "build/Release/HoloReference.dll"]
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(path)
    shutil.copytree(source, destination)
    native = destination / "mods/native"
    mods = destination / "mods/aurie"
    native.mkdir(parents=True)
    mods.mkdir(parents=True)
    shutil.copy2(downloads / "AurieCore.dll", native)
    shutil.copy2(downloads / "YYToolkit.dll", mods)
    shutil.copy2(ROOT / "build/Release/HoloProfile.dll", native)
    shutil.copy2(ROOT / "build/Release/HoloReference.dll", mods)
    # Steam's documented local-development launch mode prevents redirecting to
    # the normal installation. It still requires the user's Steam client.
    (destination / "steam_appid.txt").write_text("2420510\n", encoding="ascii")
    subprocess.run([str(downloads / "AuriePatcher.exe"), str(destination / "HoloCure.exe"),
                    "mods/native/AurieCore.dll", "install"], cwd=destination, check=True,
                   env=environment())
    (LOCAL / "source_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    provenance = {"source_files": manifest["files"],
                  "instrumented_executable": fingerprint(destination / "HoloCure.exe"),
                  "libraries": [fingerprint(p) for p in required]}
    (LOCAL / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    print(f"Staged {destination}")


def probe(seconds: int, passive=False, visible=False):
    if not 1 <= seconds <= 300:
        raise ValueError("Probe duration must be 1..300 seconds")
    game = LOCAL / "game"
    if (game / "steam_appid.txt").read_text(encoding="ascii").strip() != "2420510":
        raise RuntimeError("Missing test-copy Steam App ID; refusing a redirect-prone launch")
    # The native module fails closed if the app-data import cannot be redirected.
    profile = LOCAL / "profile"
    trace = LOCAL / "traces" / time.strftime("%Y%m%d-%H%M%S")
    profile.mkdir(parents=True, exist_ok=True)
    trace.mkdir(parents=True, exist_ok=False)
    # Preserve exact initial saves, not only filenames or mutable shared saves.
    shutil.copytree(profile, trace / "profile_before")
    run_manifest = {
        "game_version": "0.7.1746645739",
        "files": [fingerprint(game / name) for name in ("HoloCure.exe", "data.win")],
        "recorder": fingerprint(game / "mods/aurie/HoloReference.dll"),
        "instrumentation": [fingerprint(game / relative) for relative in (
            "mods/native/HoloProfile.dll", "mods/native/AurieCore.dll", "mods/aurie/YYToolkit.dll")],
        "recorder_source": fingerprint(ROOT / "recorder.cpp"),
        "profile_isolation_source": fingerprint(ROOT / "profile_isolation.cpp"),
        "source_binary_correspondence": "working-tree source hashes; correspondence to staged DLLs must be checked separately",
        "source_manifest": json.loads((LOCAL / "source_manifest.json").read_text(encoding="utf-8")),
        "scenario": "discovery; menu commands and actual gameplay state recorded in probe.jsonl",
        "input_semantics": "requested keys; applied input not yet verified",
        "sampling_phase": "after player Step_0; not global end-of-tick",
        "profile_files": [dict(relative_path=str(path.relative_to(profile)), **fingerprint(path))
                          for path in sorted(profile.rglob("*")) if path.is_file()],
        "status": "instrumented_game_capture; parity_unverified",
    }
    (trace / "run_manifest.json").write_text(json.dumps(run_manifest, indent=2) + "\n", encoding="utf-8")
    env = environment()
    env.update(HOLOCURE_PROFILE_DIR=str(profile), HOLOCURE_TRACE_DIR=str(trace),
               LOCALAPPDATA=str(profile), APPDATA=str(profile))
    if passive: env["HOLOCURE_PROBE_PASSIVE"] = "1"
    if visible: env["HOLOCURE_PROBE_VISIBLE"] = "1"
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    with (trace / "process.log").open("w", encoding="utf-8") as output:
        # The intro calls audio_play_sound with resource handles. -noaudio
        # makes those handles invalid in this build and aborts the miner.
        proc = subprocess.Popen([str(game / "HoloCure.exe"), "-inawindow",
                                 "-nosteamrestart", "-debugoutput", str(trace / "runner.log")],
                                cwd=game, env=env, startupinfo=startup,
                                stdout=output, stderr=subprocess.STDOUT)
        print(json.dumps({"pid": proc.pid, "trace": str(trace)}), flush=True)
        timed_out = False
        try:
            proc.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            if proc.poll() is None:
                command_file = trace / "commands.txt"
                if not command_file.exists():
                    command_file.write_text("stop_capture\n", encoding="ascii")
                    # Let the game-thread recorder finish and flush a record.
                    deadline = time.monotonic() + 5
                    while proc.poll() is None and command_file.exists() and time.monotonic() < deadline:
                        time.sleep(0.1)
                if proc.poll() is None:
                    proc.terminate()
                proc.wait(timeout=10)
        result = {"exit_code": proc.returncode, "bounded_probe_stopped": timed_out,
                  "trace_exists": (trace / "probe.jsonl").is_file(),
                  "profile_files": [str(p.relative_to(profile)) for p in profile.rglob("*") if p.is_file()]}
        result["gameplay_reached"] = False
        if result["trace_exists"]:
            with (trace / "probe.jsonl").open(encoding="utf-8", errors="replace") as samples:
                result["gameplay_reached"] = any('"kind":"gameplay_start"' in line for line in samples)
        for name in ("aurie.log", "YYToolkit.log"):
            if (game / name).is_file():
                shutil.copy2(game / name, trace / name)
        shutil.copytree(profile, trace / "profile_after")
        result["profile_files_after"] = [dict(relative_path=str(path.relative_to(profile)), **fingerprint(path))
                                         for path in sorted(profile.rglob("*")) if path.is_file()]
        (trace / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("build")
    setup = commands.add_parser("stage")
    setup.add_argument("game_dir", type=Path)
    run = commands.add_parser("probe")
    run.add_argument("--seconds", type=int, default=20)
    run.add_argument("--passive", action="store_true", help="Disable game-event recording for a framework baseline")
    run.add_argument("--visible", action="store_true", help="Keep probe windows visible for manual input testing")
    args = parser.parse_args()
    if args.command == "build": build()
    elif args.command == "stage": stage(args.game_dir)
    else: probe(args.seconds, args.passive, args.visible)


if __name__ == "__main__":
    main()
