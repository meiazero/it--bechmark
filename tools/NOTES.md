# M1 contract findings

M1 adds the frozen numerical profile, configuration/result schemas, invalid input
fixtures, standard-library golden generator, exact theory tables, and verifier.
All authored files use American English. The existing Portuguese plan and M0
implementation are preserved.

## Contract choices and scope

The explicit pilot sequence, master seed 20260930, and stage repetition count 100
were unspecified initial values in the plan and are recorded in the profile.
PDP values are stored with 17 significant digits. The batch remains 256, the
payload remains 672 bits, and nominal symbol energy remains 216.

At M1, `perf.n_batches` was null pending C++ timing calibration, and the validator
rejected that uncalibrated input in perf mode. M8 now freezes the main-profile
count at 2048 after measured CPU-2 work exceeded five seconds; derived null
configurations remain invalid in perf mode. Golden records have a
deterministic-case branch in the result schema;
BER/perf/stages have the point/counter branch described in the plan.

No numerical contract deviation or simulator optimization was applied. SciPy
(with transitive NumPy) is the only new runtime dependency and is listed in the
plan. psutil and matplotlib are deferred until their harness/analysis consumers
exist. Golden generation and verification require only the standard library.

## Defects caught during M1

An early ZF fixture paired a tiny nonzero estimate with a unit-amplitude input,
producing a value around 10^15. Absolute tolerance 10^-12 at that magnitude is
smaller than one binary64 rounding step. The input was reduced to the same scale
as the estimate, retaining the exact-zero/epsilon distinction with unit output.
This was corrected during fixture review, before freezing the generated files;
no simulator behavior or tolerance was changed.

The verifier compares seeds and all integer outputs without converting them to
floating point. Its self-test changes a u64 answer by one and requires failure,
preventing silent loss of precision above 2^53. Complex errors use magnitude,
not separate per-component bounds.

A negative verifier self-test exposed an overly broad tolerance on the complete
chain: `Verifier self-test accepted out-of-tolerance end_to_end`. The checker now
applies 10^-11 only to FFT/IFFT outputs, retaining 10^-12 for the grid and other
stages as required by the plan. The regression is covered by the self-test.

## Acceptance

`make golden` regenerates eleven deterministic cases and sixteen theory
points, then executes the verifier's positive and negative self-tests.
`make test` checks the reference validator's invalid-input exit behavior,
analytic numerical identities, file-byte hashes, CLI workers, closed-form
theory cross-checks, and the existing M0 environment checks. These checks do not
establish correctness of any competitor implementation; M2 has not started.

## September 30 M1 review corrections

The old mise environment/tasks coupled version management to execution. The root
Makefile now exports the four required environment variables and provides
`doctor`, `golden`, and `test`. The environment checker enforces those values
independently of mise and checks `nlohmann-json3-dev=3.11.3-1`.

Worker count had two sources of truth, in the configuration and CLI. It is now
CLI-only. Both reference CLIs validate worker counts; the golden verifier uses
its `--workers` value for metadata checks. The former zero/fractional-worker
configuration fixtures are covered by CLI rejection tests instead. Configuration
validators reject any `workers` field as an unknown key.

The old hash required other languages to reproduce CPython's JSON serialization.
It now hashes the exact file bytes. The verifier reads the bytes once for both
parsing and hashing. Its CLI regression test accepts equivalent configurations
with different formatting and hashes, rejects a changed file with stale result
metadata, and rejects mismatched worker metadata.

The original DFT formed large angles for every `(k, n)` pair. A differential
check against the installed SciPy FFT reproduced maximum absolute errors of
1.7013e-13 forward and 1.7242e-13 inverse on the dense 256-sample fixture.
Twiddles now use `(k * n) mod N`; the same regression requires error below
1e-14 and measured 6.2804e-16 in both directions, without changing implementation
verification tolerances. All golden files were regenerated. Two successive
`make golden` runs reproduced all eleven golden files and the theory file
byte-for-byte. SciPy remains confined to theory and tool checks.

No simulator optimization or profiling round was performed.
