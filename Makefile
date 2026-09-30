export OMP_NUM_THREADS := 1
export OPENBLAS_NUM_THREADS := 1
export MKL_NUM_THREADS := 1
export PYTHONHASHSEED := 0

.PHONY: doctor golden test build-cpp test-cpp build-python test-python
.PHONY: build-rust test-rust

doctor:
	python tools/check_system.py

golden:
	python -m tools.golden.generate
	uv run --project tools --locked python tools/theory.py
	python tools/check_golden.py --self-test

test: build-cpp build-python build-rust
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
