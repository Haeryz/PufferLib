# HoloCure fidelity investigation — 2026-09-08

Status: incomplete reconstruction; not verified for training.

The attached `image-1.gif` shows 148 simulator frames at 900 by 900 pixels.
The native implementations contain defects that change the task the policy learns.
Policy hyperparameter changes cannot establish real-game behavior.

## Corrected and checked

Both `ocean/holocure/holocure.h` and `ocean/holocure_melee/holocure_melee.h`
swapped x/y arguments to `point_direction` during spawn and steering updates.
The movement integration already uses x += speed*cos(direction),
y -= speed*sin(direction). The arguments now use the corresponding axes.

Evidence: raw `local/traces/20260907-201412/probe.jsonl`, SHA256
`f2c0d4169337de2223e143ccf00af32a7e61f85c5d87261e630073b65be5ba2b`.
At tick 1 the first recorded enemy is at (1533.647216796875, 2021.339599609375),
the player at (1920, 1920), and directionMoving is 14.697473526000977 degrees.
Correct-axis geometry gives 14.697480881 degrees; swapped geometry gives
255.302519119 degrees. Tick 2 records (1533.9857177734375, 2021.2508544921875).

Extraction method: existing YYToolkit 4.0.1 instrumented discovery snapshots,
read directly from JSONL. Source version in the source manifest is
0.7.1746645739; original executable SHA256 is
`8c9eb4c6042dfbe2e136fc9f96e3fcaddf9bdcf7cc6b59327ee9ac24fe315b36`,
data.win SHA256 is
`0e40d7d70d835ff9786500c0d345da481fdac34aee6efd95142108ccc6d876c3`.
The converted trace labels the scenario suisei_stage1. This older run lacks
a per-run save manifest: runtime HP 152, SPD 2.26 and EXP 0.2 must not be
treated as base character configuration. Save/upgrade attribution is unresolved.

`test_native_steering.sh` compiles each actual C environment under WSL2.
It tests this geometry against the held-out next recorded position and tests
approach in all eight surrounding directions. The recomputation timer is
deliberately set to exercise steering; this is a transition regression, not an
equivalent-initial-state replay or proof of event-order/whole-game parity.
Both native checks passed. All 14 `test_reference.py` tests passed.

## Invalid prior validation

The old replay copied player/enemy/attack/XP/item states and events from the
expected trace, and did not execute independent environment steps. Its output
files (including existing simulator.jsonl) do not prove parity. Original code
is preserved byte-for-byte as `replay_trace_legacy.py.disabled`; the public
`replay_trace.py` now fails explicitly without creating candidate output.
Raw traces, mined values, game copies, and existing output files are preserved.

## Remaining mechanics and evidence gaps

- Player HP never decreases in either native c_step; death/reset behavior is incomplete.
- XP pickups, progression, level-up choices, special/aim/strafe actions are absent.
- Damage formula, critical hits, and attack collisions are incomplete. A radius
  of 320 is used instead of the extracted animated collision masks.
- Wave probability branches (15 percent, 8 percent), fixed schedule, spawn
  geometry, and 64-enemy cap lack a general source-derived justification.
- Runtime-modified player stats and weapon cadence are hard-coded from one run.
- C rand_r is not an established match for game RNG, and float semantics and
  event ordering have not been established against equivalent game conditions.
- Old discovery traces have null entity IDs; identity and event derivation need
  repair before multi-entity traces can serve as independent parity evidence.
- The canonical converter checks lowercase hp/xp/level even though recorded
  fields include HP/EXP/wlevel; disappearing entities are labeled kills without
  establishing death. These inferred events are not authoritative evidence.
- The legacy Python environment has reference-state injection paths and is not
  an authorized training backend. Training must remain PufferLib 4 native/CUDA.

WSL2 kernel 6.18.33.2-microsoft-standard-WSL2 and NVIDIA GeForce GTX 1660 Ti were
observed using explicit Linux executable paths. This confirms GPU visibility,
not the loaded PufferLib extension, CUDA rollout/training, or rebuilt binaries.
The native regression binaries are diagnostics, not CPU training environments.

Next: repair recorder identity and event evidence, obtain reproducible game
initial conditions/actions/RNG with per-run save manifests, reconstruct the
remaining native mechanics from source/runtime evidence, and build an independent
native parity runner. Only after those checks should the native/CUDA backend
be validated and new policy training evaluated against real-game behavior.

## Recorder and converter repair, 2026-09-08

The previous goal turn made progress (native steering correction and removal of
reference injection from the parity entrypoint). This continuation repaired
typed-reference serialization using the runner's INT64 conversion, removed the
128-member scalar truncation, explicitly listed omitted complex fields, and
deduplicated instances returned through both parent and child object queries.
These records still sample after Player Step, not after all world events.

Both recorder libraries build successfully after repairing a split Windows
constant in profile_isolation.cpp. Original deployed DLLs are preserved in
local/backups/recorder-before-20260908. Probe 20260908-043001 verified an actual
obj_InputManager ID of 100010 and sprite_index -1, with its scalar input fields
and an explicit list of omitted methods. That bounded probe ended normally
through the manager's timeout termination and did not reach gameplay. Its
discovery_world sampling_phase label is inaccurate (input-command callback,
not Player Step); source now corrects that label for the next build.

The converter now refuses null/duplicate entity IDs and malformed JSON rather
than silently collapsing entities or dropping records. It reads HP/EXP/wlevel
with their actual case, treats wlevel as weapon level, and calls disappearance
only disappearance. Converted headers explicitly identify discovery-only
state deltas and unverified requested inputs; trace_check refuses to use them
as parity evidence. All 20 reference/geometry/conversion tests pass.

New managed runs preserve complete before/after profile copies, source/game/DLL
hashes and sampling/input limitations. Working-tree source hashes alone do not
establish correspondence to a staged DLL. Old raw traces remain unchanged.
