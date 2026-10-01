export OMP_NUM_THREADS := 1
export OPENBLAS_NUM_THREADS := 1
export MKL_NUM_THREADS := 1
export PYTHONHASHSEED := 0

.PHONY: doctor golden test build-cpp test-cpp build-python test-python
.PHONY: build-rust test-rust
.PHONY: build-julia test-julia
.PHONY: bench bench-plan check analyze test-bench validate

doctor:
	python tools/check_system.py

golden:
	python -m tools.golden.generate
	uv run --project tools --locked python tools/theory.py
	python tools/check_golden.py --self-test

test: build-cpp build-python build-rust build-julia
	uv run --project tools --locked python -m unittest discover -s tools -p 'test_*.py' -v

build-cpp:
	cmake -S impl/cpp -B build/cpp -G Ninja -DCMAKE_BUILD_TYPE=Release
	cmake --build build/cpp

test-cpp: build-cpp
	uv run --project tools --locked python -m unittest discover -s tools -p test_implementations.py -k cpp -v

build-python:
	uv sync --project impl/python --locked

test-python: build-python
	uv run --project tools --locked python -m unittest discover -s tools -p test_implementations.py -k python -v

build-rust:
	cargo build --manifest-path impl/rust/Cargo.toml --release --locked --target-dir build/rust

test-rust: build-rust
	uv run --project tools --locked python -m unittest discover -s tools -p test_implementations.py -k rust -v

build-julia:
	julia --startup-file=no --project=impl/julia -e 'using Pkg; Pkg.instantiate(); Pkg.precompile()'

test-julia: build-julia
	uv run --project tools --locked python -m unittest discover -s tools -p test_implementations.py -k julia -v

bench: build-cpp build-python build-rust build-julia
	uv run --project tools --locked python -m bench --suite $(or $(SUITE),smoke) $(if $(filter on,$(TURBO)),--turbo-check)

bench-plan: SUITE ?= single,scaling,memory,stages
bench-plan:
	uv run --project tools --locked python -m bench --suite $(SUITE) $(if $(filter on,$(TURBO)),--turbo-check) --dry-run

check: build-cpp build-python build-rust build-julia
	uv run --project tools --locked python -m unittest discover -s tools -p test_contract.py -v
	uv run --project tools --locked python -m unittest discover -s tools -p test_stats.py -v
	uv run --project tools --locked python -m unittest discover -s tools -p test_bench_plan.py -v
	uv run --project tools --locked python -m unittest discover -s tools -p test_code_golden.py -v
	uv run --project tools --locked python -m unittest discover -s tools -p test_analysis_boundaries.py -v

analyze:
	uv run --project tools --locked python -m bench.analyze $(if $(RUN),--run $(RUN))

test-bench: build-cpp build-python build-rust build-julia
	uv run --project tools --locked python -m unittest discover -s tools -p test_bench.py -v

validate: build-cpp build-python build-rust build-julia
	uv run --project tools --locked python -m bench.validate
