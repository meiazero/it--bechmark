# M0 environment findings

Verified on September 30, 2026, against the installed Ubuntu packages. The
benchmark plan and its numerical contract have not been changed. Only M0 is
implemented; there is no OFDM simulator or benchmark workload yet.

## Reproduce

From the repository root:

```sh
mise trust mise.toml
mise install
mise run doctor
mise run test
```

`doctor` rejects missing tools, mismatched versions, uninstalled development
packages, incorrect thread environment variables, and a missing Git repository.
It compiles the native probe in a temporary directory, runs it with a timeout,
and removes the executable on exit. No additional Python dependency is required.
Only the `doctor` and M0 `test` tasks are defined. Tasks for later milestones
will be added with their implementations.

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
| pkg-config: itpp / fftw3 | 4.3.1 / 3.3.10 |

`OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, and `MKL_NUM_THREADS` are `1`;
`PYTHONHASHSEED` is `0`. These are scoped to mise commands, not shell-wide settings.

The `g++` metapackage reports `4:13.2.0-7ubuntu1`; this is not the compiler
version. The checker uses `g++ -dumpfullversion -dumpversion` to enforce 13.3.0.
The two development packages are checked by their exact installed package
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
