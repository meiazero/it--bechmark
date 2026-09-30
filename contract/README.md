# M1 numerical contract

`profile_main.json` is the authoritative main-profile configuration. Its geometry,
pilot sequence, stored PDP, energy, payload, batch size, and warmup count are fixed.
The seed, BER points and stopping parameters, channel (`rayleigh` or
`awgn`), CSI (`estimated` or `perfect`), and stage repetition count are configurable.
AWGN uses a single unit tap; the stored eight-tap PDP applies only to Rayleigh.
The fixed profile retains its geometry in both diagnostic channel modes.
Worker count is supplied only through `--workers`; it is never a configuration
field. CLI values must be positive integers in the u64 range.

The plan leaves three initial choices to M1: the explicit 24-value BPSK pilot
sequence, the default master seed (20260930), and stage repetitions (100). These
are now recorded. PDP entries were evaluated once from the specified exponential
formula and written with 17 significant digits. Implementations must read them,
not recompute them. Data and pilot arrays follow increasing signed-bin order;
FFT arrays use unshifted index order, `k mod 256`.

## Configuration and validation

`config.schema.json` and `result.schema.json` use JSON Schema Draft 2020-12.
Objects reject unknown keys. Inputs must also reject non-finite numbers and
duplicate JSON keys, even when a parser accepts them. Seeds and counters are
unsigned 64-bit integers, never floating-point approximations or booleans.
The frozen profile rejects all incompatible dimensions, including `N_cp < 7`.

JSON Schema cannot express all cross-field conditions. Native validators must
also enforce `max_bits >= min_batches * B * 672`, enough u64 headroom for the final
whole batch, and the selected mode's restrictions. Perfect CSI is diagnostic and
is rejected in `perf` and `stages` modes. `perf.n_batches` is intentionally null:
M8 measures the profiled C++ workload before filling and freezing it; until then,
tests and the M6 smoke suite use a derived copy outside `contract/`. Null is
valid for `golden` and `ber`, and invalid for `perf` execution. No performance
calibration has been invented.

Run the reference configuration checks with:

```sh
make test
```

Invalid configurations and invalid CLI worker counts exit 2, print an English
error to stderr, and print no result. Every file in `invalid_configs/` is a
complete standalone negative input,
except for deliberate missing/extra-field cases. `nonfinite_number.json` contains
the valid JSON numeric token `1e309`; a binary64 parser must reject its overflow.
Later native implementations must reject these files with exit 2 and no output
result file. M1 tests the reference validator, not those unbuilt implementations.

## Configuration fingerprint

`config_sha256` is the SHA-256 of the exact configuration file bytes read from
disk, including whitespace, key order, numeric spelling, and line endings.
Implementations must hash the same bytes they parse, without reserializing JSON.
The digest is lowercase hexadecimal. `tools/contract.py::config_sha256` accepts
those bytes. The verifier's `--config` must refer to the same file, and its
`--workers` must match the implementation's CLI worker count. Changing only
`--workers` leaves the configuration hash unchanged.

## Golden protocol

Regenerate the checked-in reference data and verify M1 with:

```sh
make golden
make test
```

The generator under `tools/golden/` imports only the Python standard library and
uses a direct O(N²) DFT with twiddles indexed by `(k * n) mod N`, avoiding
large-angle argument reduction. It never imports NumPy, SciPy, or competitor code.
Each `golden/*.json` contains `schema_version`, `profile_id`, `case_id`, `inputs`,
and `expected`. Complex vectors are arrays of `[real, imaginary]` binary64 pairs.
Bits and seed outputs are exact JSON integers.

The eleven cases cover QAM mapping; decisions at and near all thresholds on both
axes; grid construction and extraction; dense and impulse FFT/IFFT; CP operations;
truncated direct convolution and true frequency response; LS and interpolation
across DC; exact-zero ZF; N0 and full-u64 seed derivation; and a complete noiseless
multipath chain with both estimated and perfect CSI recovering all 672 bits.
The channel case retains exactly 288 samples. The ZF case includes a tiny nonzero
estimate to distinguish exact-zero handling from an epsilon cutoff.

Native `--mode golden` must consume the inputs in these files, compute all keys
listed in `expected`, and emit one JSON Lines record per case with:

```text
schema_version, impl, git_sha, mode, profile_id, config_sha256,
master_seed, workers, case_id, outputs
```

`outputs` has the same structure as `expected`. Its values must be computed by the
implementation, not copied from the reference. Case order is free. Missing,
duplicate, or unknown cases, extra/missing output keys, incorrect metadata, and
non-finite values fail verification. Integers are compared exactly (including
values above 2^53); complex errors use their magnitude. Absolute tolerance is
`1e-12`, with `1e-11` only for `fft`/`ifft` outputs in the transform cases and
`time`/`received_fft` in the complete chain. Other chain stages retain `1e-12`.
There is no relative tolerance. The verifier checks result content, not exit codes
or whether the implementation computed it independently.

```sh
python tools/check_golden.py --config contract/profile_main.json --workers 1 --actual path/to/cpp.jsonl
python tools/check_golden.py --workers 4 --actual path/to/cpp.jsonl --actual path/to/python.jsonl
```

The self-test and JSON Lines CLI test use synthetic envelopes around reference
values; they test the verifier, not a simulator. The self-test deliberately
corrupts outputs, u64 seeds, metadata, and case coverage and requires rejection.

## Measurement records

For `ber`, `perf`, and `stages`, the result schema requires the metadata in the
plan and one record per Eb/N0 point with the seven integer counters and three
phase durations. `status` is `target_errors` or `max_bits` for BER, `fixed_work`
for fixed workloads, or `timeout` for an interrupted workload. Full batches are
counted; `n_symbols = n_batches * 256` and `n_bits = n_symbols * 672`.
`n_errors <= n_bits` and `n_symbols_with_errors <= n_symbols`.
`sum_batch_errors_sq` is the sum of squared integer batch error counts, not a BER
estimate. Later result consumers must check these semantic relationships.

Only `stages` records contain `stage_ns_per_symbol`. Its twelve stage names match
the plan, plus `e2e` for the complete chain. Values are medians in nanoseconds per
OFDM symbol over `stages.repetitions`; setup and warmup are excluded. Golden
records have no Eb/N0 or work counters because they describe deterministic cases,
rather than a simulated BER point.

## Theory and sources

`theory/main.json` stores exact uncoded Gray 16-QAM BER for the main Eb/N0 grid:
AWGN and Rayleigh with perfect CSI, including the pilot/CP overhead through
`Es/N0 = (672/216) * 10^(EbN0_dB/10)`. AWGN sums Gaussian decision-region
probabilities weighted by Hamming distance, rather than using a nearest-neighbor
approximation. Rayleigh integrates that BER over unit-mean exponential channel
power and stores the quadrature error estimate. No estimated-CSI theoretical
curve or simulated BER result is claimed.

The independent checks compare both curves against closed forms: with
`Q(x) = erfc(x/sqrt(2))/2` and `a = sqrt(Es/N0/5)`, AWGN BER is
`3Q(a)/4 + Q(3a)/2 - Q(5a)/4`. Averaging each term over Rayleigh gives
`E[Q(c*a*sqrt(g))] = (1 - sqrt(c²a²/(c²a² + 2)))/2`.

Sources checked for M1:

- [SplitMix64 reference by Sebastiano Vigna](https://prng.di.unimi.it/splitmix64.c):
  addition and multiplication wrap modulo 2^64; `sm64(s)` is the first output
  after initializing state to `s`.
- [SciPy erfc documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.special.erfc.html)
  for Gaussian tails.
- [SciPy quad documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.integrate.quad.html)
  for integration on `[0, infinity)` and its error estimate.

Only SciPy is a direct M1 tools dependency. Its transitive NumPy dependency stays
in `tools/.venv`; neither is imported by the golden generator or a competitor.
`tools/uv.lock` pins both versions. No simulator, profiler optimization, benchmark
harness, or later-milestone acceptance test is implemented here.
