import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "contract/profile_main.json"
U64_MAX = (1 << 64) - 1
FIXED_FIELDS = (
    "schema_version",
    "profile_id",
    "N_fft",
    "N_cp",
    "M",
    "active_bins",
    "pilot_bins",
    "data_bins",
    "pilots",
    "pdp",
    "E_sym",
    "bits_per_symbol",
    "B",
    "warmup_batches",
)


def reject_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON number: {value}")


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def require_finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("All numbers must be finite")
    if isinstance(value, dict):
        for item in value.values():
            require_finite(item)
    elif isinstance(value, list):
        for item in value:
            require_finite(item)


def parse_json(text: str) -> Any:
    value = json.loads(
        text, parse_constant=reject_constant, object_pairs_hook=unique_object
    )
    require_finite(value)
    return value


def load_json(path: Path) -> Any:
    return parse_json(path.read_text())


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def integer(value: Any, name: str, minimum: int = 1, maximum: int = U64_MAX) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer in [{minimum}, {maximum}]")


def number(value: Any, name: str) -> None:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")


def object_keys(value: Any, keys: set[str], name: str) -> None:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{name} must contain exactly {sorted(keys)}")


def validate_config(config: Any, mode: str | None = None) -> None:
    profile = load_json(PROFILE)
    object_keys(config, set(profile), "config")
    require_finite(config)
    for name in FIXED_FIELDS:
        if json.dumps(config[name]) != json.dumps(profile[name]):
            raise ValueError(f"{name} differs from the frozen main profile")
    integer(config["master_seed"], "master_seed", 0)
    if config["channel"] not in ("rayleigh", "awgn"):
        raise ValueError("channel must be rayleigh or awgn")
    if config["csi"] not in ("estimated", "perfect"):
        raise ValueError("csi must be estimated or perfect")
    object_keys(
        config["ber"], {"target_errors", "min_batches", "max_bits", "ebn0_db"}, "ber"
    )
    for name in ("target_errors", "min_batches", "max_bits"):
        integer(config["ber"][name], f"ber.{name}")
    points = config["ber"]["ebn0_db"]
    if not isinstance(points, list) or not points:
        raise ValueError("ber.ebn0_db must be a nonempty array")
    for point in points:
        number(point, "ber.ebn0_db entry")
    batch_bits = config["B"] * config["bits_per_symbol"]
    if config["ber"]["max_bits"] < config["ber"]["min_batches"] * batch_bits:
        raise ValueError("ber.max_bits is below the minimum batch payload")
    if config["ber"]["max_bits"] + batch_bits - 1 > U64_MAX:
        raise ValueError("The final whole batch may overflow a u64 bit counter")
    object_keys(config["perf"], {"ebn0_db", "n_batches"}, "perf")
    if config["perf"]["ebn0_db"] != 10 or type(config["perf"]["ebn0_db"]) is not int:
        raise ValueError("perf.ebn0_db must be 10")
    batches = config["perf"]["n_batches"]
    if batches is not None:
        integer(batches, "perf.n_batches", maximum=U64_MAX // batch_bits)
    elif mode == "perf":
        raise ValueError("perf.n_batches awaits M2 calibration")
    object_keys(config["stages"], {"repetitions"}, "stages")
    integer(config["stages"]["repetitions"], "stages.repetitions")
    if mode in ("perf", "stages") and config["csi"] != "estimated":
        raise ValueError("Perfect CSI is diagnostic only")


def config_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the M1 configuration contract"
    )
    parser.add_argument("config", type=Path)
    parser.add_argument("--mode", choices=("golden", "ber", "perf", "stages"))
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    try:
        integer(args.workers, "workers")
        validate_config(load_json(args.config), args.mode)
    except (OSError, ValueError, TypeError, OverflowError) as error:
        print(f"Invalid configuration: {error}", file=sys.stderr)
        return 2
    print("PASS configuration")
    return 0


if __name__ == "__main__":
    sys.exit(main())
