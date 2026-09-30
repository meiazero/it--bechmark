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
