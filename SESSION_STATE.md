# Session state: M4 complete; lecture refactor

Updated September 30, 2026. The current request revises the plan and refactors
the existing C++/Python/Rust code for an optimization and telecommunications
lecture. The next implementation milestone remains **M5 Julia**.
`LECTURE.md` contains the executable teaching route and derivations.

## Completed milestone commits

| Milestone | Commit | Verified outcome |
|---|---|---|
| M2 C++/IT++ | `0616983` | Four modes, eleven golden cases, invalid configurations, direct full-u64 RNG sequence check, deterministic counts with one/four workers |
| M3 Python | `bfdfbfe` | Batched NumPy, PCG64, persistent forkserver process pool, same CLI/golden/determinism acceptance |
| M4 Rust | `5347f68` | Safe Rust, rustfft, SmallRng/StandardNormal, persistent Rayon workers, same CLI/golden/determinism acceptance |

Each milestone passed acceptance and an independent read-only explorer review
before its commit. M2 required two review cycles: the first requested a direct
RNG sequence test instead of comparing aggregate BER; the second approved it.
M3 had no review findings. M4 had no blockers and the shared stage finding below.

Final verification: `make golden` and `make test` passed **24 tests**. Rust
formatting and Clippy with `-D warnings` passed. Python and shared E2E test files
passed Ruff 0.16.9 formatting/lint checks using an already cached executable.
No statistical simulator/theory validation, profiler round, calibration, complete
benchmark, harness, or report has been performed yet.

## Lecture refactor validation

`make doctor`, `make golden`, and all 24 tests passed. Ruff and Rust formatting
checks passed; Clippy passed with warnings denied. `results/refactor/verify.py`
compares 30 retained CLI artifacts against the pre-refactor snapshot: all numeric
outputs and metadata match exactly when timing fields are excluded. Evidence is
local in `results/refactor/comparison.json`; acceptance remains reproducible with
`make test`. The frozen contract and lockfiles are unchanged. Independent read-only explorer
review found no blocker; the IT++ plan lifetime distinction is recorded for M8.
Changes remain uncommitted on the observed `master` branch.

## Evidence and implementation details

- E2E artifacts are retained under `results/acceptance/{cpp,python,rust}/`.
  This directory and build/virtual environments are ignored by Git and remain
  local. Acceptance commands can regenerate them; they are not published data.
- Detailed decisions, defects, review cycles, and pending findings are recorded
  in each implementation's `NOTES.md`.
- Arbitrary SplitMix64-filled IT++ RNG state produced 1,000 invalid draws out of
  1,000. C++ therefore uses the plan's authorized `std::mt19937_64` fallback for
  all random draws. `impl/cpp/tests/seed_state_probe.cpp` reproduces the failure;
  `seed64_check.cpp` directly proves repeated/full-u64 bit, tap, and noise sequences.
- Configurations hash their exact input bytes. Worker count remains CLI-only.
  Workers initialize before setup ends; four independent warmup batches are
  excluded; BER aggregation consumes batch results in index order.
- `perf.n_batches` remains null in the frozen profile. Acceptance derives small
  configurations outside `contract/`; calibration belongs to M8.

## Pending for M7

M4 review identified that `channel_conv` in C++, Python, and Rust generates fresh
taps inside the timed stage instead of using a retained pregenerated tap batch.
The review classified this as nonblocking for Phase 1. It is recorded in all
three `NOTES.md` files and is resolved in the three existing implementations
by the current lecture refactor before any performance claim. M7 will recheck
Julia and the harness. Symbol-sized allocations in C++ and Rust
are deliberate initial ceilings; optimization requires the one M8 profiler round.

## Resume implementation milestones

Read `AGENTS.md`, `PLANO_BENCHMARK_OFDM.md`, and this file; verify the current Git
state before changing anything. The current task is the lecture refactor,
not completion of the remaining
milestones. Confirm the active request before resuming M5–M10. The observed
branch is `master`; milestone instructions request `main`, so establish the
intended branch before making future milestone commits.

1. In a noninteractive Bash shell, activate the pinned toolchain:
   `eval "$(mise env -s bash)"`.
2. Run `make doctor` to recheck the environment after the restart.
3. Implement M5 Julia with FFTW.ESTIMATE, Xoshiro, typed buffers, and thread tasks;
   add its acceptance scenario before the implementation.
4. Continue M6 harness/smoke analysis, M7 validation/corrections, M8 profiling and
   calibration, M9 full measurements, and M10 report under the current plan.

No system package, persistent PATH, governor, or turbo setting was changed in
this session. The last observed `no_turbo` value was 0 and its sysfs file was
owned by root. Recheck it when the primary measurement requires disabling turbo;
changing it may require the user action specified by the plan's stop conditions.
