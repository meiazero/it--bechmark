# OFDM benchmark: IT++ vs Python, Julia, Rust

`PLANO_BENCHMARK_OFDM.md` is the spec (in PT-BR). Read it before any change; its milestone table defines scope and acceptance.

## Rules

- `contract/` is the source of truth. Never change contract values; if one cannot be met, stop and report with evidence.
- One milestone per PR. A milestone is done only when its acceptance command passes.
- No stubs, TODOs, or disabled tests. Report a failing test with its output.
- No dependencies beyond those listed in the plan without a written justification in the PR.
- Log every contract deviation, bug found, and optimization applied in `impl/<lang>/NOTES.md`.
- `tools/golden/` uses the Python stdlib only and never imports any competing implementation.
- Fairness rules (allowed/forbidden per language, build flags, one profiling round each) are in the plan's "Regras de implementação idiomática" section.

## Environment

mise is only a language/tool version manager: `mise.toml` holds `[tools]` and nothing else. Never add `[env]` or `[tasks]`, and never use `mise run` or `mise exec`. Tasks and environment variables live in the root `Makefile` (thread variables via `export`). System packages (`libitpp-dev`, `libfftw3-dev`, `nlohmann-json3-dev`, `g++`) are pinned and checked by `tools/check_system.py`.

```sh
make doctor   # verify toolchain and probe IT++
make golden   # regenerate golden vectors and theory curves, run the verifier self-test
make test     # tool and contract tests
```

## Known facts (verified in M0, see `impl/cpp/NOTES.md`)

- IT++ `fft` is unscaled and `ifft` scales by `1/N`; the contract requires unitary transforms.
- IT++ plans FFTW with `FFTW_ESTIMATE`; Julia must use `flags=FFTW.ESTIMATE`.
- IT++ RNG state is per thread, but `RNG_reset` takes 32 bits; never truncate the 64-bit batch seed.
- The CPU is hybrid: P-cores are logical CPUs 0–3, E-cores are 4–11. Scaling runs use E-cores only.

## Tests

1. Never write unit tests after writing the code.
2. End-to-end (E2E) tests are the main way to test; use them to check that complex
   features work. Each E2E test produces an artifact that can be checked and reproduced.
3. For complex features, use realistic E2E scenarios of medium or high complexity, not
   only the simplest successful case.
4. Testing a system in isolation: first list every way it could fail, then write the code.
5. No tautological tests (confirming what the code already says) and no tests that only
   detect whether code changed.
6. Bug fixes get a regression test only when existing behavior tests leave a real gap.



## Output language

Code, comments, commits, and `NOTES.md` in American English. The final report, figures, and table labels in PT-BR.
