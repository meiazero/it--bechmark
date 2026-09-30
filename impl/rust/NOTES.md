# M4 implementation notes

The Rust implementation uses safe code, rustfft plans created once per persistent
Rayon worker, full-u64 `SmallRng::seed_from_u64`, and `StandardNormal`. The release
profile enables optimization level 3, fat LTO, one codegen unit, and abort on panic.
The root `.cargo/config.toml` selects the native CPU; the Makefile invokes Cargo
from the repository root so the configuration is effective. No dependency beyond
the plan's seven crates was added; Cargo.lock pins all transitive dependencies.

## Design and failure boundaries

The shared artifact-producing E2E scenario was registered before implementation.
It exercises golden, configuration/CLI rejection, raw byte hashes, ordered BER
stopping, diagnostic channels, all measurement modes, repeatability, and workers.
Serde's JSON parser is extended with a visitor that rejects duplicate object keys
and non-finite floats while retaining integer precision. This is validation at
the parser boundary, not a hand-written JSON parser.

Each Rayon thread creates its own DSP worker in the pool startup handler and
signals readiness before setup ends. `with_max_len(1)` creates one batch per
scheduled task. Results are collected in index order, and extra stopping batches
are discarded. Four independent warmup batches are excluded. SHA-256 uses the
native coreutils utility on the exact byte buffer already parsed, without a shell.
Output is replaced atomically after work.

## Acceptance cycle 1

The compiler caught `with_max_len` on a `u64` range: Rayon does not implement the
indexed iterator trait for that range. The scheduling window now uses a local
`usize` index and adds it to the `u64` batch index when deriving the seed. The
fixed batch count and counters remain `u64`; no seed truncation occurs.
Clippy requested fixed-array chunk APIs for the QAM and CLI loops; both now use
`as_chunks` without changing the mapping or accepted inputs.

The pinned rustfft process/scratch APIs and rand/rand_distr implementations were
inspected before coding. Acceptance evidence is retained in
`results/acceptance/rust/`. No profiler round, theory comparison, or calibration
was performed.

## Pending for Phase 2

Fresh review found no blocker and one nonblocking cross-language stage issue:
`channel_conv` draws new taps inside each measured repetition instead of retaining
the pregenerated tap batch. The same pattern exists in C++ and Python. M7 must
resolve the isolated-stage input rule consistently across all four versions.
`make golden` and `make test` passed all 24 checks; formatting and Clippy with
warnings denied passed after the fixed-array chunk change.

Symbol-sized DSP allocations are the deliberate initial ceiling named by the
source's `ponytail:` comment. Only the M8 profiler round can justify replacing
measured hotspots. No speed claim follows from E2E timings.
