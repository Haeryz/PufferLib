"""Retired trace-injection replay; independent native replay is required."""
from pathlib import Path


def replay(game_trace_path: Path, sim_out_path: Path, position_tolerance: float = 1.0):
    raise RuntimeError(
        "Gameplay parity unavailable: the retired replay copied reference states "
        "and events instead of independently stepping the native simulator. "
        "Its source is preserved in replay_trace_legacy.py.disabled. "
        "Existing simulator.jsonl outputs from that replay are not parity evidence."
    )


if __name__ == "__main__":
    raise SystemExit("Parity replay disabled: reference-state injection is invalid. See FIDELITY.md.")
