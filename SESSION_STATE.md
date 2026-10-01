# Session state: M7 complete; M8 profiler preflight

Updated September 30, 2026. The active request continues milestones for an
optimization and telecommunications lecture. M0–M7 are implemented on main;
there is no remote. M5 is 43f7cf4; M6 is dfe7be9; M7 completes fixed validation and
phase/memory corrections. Each passed its acceptance and a fresh read-only Luna
explorer review before its milestone commit.

M7 acceptance: make golden; make test (29 tests in 296.658s); make validate.
Rust formatting/Clippy and Ruff passed. Contract/golden values and lockfiles are
unchanged by M7. perf.n_batches remains null. No profiler round or calibration
has been performed. Full measurements and final scientific report are pending.

Independent fixed validation protocol exists before observations:
bench/validation_protocol.json, 256batches per point, all 16 points, reserved seed
1312221634. 12real processes produced 49,152 batches. 128theory checks and 96Welch
pair comparisons found 0incompatibles. 32 AWGN cases at 16–30 dB had fewer than 100errors:
evidence_insufficient, never automatically approved or recollected after outcomes.
All 96main-profile pair comparisons are compatible; equivalence is not claimed.
Raw protocol/results: results/validation-20260930T234334-97147. Report:
report/validation-20260930T234334-97147. all_points_approved is false.

All four implementations emit exclusive optional phase markers after warmup,
outside work. Memory baselines and peaks use actual post-marker samples; the
600-second workload deadline excludes warmup. Smoke proves duration/progress
and preserves samples; it does not prove ten-minute stability. Full-only CV
repetition, turbo confirmation and informative 12-CPU orchestration are implemented
but remain unmeasured. Primary results still require M8 calibration and M9 runs.

The harness supplies existing /run/user/1000 bus variables locally. AC is online;
turbo is on and root-owned. perf is absent. Matching apt packages are available:
linux-tools-common and linux-tools-7.1.5-76070105-generic. M8 must stop for the
user's sudo install under the plan's second stop condition. No system package,
governor, turbo setting or persistent PATH was changed.

Resume: activate pinned tools with eval "$(mise env -s bash)" before make.
Recheck M8 profiler tools, perform exactly one profiler round per language, fix
and validate, then calibrate on CPU 2. Record measured machine-time estimate before
M9. Follow the acceptance/fresh-review/one-commit loop and all stop conditions.
