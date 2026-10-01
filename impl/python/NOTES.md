# M3 implementation notes

The implementation uses only NumPy 2.5.3 and the Python standard library. NumPy
is isolated in `impl/python/.venv` with its own committed lockfile; SciPy is never
imported. The shared `tools.contract` module contains only stdlib configuration
validation and hashing, and does not import competing simulator code.

## Design and failure boundaries

The E2E acceptance scenario was added before implementation. It covers all
golden inputs, invalid configuration/CLI boundaries, both stopping reasons,
diagnostic channels, raw-byte fingerprints, repeated seeds, and worker counts.
Each batch uses a fresh `Generator(PCG64(full_u64_seed))`. Mapping, FFTs, noise,
LS interpolation, decisions, and counting operate over a 256-symbol matrix.
Convolution is a direct eight-tap accumulation using sliced NumPy arrays.

The persistent `ProcessPoolExecutor` explicitly selects `forkserver`. A startup
barrier makes every worker initialize before setup ends. Initialization submits
only empty tasks, not simulation batches. Four distinct-seed warmup batches are
then executed and excluded from counters. Dynamic scheduling uses one batch per
task (`chunksize=1`); results are aggregated by batch index. Extra results after
the stopping index are discarded. Output replacement is atomic and outside work.

## Acceptance cycle 1

`make test-python` runs the shared artifact-producing CLI acceptance. The NumPy
FFT signature and random generator documentation were inspected from the pinned
installed package before coding. No calibration, theory test, or profiler round
was performed. All generated acceptance evidence remains in
`results/acceptance/python/`.

## Pending for Phase 2

The M4 independent review identified a shared stage issue: `channel_conv` draws
new taps inside the timed repetition instead of using a pregenerated tap batch.
This historical finding is resolved by the lecture refactor below.
M7 will recheck the completed implementations before performance reporting.

Independent review reported no blocking or nonblocking findings. `make golden`
and `make test` passed all 23 checks. Ruff 0.16.9 was already available in the
local uv cache and was used for formatting and linting without adding any project
dependency. Final CLI exception handling names the expected runtime error classes.

No optimization has been applied. M8 will inspect one profiler round before
changing measured hotspots. Stage CP removal explicitly copies the slice to
measure the removal operation consistently with the other implementations.

## Lecture refactor — September 30, 2026

The pipeline now names transmit/receive signals and the tensor dimensions explicitly.
Pilot values and the Gray axis table are retained instead of rebuilding invariant
arrays. Batch vectorization and PCG64 draw shapes/order remain unchanged. No buffer
pool or dependency was added; the single profiler round remains pending for M8.

The pending stage defect is resolved: `channel_conv` uses the pregenerated tap
batch. End-to-end stage repetitions now derive distinct deterministic seeds,
matching the repetition rule already used by C++ and Rust. Stage nanoseconds use
OFDM symbols as the denominator. Comments distinguish the unscaled channel DFT
from unitary signal FFTs and exact channel zeros from small nonzero gains.
No contract value or schema changed. There is no measured speedup claim.

### Refactor acceptance and independent review

`make doctor`, `make golden`, and `make test` passed (24 tests). All 30 retained
CLI artifacts match their pre-refactor numerical outputs and metadata exactly
when setup/warmup/work and stage timing fields are excluded. The local evidence
is `results/refactor/comparison.json`; `results/refactor/verify.py` regenerates
that comparison. E2E now also checks finite, positive isolated stage durations
and finite, nonnegative phase durations. No timing result proves a speedup.

An independent read-only explorer review found no blocker. Rust formatting and
Clippy with warnings denied passed; Python and shared E2E Ruff checks passed.
The frozen contract and all lockfiles remain byte-unchanged.

## M7 phase boundary and independent validation

The optional BENCH_PHASE_PATH marker is created exclusively after warmup and
before the work timer. It writes no data inside timed work and cannot overwrite
an existing marker. Shared E2E verifies this boundary, no marker/result on invalid
input, and unchanged worker-independent counters. It supports actual sampled
post-warmup memory baselines, not reconstruction from elapsed work durations.

The fixed validation protocol reserves master_seed 1312221634 and 256 batches per
point before outcomes, across all 16 profile points. AWGN/perfect CSI and
Rayleigh/perfect CSI use a family of 128 simultaneous 99% batch-mean intervals;
the main estimated-CSI profile uses 96 Bonferroni-controlled Welch comparisons.
No incompatible case was found. The 32 AWGN cases at 16–30 dB had fewer than 100 errors
and remain evidence_insufficient, without point approval or increasing sample
size after outcomes. Compatibility is not equivalence. No contract, RNG draw
order, algorithm or profiler optimization changed.

## M8 profiler-guided round

One py-spy 0.4.2 round used native and subprocess stacks at 100 Hz,
4,096 batches, one worker, CPU 2, and turbo on. py-spy is explicitly named in
the plan and ran through an isolated uvx environment, without changing any
project dependency or lockfile. The raw speedscope data, command, streams,
environment, derived config and complete result are retained in `results/profiling-20261001T002110-111626`.
The productive child has 4,008 samples; the complete file has 4,037.
Convolution has 948 productive-child samples (23.65%); AWGN has 943 (23.53%).
These are nearest Python-frame classifications of native samples, not exclusive
native-symbol costs or performance measurements.

py-spy returned exit 1 with `No child process (os error 10)` after reporting
that it wrote all 4,037 samples, with one sampling error. The simulator completed
all 4,096 batches and its output passed the strict result boundary. Both the
failure and complete artifacts are retained; the round was not rerun.
The upstream [shutdown race report](https://github.com/benfred/py-spy/issues/759)
describes the same symptom; that is supporting context, not proof of the exact
local cause. Version 0.4.2's [release notes](https://github.com/benfred/py-spy/releases/tag/v0.4.2)
confirm Python 3.14 support.

Direct convolution reuses one product array through NumPy multiply/add `out=`.
The eight tap passes retain their order. PCG64, batched shapes and all numeric
conventions are unchanged. The workspace is batch-sized and local to one call;
full cross-stage worker buffer reuse remains outside this lecture revision.

### M8 numerical acceptance

make test passed 29 E2E/contract/inference checks in 292.222 seconds. Independent
golden signals pass. All 64 retained real before/after counter records agree,
including each implementation's 4,096-batch load. make validate recollected the
unchanged fixed protocol: zero incompatible cases, 32 insufficient sparse AWGN
points, and no equivalence claim. Raw validation is
results/validation-20261001T003344-116836. The shared profile freezes only the
planned perf batch count at 2048; C++ CPU-2 calibration measured 8.856117789 s.
All other contract values and dependency lockfiles remain unchanged.

### M8 review corrections

The review corrected stale calibration prose without changing schema constraints.
The shared pre-calibration test now explicitly sets its null fixture after the
main profile is frozen. The profiling launcher did not pin its own CPU despite
recording CPU 0; original observations and metadata-corrections.json preserve
that provenance defect. Each profiler/simulator was correctly pinned to CPU 2.
No profiler round was repeated. A CPU-0-pinned launcher verified the same frozen
C++ workload at 7.842908383 s; bench/NOTES.md records the full correction cycle.

## Code-only continuation

The user deferred comparison experiments. The shared make check target validates
this implementation's golden CLI without random comparison collection; no new
DSP, RNG, contract or dependency change was made. The shared planner has a true
non-executing path. Report input now rejects stale fingerprints, differing loads
and incomplete collections before output, and separates performance metrics from
stage/BER counters. bench/NOTES.md records the shared defects and corrections.
The interrupted M9 run is retained as incomplete, not a performance conclusion.
