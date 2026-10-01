"""Commands, provenance, and strict result boundaries for the benchmark harness."""

import hashlib
import json
import math
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from tools import contract

ROOT = contract.ROOT
LANGUAGES = ("cpp", "python", "rust", "julia")
THREADS = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "PYTHONHASHSEED": "0",
}


def command(language, workers, config, mode, output):
    launch = {
        "cpp": [str(ROOT / "build/cpp/ofdm")],
        "python": [
            str(ROOT / "impl/python/.venv/bin/python"),
            str(ROOT / "impl/python/src/ofdm.py"),
        ],
        "rust": [str(ROOT / "build/rust/release/ofdm-rust")],
        "julia": [
            "julia",
            "-O3",
            "--startup-file=no",
            f"--threads={workers},0",
            f"--project={ROOT / 'impl/julia'}",
            str(ROOT / "impl/julia/src/main.jl"),
        ],
    }[language]
    return [
        *launch,
        "--config",
        str(config),
        "--mode",
        mode,
        "--workers",
        str(workers),
        "--out",
        str(output),
    ]


def capture_text(args):
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def temperature():
    return {
        str(p.parent): int(p.read_text())
        for p in Path("/sys/class/thermal").glob("thermal_zone*/temp")
    }


def ac_online():
    paths = list(Path("/sys/class/power_supply").glob("*/online"))
    return bool(paths) and any(p.read_text().strip() == "1" for p in paths)


def session_environment():
    environment = os.environ.copy()
    runtime = Path(f"/run/user/{os.getuid()}")
    if (runtime / "bus").is_socket():
        environment.setdefault("XDG_RUNTIME_DIR", str(runtime))
        environment.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime}/bus")
    return environment


def environment(order_seed, measurement):
    if not ac_online():
        raise RuntimeError("AC power is required; connect the charger")
    maps = {
        kind: Path(f"/sys/devices/cpu_{kind}/cpus").read_text().strip()
        for kind in ("core", "atom")
    }
    if maps != {"core": "0-3", "atom": "4-11"}:
        raise RuntimeError(f"Hybrid CPU geometry differs from the plan: {maps}")
    effective = {key: os.environ.get(key) for key in THREADS}
    if effective != THREADS:
        raise RuntimeError(f"Thread environment differs: {effective}")
    turbo = int(Path("/sys/devices/system/cpu/intel_pstate/no_turbo").read_text())
    if measurement == "primary" and turbo != 1:
        raise RuntimeError(
            "Primary measurements require no_turbo=1; user action is required"
        )
    if measurement == "turbo_check" and turbo != 0:
        raise RuntimeError("Turbo confirmation requires no_turbo=0")
    locks = (
        "impl/python/uv.lock",
        "impl/rust/Cargo.lock",
        "impl/julia/Manifest.toml",
        "tools/uv.lock",
    )
    return {
        "date_utc": datetime.now(UTC).isoformat(),
        "smoke": measurement == "smoke",
        "measurement": measurement,
        "git_sha": capture_text(["git", "rev-parse", "HEAD"]),
        "dirty": bool(capture_text(["git", "status", "--porcelain"])),
        "cpu": json.loads(capture_text(["lscpu", "--json"])),
        "cpu_map": json.loads(
            capture_text(["lscpu", "-e=CPU,CORE,SOCKET,ONLINE,MAXMHZ", "--json"])
        ),
        "p_cores": [0, 1, 2, 3],
        "e_cores": list(range(4, 12)),
        "verified_cpu_sets": maps,
        "kernel": capture_text(["uname", "-r"]),
        "distro": capture_text(["lsb_release", "-ds"]),
        "governors": {
            str(p.parent): p.read_text().strip()
            for p in Path("/sys/devices/system/cpu/cpufreq").glob(
                "policy*/scaling_governor"
            )
        },
        "no_turbo": turbo,
        "ac_online": True,
        "threads": effective,
        "mise": json.loads(capture_text(["mise", "ls", "--current", "--json"])),
        "system_packages": capture_text(
            [
                "dpkg-query",
                "-W",
                "g++",
                "libitpp-dev",
                "libfftw3-dev",
                "nlohmann-json3-dev",
            ]
        ),
        "lockfile_sha256": {
            p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in locks
        },
        "build_flags": {
            "cpp": "Release -O3 -march=native",
            "rust": "opt-level=3 lto=fat codegen-units=1 panic=abort target-cpu=native",
            "julia": "-O3 --startup-file=no --threads=p,0 FFTW.ESTIMATE",
            "python": "CPython NumPy forkserver",
        },
        "order_seed": order_seed,
        "orchestrator_cpu": 0,
    }


def read_results(path, config_path, language, workers, mode):
    records = [contract.parse_json(line) for line in path.read_text().splitlines()]
    config = contract.load_json(config_path)
    expected_points = config["ber"]["ebn0_db"] if mode == "ber" else [10]
    if len(records) != len(expected_points):
        raise ValueError("Incomplete point output")
    schema = contract.load_json(ROOT / "contract/result.schema.json")["oneOf"][1]
    for record, point in zip(records, expected_points, strict=True):
        expected_keys = set(schema["required"])
        if mode == "stages":
            expected_keys.add("stage_ns_per_symbol")
        contract.object_keys(record, expected_keys, "result")
        for name in ("schema_version", "workers", "master_seed"):
            contract.integer(
                record[name], name, minimum=0 if name == "master_seed" else 1
            )
        contract.number(record["ebn0_db"], "ebn0_db")
        for name, value in {
            "impl": language,
            "workers": workers,
            "mode": mode,
            "schema_version": 1,
            "profile_id": config["profile_id"],
            "master_seed": config["master_seed"],
            "config_sha256": contract.config_sha256(config_path.read_bytes()),
            "ebn0_db": point,
        }.items():
            if record[name] != value:
                raise ValueError(f"Result metadata mismatch: {name}")
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", record["git_sha"]):
            raise ValueError("Invalid result Git SHA")
        for name in (
            "n_batches",
            "n_symbols",
            "n_bits",
            "n_errors",
            "sum_batch_errors_sq",
            "n_symbols_with_errors",
            "zf_zero_count",
        ):
            contract.integer(record[name], name, minimum=0)
        if (
            record["n_batches"] < 1
            or record["n_bits"] != record["n_batches"] * 172032
            or record["n_symbols"] != record["n_batches"] * 256
        ):
            raise ValueError("Invalid batch counter relationships")
        if record["n_errors"] > record["n_bits"] or record[
            "n_symbols_with_errors"
        ] > min(record["n_symbols"], record["n_errors"]):
            raise ValueError("Error counters exceed payload")
        for name in ("setup_s", "warmup_s", "work_s"):
            contract.number(record[name], name)
            if record[name] < 0 or (name == "work_s" and record[name] == 0):
                raise ValueError("Invalid phase duration")
        allowed = {"target_errors", "max_bits"} if mode == "ber" else {"fixed_work"}
        if record["status"] not in allowed:
            raise ValueError("Unexpected completion status")
        if mode == "perf" and record["n_batches"] != config["perf"]["n_batches"]:
            raise ValueError("Fixed performance workload differs")
        if mode == "stages" and record["n_batches"] != 1:
            raise ValueError("Stage counters must represent one batch")
        n, total, squares = (
            record[k] for k in ("n_batches", "n_errors", "sum_batch_errors_sq")
        )
        if n * squares < total * total or squares > total * 172032:
            raise ValueError("Inconsistent batch error moments")
        if mode == "stages":
            stages = record["stage_ns_per_symbol"]
            contract.object_keys(
                stages,
                set(schema["properties"]["stage_ns_per_symbol"]["required"]),
                "stages",
            )
            if any(
                type(x) not in (int, float) or not math.isfinite(x) or x <= 0
                for x in stages.values()
            ):
                raise ValueError("Invalid isolated stage duration")
    return records
