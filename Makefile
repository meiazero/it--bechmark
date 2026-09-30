export OMP_NUM_THREADS := 1
export OPENBLAS_NUM_THREADS := 1
export MKL_NUM_THREADS := 1
export PYTHONHASHSEED := 0

.PHONY: doctor golden test

doctor:
	python tools/check_system.py

golden:
	python -m tools.golden.generate
	uv run --project tools --locked python tools/theory.py
	python tools/check_golden.py --self-test

test:
	uv run --project tools --locked python -m unittest discover -s tools -p 'test_*.py' -v
