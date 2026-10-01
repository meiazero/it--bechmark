# M0 environment findings

Verified on September 30, 2026, against the installed Ubuntu packages. This file
records environment findings, review corrections, and the M2 C++ workload.

## M2 implementation and acceptance

The C++ executable implements all four CLI modes with IT++ unitary FFTs, direct
time convolution, Gray table decisions, signed-bin interpolation, and exact-zero
ZF. A persistent thread pool draws one batch per atomic queue entry. Integer
results are consumed in batch order; speculative results beyond the stopping
batch are discarded. Four independent warmup batches are excluded from counts.
Configuration validation happens before output creation; output replacement is
atomic. Metadata utilities (`git` and coreutils `sha256sum`) run only during setup,
without a shell, and hash the exact parsed bytes. No library dependency was added.

### RNG fallback evidence

`tests/seed_state_probe.cpp` fills all 769 IT++ state words with consecutive
SplitMix64 outputs and restores that state. The installed DSFMT generator accepts
the state but produces 1,000 invalid uniform/Gaussian draw pairs out of 1,000.
Arbitrary words do not satisfy its floating-point state representation. Reproduce:

```sh
g++ -std=c++20 impl/cpp/tests/seed_state_probe.cpp -o /tmp/ofdm-seed-probe $(pkg-config --cflags --libs itpp)
timeout 5 /tmp/ofdm-seed-probe
```

Observed output: `words=769`, `invalid_draws=1000`, exit 1. The plan's explicitly
authorized fallback therefore uses `std::mt19937_64` and
`std::normal_distribution<double>` for every production random draw. Every batch
reseeds the full generator and resets the normal distribution's cached value.
The acceptance checks repeat a seed exactly and change only its upper 32 bits.
This RNG difference must remain visible in the final report and stage timings.

### Acceptance cycle 1

Failure boundaries were listed in the E2E test before implementation. `make
test-cpp` passed all eleven golden cases, all 25 invalid configurations, malformed
JSON and worker CLI cases, raw-byte fingerprints, BER/perf determinism with one
and four workers, stopping at both target errors and max bits, high seed bits,
diagnostic channels, and the complete stage output. Artifacts are retained under
`results/acceptance/cpp/`. No theory test, calibration, or profiler round was run.

### Pending for Phase 2

The M4 independent review identified a shared stage issue: `channel_conv` draws
new taps inside the timed repetition instead of using a pregenerated tap batch.
This historical finding is resolved by the lecture refactor below.
M7 will recheck the completed implementations before performance reporting.

Symbol-sized vectors allocate inside the batch; this deliberate initial ceiling
is recorded in the `ponytail:` comment. M8 may optimize only profiler-supported
hotspots. No performance claim is made from acceptance timings.

### Acceptance cycle 2

Independent review found that comparing aggregate BER after changing upper seed
bits did not prove distinct random sequences. Added a native sequence check using
the same production seed method, covering exact repeatability and distinct bits,
taps, and noise when only the upper 32 seed bits change. The retained artifact is
`results/acceptance/cpp/seed64.json`. The first review found no other blocker.
The fresh second review confirmed this correction and reported no findings.
`make golden` and the complete `make test` passed (22 checks) after the correction.

## Reproduce

From the repository root:

```sh
mise trust mise.toml
mise install
make doctor
make test
```

`doctor` rejects missing tools, mismatched versions, uninstalled development
packages, incorrect thread environment variables, and a missing Git repository.
It compiles the native probe in a temporary directory, runs it with a timeout,
and removes the executable on exit. No additional Python dependency is required.
The root Makefile provides `doctor`, `golden`, and `test`. Targets for later
milestones will be added with their implementations.

## Installed environment

| Component | Verified version |
|---|---|
| Python | 3.14.7 |
| uv | 0.12.20 |
| Julia | 1.13.1 |
| Rust | 1.98.1 |
| CMake | 4.4.3 |
| Ninja | 1.13.2 |
| tokei | 15.0.0 |
| g++ compiler | 13.3.0 |
| libitpp-dev | 4.3.1-10build1 |
| libfftw3-dev | 3.3.10-1ubuntu3 |
| nlohmann-json3-dev | 3.11.3-1 |
| pkg-config: itpp / fftw3 | 4.3.1 / 3.3.10 |

`OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, and `MKL_NUM_THREADS` are `1`;
`PYTHONHASHSEED` is `0`. The Makefile exports these to its child processes.

The `g++` metapackage reports `4:13.2.0-7ubuntu1`; this is not the compiler
version. The checker uses `g++ -dumpfullversion -dumpversion` to enforce 13.3.0.
The three development packages are checked by their exact installed package
versions, including distribution revisions, as required by the plan.

## FFTW planning and scaling

`impl/cpp/tests/environment_probe.cpp` interposes `fftw_plan_dft_1d` and forwards
the calls to the real FFTW planner using `dlsym(RTLD_NEXT, ...)`. This observes
the actual installed IT++ binary rather than relying on another source build.

For a complex transform of size 256, both directions pass flags **64**:
`FFTW_ESTIMATE`, with no additional flag bits. Julia must use
`flags=FFTW.ESTIMATE` when creating its plans. The checker fails if these flags
change, so the recorded finding cannot silently become stale.

An impulse produces an unscaled all-ones forward transform; the inverse of that
spectrum recovers the impulse. Maximum absolute error observed: **0**. This
confirms the plan's IT++ scaling adjustment: multiply `fft` by `1/sqrt(N)` and
`ifft` by `sqrt(N)` to obtain unitary transforms.

## IT++ RNG thread independence

The probe uses **two `std::thread` workers**, not an OpenMP parallel region.
Both call `itpp::RNG_reset(4257)` and generate binary, real Gaussian, and complex
Gaussian samples. Barriers alternate draws between workers; each sequence is
compared exactly with a serial reference. Halfway through, only worker 1 resets
its RNG to seed 9182. Worker 0 must retain its original sequence, while worker 1
must match a separately reseeded serial reference.

The experiment runs eight times with fresh threads, 64 draws per worker per
repetition. Each draw contains 16 samples of each of the three types. Results:

- Same seed in two threads matches the serial reference: **true**.
- Reseeding one thread preserves the other thread's state: **true**.

The installed library therefore passed the required thread-state experiment.
The plan's concurrency-based fallback to `std::mt19937_64` was not triggered.
This test establishes reproducible state independence for these calls and this
build; it is not a general proof that all IT++ objects may be shared by threads.

The installed declaration in `/usr/include/itpp/base/random.h` is
`RNG_reset(unsigned int seed)`, and `unsigned int` has **32 bits** on this build.
M2 must resolve initialization from the contract's full `u64` batch seed without
silent truncation. M0 does not introduce a seed conversion or change the
contract. The installed header also provides `RNG_set_state(const ivec&)`;
whether it can satisfy the full seed contract has not been tested here.

Observed probe output:

```json
{"fft_scaling_max_abs_error": 0, "fftw_backward_flags": 64, "fftw_forward_flags": 64, "rng_cross_thread_reseed_independent": true, "rng_same_seed_two_threads_match": true, "rng_seed_bits": 32}
```

## Scope limits and deviations

No numerical contract deviation or simulator optimization was applied. No
production library was added. The probe uses C++20 barriers and POSIX dynamic
symbol lookup, both available in the specified compiler/Linux environment.

The plan mentions calibrating `perf.n_batches` in M0, but assigns the complete
C++ workload to M2. A five-second end-to-end calibration cannot be measured
before that workload exists. No batch count, timing estimate, or performance
result has been invented or frozen. Calibration remains pending for the real
workload; this does not affect the explicit M0 environment acceptance command.

The apt IT++ library uses distribution build flags. Compiling the probe with
`-O3 -march=native` does not rebuild or optimize that library; the plan's threat
to validity remains applicable to the later C++ benchmark.

## M1 review corrections

The root Makefile replaces mise tasks and exports the four required environment
variables. The checker no longer reads an `[env]` section from mise.toml and now
requires `nlohmann-json3-dev=3.11.3-1`; that package version was verified with
`dpkg-query` during the correction pass.

The shared configuration no longer contains `workers`; it is CLI-only, including
the golden verifier's metadata checks. Configuration fingerprints now hash the
exact file bytes rather than a CPython-specific JSON serialization. C++ must hash
the same bytes it parses and record the CLI worker count separately.

The reference DFT now indexes twiddles by `(k * n) mod N`. Golden files were
regenerated without changing verification tolerances. The dense transform error
against the installed SciPy FFT decreased from approximately 1.72e-13 to
6.28e-16. This is a reference-data correction, not a C++ profiler optimization.

During this pass, `make doctor` failed in the noninteractive validation shell:
`FAIL uv: expected 0.12.20, found 0.10.4`. A PATH-only adjustment exposed the same
issue for Rust (`1.93.1` instead of `1.98.1`). The required versions are installed,
but shell activation did not select them consistently. No system installation,
shell configuration, or version pin was changed. M1 acceptance uses `make golden`
and `make test`; a new successful doctor run is not claimed.

## Undo local setup

To remove only the mise versions installed for this milestone:

```sh
mise uninstall python@3.14.7 uv@0.12.20 julia@1.13.1 rust@1.98.1 cmake@4.4.3 ninja@1.13.2 tokei@15.0.0
```

To remove trust for this repository's configuration:

```sh
mise untrust mise.toml
```

No system package, governor, turbo, service, or persistent PATH setting was changed.

## Lecture refactor — September 30, 2026

The user requested a readable academic treatment of the existing implementations.
`DspConfig` now converts the validated JSON to numeric geometry during setup: FFT
indices, pilot values, interpolation brackets/weights, and tap standard deviations.
The symbol loop no longer parses JSON, searches fixed pilot bins, or recalculates
tap scales. This brings its setup/work separation in line with Python and Rust;
no profiler round or speedup measurement was performed. A small retained geometry
allocation replaces repeated invariant work. Symbol-sized temporary buffers remain.

The OFDM pipeline now names transmit/receive signals explicitly and uses constants
for the frozen dimensions. Comments explain unitary FFT scaling and the unscaled
channel DFT. The pending stage defect is resolved: `channel_conv` reuses retained
taps and excludes their RNG cost. Tap generation remains inside end-to-end work.
No algorithm, draw order, contract value, schema, or dependency changed.

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

The review noted a backend lifetime distinction: C++ calls the IT++ FFT function
interface and pre-exercises both directions during setup; Rust retains explicit
plan and scratch objects. M0 verifies FFTW flags and scaling, not plan reuse or
lifetime. M8 should observe that behavior before interpreting backend overhead.
No unverified claim about an internal IT++ cache is made.

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

One perf 7.1.5 round used cpu-clock:u at 99 Hz with DWARF call stacks,
4,096 batches, one worker, CPU 2, and turbo on. The raw data, command,
environment, derived config, result and flat report are retained in
`results/profiling-20261001T002110-111626`. There were 1,693 samples. Self costs included normal draws
33.85%, direct convolution 13.23%, and demapping 6.73%. Sampling proportions
are diagnostics, not a before/after speedup measurement.

Convolution now visits contiguous samples for each tap. Each output still sums
in ascending tap order; the RNG sequence, normalization, receive window and
contract are unchanged. The standard normal generator remains unchanged:
replacing it would conflate optimization with the documented RNG difference.
Symbol-sized temporary vectors remain for the lecture's readable pipeline.

No FFTW planner symbol appeared among sampled hotspots. Absence of samples
cannot establish plan reuse, so the existing interposition probe now counts
actual planner calls across 101 transforms per direction and checks repeated
impulse recovery. On this installed binary, one forward and one backward plan
were observed. This establishes reuse for this process, size and call sequence;
it does not prove all library interfaces or concurrent plan lifetimes.

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
