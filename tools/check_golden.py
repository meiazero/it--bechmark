import argparse
import copy
import math
import re
import sys
from pathlib import Path
from typing import Any

import contract

FFT_OUTPUTS = {
    "transforms": {"fft", "ifft"},
    "fft_impulse": {"fft", "ifft"},
    "end_to_end": {"time", "received_fft"},
}
METADATA = {
    "schema_version",
    "impl",
    "git_sha",
    "mode",
    "profile_id",
    "config_sha256",
    "master_seed",
    "workers",
    "case_id",
    "outputs",
}


def compare(expected: Any, actual: Any, tolerance: float, path: str) -> None:
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(expected) != set(actual):
            raise ValueError(f"{path}: object keys differ")
        for key in expected:
            compare(expected[key], actual[key], tolerance, f"{path}.{key}")
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            raise ValueError(f"{path}: array length differs")
        if len(expected) == 2 and all(type(value) is float for value in expected):
            if any(type(value) not in (int, float) for value in actual):
                raise ValueError(f"{path}: complex components must be numbers")
            difference = abs(complex(*expected) - complex(*actual))
            if not math.isfinite(difference) or difference > tolerance:
                raise ValueError(
                    f"{path}: complex absolute error {difference} > {tolerance}"
                )
        else:
            for index, (left, right) in enumerate(zip(expected, actual, strict=True)):
                compare(left, right, tolerance, f"{path}[{index}]")
    elif type(expected) is float:
        if type(actual) not in (int, float):
            raise ValueError(f"{path}: expected a number")
        difference = abs(expected - actual)
        if not math.isfinite(difference) or difference > tolerance:
            raise ValueError(f"{path}: absolute error {difference} > {tolerance}")
    elif type(expected) is not type(actual) or expected != actual:
        raise ValueError(f"{path}: expected {expected!r}, found {actual!r}")


def load_expected(directory: Path) -> dict[str, dict]:
    cases = {}
    for path in sorted(directory.glob("*.json")):
        vector = contract.load_json(path)
        case_id = vector["case_id"]
        if case_id in cases:
            raise ValueError(f"Duplicate reference case: {case_id}")
        cases[case_id] = vector
    if not cases:
        raise ValueError(f"No golden cases found in {directory}")
    return cases


def verify_records(
    records: list[dict],
    expected: dict[str, dict],
    config: dict,
    config_hash: str,
    workers: int,
) -> None:
    seen = set()
    implementation = None
    for record in records:
        contract.object_keys(record, METADATA, "golden record")
        contract.require_finite(record)
        case_id = record["case_id"]
        if not isinstance(case_id, str) or case_id not in expected:
            raise ValueError(f"Unknown golden case: {case_id!r}")
        if case_id in seen:
            raise ValueError(f"Duplicate actual case: {case_id}")
        seen.add(case_id)
        for name, value in {
            "schema_version": 1,
            "mode": "golden",
            "profile_id": config["profile_id"],
            "master_seed": config["master_seed"],
            "workers": workers,
            "config_sha256": config_hash,
        }.items():
            compare(value, record[name], 0, f"{case_id}.{name}")
        impl = record["impl"]
        if impl not in ("cpp", "python", "julia", "rust"):
            raise ValueError(f"{case_id}: invalid implementation")
        if implementation is not None and impl != implementation:
            raise ValueError(
                "A golden output file must contain exactly one implementation"
            )
        implementation = impl
        if (
            not isinstance(record["git_sha"], str)
            or re.fullmatch(r"([0-9a-f]{40}|[0-9a-f]{64})", record["git_sha"]) is None
        ):
            raise ValueError(f"{case_id}: invalid git_sha")
        if expected[case_id]["profile_id"] != config["profile_id"]:
            raise ValueError(f"{case_id}: reference profile differs")
        outputs = expected[case_id]["expected"]
        contract.object_keys(record["outputs"], set(outputs), f"{case_id}.outputs")
        for key, value in outputs.items():
            tolerance = 1e-11 if key in FFT_OUTPUTS.get(case_id, set()) else 1e-12
            compare(value, record["outputs"][key], tolerance, f"{case_id}.{key}")
    missing = set(expected) - seen
    if missing:
        raise ValueError(f"Missing golden cases: {sorted(missing)}")


def read_records(path: Path) -> list[dict]:
    records = []
    for index, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            raise ValueError(f"{path}:{index}: blank JSON Lines record")
        records.append(contract.parse_json(line))
    return records


def self_test(
    expected: dict[str, dict], config: dict, config_hash: str, workers: int
) -> None:
    records = [
        {
            "schema_version": 1,
            "impl": "python",
            "git_sha": "0" * 40,
            "mode": "golden",
            "profile_id": config["profile_id"],
            "config_sha256": config_hash,
            "master_seed": config["master_seed"],
            "workers": workers,
            "case_id": case_id,
            "outputs": copy.deepcopy(vector["expected"]),
        }
        for case_id, vector in expected.items()
    ]
    verify_records(records, expected, config, config_hash, workers)
    by_id = {record["case_id"]: index for index, record in enumerate(records)}

    def must_fail(changed: list[dict], label: str) -> None:
        try:
            verify_records(changed, expected, config, config_hash, workers)
        except ValueError, TypeError:
            return
        raise ValueError(f"Verifier self-test accepted {label}")

    for case_id, key, index, delta in (
        ("qam_map", "symbols", 0, 2e-12),
        ("transforms", "fft", 0, 2e-11),
        ("end_to_end", "spectrum", 0, 2e-12),
    ):
        changed = copy.deepcopy(records)
        changed[by_id[case_id]]["outputs"][key][index][0] += delta
        must_fail(changed, f"out-of-tolerance {case_id}")
        changed = copy.deepcopy(records)
        changed[by_id[case_id]]["outputs"][key][index][0] += delta / 8
        verify_records(changed, expected, config, config_hash, workers)
    changed = copy.deepcopy(records)
    changed[by_id["noise_seed"]]["outputs"]["splitmix_outputs"][0] += 1
    must_fail(changed, "one-bit u64 seed difference")
    changed = copy.deepcopy(records)
    changed[by_id["demap"]]["outputs"]["bits"][0] ^= 1
    must_fail(changed, "incorrect payload bit")
    changed = copy.deepcopy(records)
    changed[by_id["zf"]]["outputs"]["equalized"][0][0] = float("nan")
    must_fail(changed, "NaN")
    changed = copy.deepcopy(records)
    changed[by_id["zf"]]["outputs"]["zf_zero_count"] += 1
    must_fail(changed, "wrong ZF zero count")
    changed = copy.deepcopy(records)
    changed[0]["outputs"]["extra"] = 0
    must_fail(changed, "extra output key")
    changed = copy.deepcopy(records)
    changed[0]["config_sha256"] = "f" * 64
    must_fail(changed, "incorrect config hash")
    must_fail(records[:-1], "missing case")
    must_fail(records + records[:1], "duplicate case")
    print(
        f"PASS verifier self-test ({len(records)} cases; "
        "exact u64, bits and failure paths)"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check implementation golden JSON Lines"
    )
    parser.add_argument(
        "--expected", type=Path, default=contract.ROOT / "contract/golden"
    )
    parser.add_argument("--config", type=Path, default=contract.PROFILE)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--actual", type=Path, action="append", default=[])
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if not args.self_test and not args.actual:
        parser.error("provide --actual or --self-test")
    try:
        contract.integer(args.workers, "workers")
        config_bytes = args.config.read_bytes()
        config = contract.parse_json(config_bytes.decode("utf-8"))
        contract.validate_config(config, "golden")
        config_hash = contract.config_sha256(config_bytes)
    except (OSError, ValueError, TypeError, OverflowError) as error:
        print(f"Invalid configuration: {error}", file=sys.stderr)
        return 2
    try:
        expected = load_expected(args.expected)
        if args.self_test:
            self_test(expected, config, config_hash, args.workers)
        for path in args.actual:
            verify_records(
                read_records(path), expected, config, config_hash, args.workers
            )
            print(f"PASS {path}: {len(expected)} golden cases")
    except (OSError, ValueError, KeyError, TypeError, OverflowError) as error:
        print(f"FAIL golden: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
