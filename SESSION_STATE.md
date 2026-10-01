# Session state: code-only validation; comparison collection deferred

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

Current user instruction: write the code and assure validity only; comparison
experiments are deferred. The user authorized a commit after finishing. Never
resume or start collection based on the older milestone loop without a new user
instruction. No new profiling, simulation-based validation collection, cold-build
timing experiment or make bench/test-bench is authorized in this stage. make test
also contains a smoke collection and must not be used for the current scope.

The M9 run results/20261001T010257-124574 was terminated after seven completed
processes. Its manifest is incomplete with interrupted_by_user=true. Raw files
and interruption reason are preserved; it is not a completed comparison. The
make session 81320 ended; all simulator/capture processes for that run are gone.
results/M9_CANCELLED points to it; no collection is running.

New code-only commands: make check builds all four implementations, then checks
contracts/inference, a non-executing plan, four real golden interfaces and report
input boundaries. make bench-plan TURBO=on emits planned commands, affinities,
process counts and workload without executing tools/simulators or checking live
hardware. The runner and preview share CPU geometry selection. Unknown and
duplicate suites are rejected. The full plan has 328 baseline processes and up
to 320 CV repeat processes; these are scheduled counts, not observed results.

Report input now uses the strict raw-result boundary, refuses stale fingerprints
and differing configurations within/across comparison groups, and preserves the
incomplete-run rejection. Payload throughput and relative ratios are limited to
fixed performance suites, not stage timers or adaptive BER. No experiment was
run to validate this change: explicitly invalid input fixtures exercise rejection
before reporting. Old M8 numerical evidence remains available and unchanged.

Validation logs: results/code-check-ready.log and results/acceptance/code-golden/;
results/acceptance/plan-only/plan.json is the non-executed preview. All 33 short
checks passed (18 contract, 3 inference, 3 planning, 1 four-language golden,
8 report-boundary). Ruff passed. Rendering now finishes in a temporary directory before publishing; failures
preserve or restore the previous report. Phase ratios are inapplicable outside
fixed performance, and source commits/scaling loads are validated. Final fresh
read-only review found no findings; the user-authorized code preparation commit
closes this scope. Comparison experiments remain deferred. The reviewer must not launch experiments. M9 measurements and M10's
scientific final report, including measured ergonomics, remain deferred.

Activate pinned tools with eval "$(mise env -s bash)" before make. Use make check
for code assurance. All frozen numerical values, lockfiles, simulator algorithms
and profiler budgets are unchanged. No system setting or persistent PATH changed.
