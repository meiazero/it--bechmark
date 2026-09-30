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

Independent review reported no blocking or nonblocking findings. `make golden`
and `make test` passed all 23 checks. Ruff 0.16.9 was already available in the
local uv cache and was used for formatting and linting without adding any project
dependency. Final CLI exception handling names the expected runtime error classes.

No optimization has been applied. M8 will inspect one profiler round before
changing measured hotspots. Stage CP removal explicitly copies the slice to
measure the removal operation consistently with the other implementations.
