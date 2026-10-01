# Session state: M8 complete; M9 awaits human turbo control

Updated September 30, 2026. The active request continues remaining milestones
for an optimization and telecommunications lecture. M0–M8 are committed on main. M8 passed acceptance and two fresh
read-only Luna reviews after documentation/provenance corrections; no blocking
finding remains. No remote is configured. M5 is 43f7cf4, M6 dfe7be9, M7 adb15ee.

M8 retains exactly one profiler round per language under
results/profiling-20261001T002110-111626. Native perf 7.1.5, isolated uvx py-spy
0.4.2 and Julia stdlib Profile were used on CPU 2 with one worker and 4096 batches.
Python's ECHILD shutdown error occurred after complete sampled data and simulator
output were saved; it is retained and no round was repeated. Per-language NOTES
record evidence and ceilings. Minimal changes preserve the lecture pipeline:
contiguous tap traversal C++/Rust, NumPy product workspace, in-place Julia FFT
result scaling. No RNG, physical contract value or dependency lockfile changed.

The planned M8 calibration freezes only perf.n_batches from null to 2048.
C++ CPU-2 work measured 8.856117789 s; explicitly CPU-0-pinned launcher verification
measured 7.842908383 s. Both exceed five seconds. The original manual launcher's
CPU-0 provenance claim was incorrect; original records and explicit correction
files are preserved. All simulator commands themselves were pinned to CPU 2.
Calibration and profiler timings are not primary comparison evidence.

make test passed 29 tests in 292.222 s; independent golden passes. 64 retained
before/after real integer counter records agree. The post-freeze contract test
now explicitly creates its uncalibrated null fixture; all 18 checks pass.
make doctor, Ruff, Rust formatting and Clippy with warnings denied pass. The
extended FFT interposition probe observes one plan per direction across 101 calls
for the installed IT++ binary and process; it does not prove every interface.

make validate recollected the unchanged predeclared protocol at
results/validation-20261001T003344-116836: 12 processes, 49,152 batches, 128 theory
checks and 96 Welch pair comparisons. Zero incompatible cases; 32 AWGN cases at
16–30 dB remain evidence_insufficient without automatic approval or larger N.
All 96 main-profile pairs are compatible; equivalence is not claimed.
report/validation-20261001T003344-116836 contains regenerated Portuguese tables.
The M7 run remains retained. Reanalysis uses the same observations, not pooling.

M9 estimate is recorded in bench/NOTES and calibration/machine-estimate.json:
227 projected minutes for required primary suites, 15 for full stages, 371 for
required suites if every CV arm repeats, and 44 for turbo-on single confirmation.
Inputs are measured smoke/calibration; scheduling, turbo-off and thermal behavior
remain uncertain. Quality curves can use independent fixed-budget validation.
Full memory stability, primary rankings and final report remain M9–M10 work.

AC is connected; perf access works without sudo. Turbo remains on (no_turbo=0).
Primary M9 requires no_turbo=1, a root-owned human action under the plan's second
stop condition. No system package, governor, turbo, service or persistent PATH
was changed by this work. The user installed linux-perf before resuming.

Resume: activate pinned tools with eval "$(mise env -s bash)" before make.
M8 is closed. Recheck turbo and AC before M9; stop for the exact human turbo command if required. Run single, scaling,
memory and supplementary stages, then generate final PT-BR artifacts from raw
results with proper separate turbo states. Preserve all raw processes and CV
repeats. Never combine smoke with primary timing or claim sparse point approval.
