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
