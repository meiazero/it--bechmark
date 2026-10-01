# Julia implementation notes

## M5 design and failure boundaries

The shared artifact-producing acceptance scenario was added before the simulator.
Failure boundaries include malformed/duplicate JSON, nonfinite numbers, geometry
changes, full-u64 seeds, raw-byte configuration hashes, exact-zero ZF, adaptive
stopping order, invalid CLI workers, and contamination between setup/warmup/work.

The implementation uses only the planned FFTW.jl and JSON3.jl dependencies plus
Julia standard libraries. Project.toml and Manifest.toml retain the resolved
versions. FFTW uses its default FFTW provider, ESTIMATE planning, and one internal
thread; BLAS also uses one thread. Forward/backward signal transforms divide by
sqrt(256); the channel response remains an unscaled forward transform.

Each persistent worker owns Xoshiro state and concrete FFT plan types. A shared
atomic index dispatches one batch per task. Results are stored by batch index and
aggregated in order; speculative batches beyond the BER stopping index are
ignored. Only integer counters are reduced, with checked u64 addition.

The teaching path advances one OFDM symbol at a time, naming the transmit grid,
time signal, prefix, channel taps, receive grid, estimates, and decisions.
Symbol-sized temporaries are the initial ceiling, documented with ponytail.
No profiler round or speedup claim has been made. Isolated convolution consumes
retained taps; tap generation is included in complete simulation work. Stage
inputs and timing dispatch are exercised during warmup before measurement.

## JSON integer boundary correction

A local probe found that JSON3's default reader returns Float64 above Int64,
and its typed UInt64 reader converts 1.5 to 1 and -1 to typemax(UInt64).
The documented JSON3.RawType extension retains numeric tokens; Julia's BigInt
parser and explicit lexical/range checks preserve exact integer values.
JSON parsing itself remains delegated to JSON3. No custom JSON parser or new
dependency was added. Iterating JSON3.Object pairs preserves duplicate keys,
which allows recursive duplicate rejection before typed extraction.

## Acceptance and review

Artifacts are retained under results/acceptance/julia. The shared E2E checks all
eleven golden cases, every invalid fixture, malformed input and CLI workers,
raw CRLF configuration hashing, full-u64 golden seed inputs, BER repeatability,
worker-independent counts, fixed performance work, finite positive stages,
and AWGN/perfect-CSI diagnostics. Acceptance and independent review outcomes
are appended after their actual completion.

## Pending for Phase 2

M7 rechecks numerical/statistical behavior and JIT phase boundaries across all
four implementations. M8 owns the one permitted profiler round. The Julia FFTW
artifact is 3.3.12 while the system C++ FFTW is 3.3.10; this backend difference
must remain visible in the measurement metadata and final report.

### M5 closure

make test-julia passed the artifact-producing E2E in 149.117 seconds. make golden
and the complete make test passed (25 tests in 151.765 seconds). A fresh read-only
Luna explorer review found no blocking finding and confirmed that acceptance
proves the declared M5 behaviors. It did not claim statistical theory validation,
profiling, calibration, or complete benchmark results. No contract value changed.

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

One stdlib Profile round used a 0.01-second delay, 4,096 batches, one worker,
CPU 2 and turbo on. `bench/profile_julia.jl` first executes the same CLI workload
outside Profile to compile its dispatcher, clears samples, and profiles one
subsequent execute call. That includes its small setup/warmup phases as well as
work. It asserts unchanged integer counters and nonempty samples; raw instruction
pointers, resolved frames, flat report, config and command are retained in
`results/profiling-20261001T002110-111626`. No second profiler round was performed.

The profile has 1,442 snapshots. GenericMemory has 489 self snapshots (33.91%),
while backward/forward transform source lines occur in 132/100 snapshots.
Inclusive frame counts overlap and must not be added as a stage decomposition.
The FFT wrapper now scales its newly allocated result in place, removing the
second vector per signal transform. It still returns an independent output,
so retained stage fixtures and golden signals cannot alias a reused FFT buffer.
Xoshiro draw order, FFTW.ESTIMATE plans, scale and contract are unchanged.
Symbol-sized temporaries remain; no dependency or global bounds override was added.

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
