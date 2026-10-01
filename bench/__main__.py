"""Execute fixed, pinned, randomized suites without discarding raw processes."""

import argparse
import copy
import json
import os
import random
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime

from bench.common import (
    LANGUAGES,
    ROOT,
    ac_online,
    command,
    environment,
    read_results,
    session_environment,
    temperature,
)
from tools import contract


def run_execution(directory, execution, timeout, sample):
    stem = execution["id"]
    output = directory / f"raw/{stem}.jsonl"
    capture = directory / f"raw/{stem}.capture.json"
    invocation = [
        "taskset",
        "-c",
        ",".join(map(str, execution["cpus"])),
        *command(
            execution["impl"],
            execution["workers"],
            directory / execution["config"],
            execution["mode"],
            output,
        ),
    ]
    spec = {
        "command": invocation,
        "output": str(output),
        "capture": str(capture),
        "stdout": str(directory / f"raw/{stem}.stdout"),
        "stderr": str(directory / f"raw/{stem}.stderr"),
        "timeout_s": timeout,
        "sample_s": sample,
        "phase_path": str(directory / f"raw/{stem}.phase"),
        "limit_work": execution["suite"] == "memory",
        "warmup_timeout_s": 90,
    }
    spec_path = directory / f"raw/{stem}.spec.json"
    contract.write_json(spec_path, spec)
    launch = [
        "systemd-run",
        "--user",
        "--scope",
        "--quiet",
        "--unit",
        f"ofdm-{directory.name}-{stem}",
        "-p",
        "MemoryAccounting=yes",
        sys.executable,
        "-m",
        "bench.capture",
        "--spec",
        str(spec_path),
    ]
    before = temperature()
    started = time.monotonic()
    completed = subprocess.run(
        launch,
        cwd=ROOT,
        env=session_environment(),
        capture_output=True,
        text=True,
        timeout=timeout + 105,
    )
    execution.update(
        external_s=time.monotonic() - started,
        temperature_before=before,
        temperature_after=temperature(),
        output=str(output.relative_to(directory)),
        capture=str(capture.relative_to(directory)),
        command=invocation,
    )
    if completed.returncode:
        raise RuntimeError(f"{stem}: {completed.stderr}; see {spec['stderr']}")
    memory = contract.load_json(capture)
    execution["status"] = memory["status"]
    if memory["status"] == "complete":
        records = read_results(
            output,
            directory / execution["config"],
            execution["impl"],
            execution["workers"],
            execution["mode"],
        )
        execution["work_s"] = records[0]["work_s"]
    elif execution["suite"] != "memory":
        raise RuntimeError(f"{stem}: unexpected timeout")
    return execution


def positions(suite, smoke):
    selected = (
        [(1, [2], "p-core"), (1, [4], "e-core")]
        if suite == "single"
        else [(p, list(range(4, 4 + p)), "e-core") for p in (1, 2, 4, 8)]
        if suite == "scaling"
        else [(p, list(range(4, 4 + p)), "e-core") for p in (1, 8)]
        if suite == "memory"
        else [(1, [2], "p-core")]
    )
    if suite == "scaling" and not smoke:
        selected.append((12, list(range(12)), "mixed-informative"))
    return selected


def execution_plan(suites, smoke, turbo_check):
    profile = contract.load_json(contract.PROFILE)
    contract.validate_config(profile, "golden" if smoke else "perf")
    groups = []
    for suite in suites:
        for workers, cpus, core in positions(suite, smoke):
            for language in LANGUAGES:
                mode = (
                    "stages"
                    if suite == "stages"
                    else "ber"
                    if suite == "ber"
                    else "perf"
                )
                config = "memory-config.json" if suite == "memory" else "config.json"
                directory = ROOT / "results/<run_id>"
                groups.append(
                    {
                        "suite": suite,
                        "impl": language,
                        "workers": workers,
                        "cpus": cpus,
                        "core": core,
                        "repetitions": 1 if smoke or suite == "memory" else 10,
                        "possible_repeat_processes": 10
                        if not smoke and suite in ("single", "scaling", "stages")
                        else 0,
                        "work_limit_s": (10 if smoke else 600)
                        if suite == "memory"
                        else None,
                        "command_is_first_repetition": True,
                        "command": [
                            "taskset",
                            "-c",
                            ",".join(map(str, cpus)),
                            *command(
                                language,
                                workers,
                                directory / config,
                                mode,
                                directory
                                / f"raw/{suite}-{core}-p{workers}-r0-{language}.jsonl",
                            ),
                        ],
                    }
                )
    return {
        "plan_only": True,
        "executed": False,
        "measurement": "smoke"
        if smoke
        else "turbo_check"
        if turbo_check
        else "primary",
        "expected_no_turbo": None if smoke else 0 if turbo_check else 1,
        "perf_n_batches": 4 if smoke else profile["perf"]["n_batches"],
        "contract_source_sha256": contract.config_sha256(contract.PROFILE.read_bytes()),
        "cooldown_s": 0 if smoke else 20,
        "orchestrator_cpu": 0,
        "order_seed": 20260930,
        "CV_repeat_threshold": 0.05,
        "baseline_processes": sum(group["repetitions"] for group in groups),
        "possible_repeat_processes": sum(
            group["possible_repeat_processes"] for group in groups
        ),
        "groups": groups,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", default="smoke")
    parser.add_argument("--turbo-check", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    smoke = args.suite == "smoke"
    suites = (
        ["single", "stages", "scaling", "memory", "ber"]
        if smoke
        else args.suite.split(",")
    )
    if len(set(suites)) != len(suites) or any(
        s not in ("single", "stages", "scaling", "memory", "ber") for s in suites
    ):
        raise ValueError("Unknown or duplicate benchmark suite")
    order_seed = 20260930
    if smoke and args.turbo_check:
        raise ValueError("Turbo confirmation requires a full suite")
    if args.dry_run:
        print(json.dumps(execution_plan(suites, smoke, args.turbo_check), indent=2))
        return 0
    measurement = "smoke" if smoke else "turbo_check" if args.turbo_check else "primary"
    env = environment(order_seed, measurement)
    allowed = os.sched_getaffinity(0)
    if not set(range(12)) <= allowed:
        raise RuntimeError(
            "The required hybrid CPU map is outside the allowed affinity"
        )
    os.sched_setaffinity(0, {0})
    profile = contract.load_json(contract.PROFILE)
    if not smoke and profile["perf"]["n_batches"] is None:
        raise RuntimeError("Full measurements await M8 calibration")
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + f"-{os.getpid()}"
    directory = ROOT / "results" / run_id
    (directory / "raw").mkdir(parents=True, exist_ok=False)
    contract.write_json(directory / "env.json", env)
    config = copy.deepcopy(profile)
    if smoke:
        config["perf"]["n_batches"] = 4
        config["stages"]["repetitions"] = 3
        config["ber"].update(
            target_errors=1000, min_batches=3, max_bits=8 * 172032, ebn0_db=[0, 10, 30]
        )
    contract.write_json(directory / "config.json", config)
    long_config = copy.deepcopy(config)
    long_config["perf"]["n_batches"] = contract.U64_MAX // 172032
    contract.write_json(directory / "memory-config.json", long_config)
    manifest = {
        "run_id": run_id,
        "smoke": smoke,
        "executions": [],
        "completed": False,
        "repetitions": 1 if smoke else 10,
        "cooldown_s": 0 if smoke else 20,
    }
    contract.write_json(directory / "manifest.json", manifest)
    rng = random.Random(order_seed)
    manifest["noise_checks"] = []

    def execute_round(suite, workers, cpus, core, repetition):
        languages = list(LANGUAGES)
        rng.shuffle(languages)
        for language in languages:
            if not ac_online():
                raise RuntimeError("AC disconnected; connect the charger")
            config_name = "memory-config.json" if suite == "memory" else "config.json"
            item = {
                "id": f"{suite}-{core}-p{workers}-r{repetition}-{language}",
                "suite": suite,
                "impl": language,
                "workers": workers,
                "cpus": cpus,
                "core": core,
                "repetition": repetition,
                "mode": "stages"
                if suite == "stages"
                else "ber"
                if suite == "ber"
                else "perf",
                "config": config_name,
                "config_sha256": contract.config_sha256(
                    (directory / config_name).read_bytes()
                ),
            }
            timeout = (
                (10 if smoke else 600) if suite == "memory" else 90 if smoke else 3600
            )
            run_execution(
                directory,
                item,
                timeout,
                1.0 if suite == "memory" and not smoke else 0.05,
            )
            manifest["executions"].append(item)
            contract.write_json(directory / "manifest.json", manifest)
            print(f"Completed {item['id']}: {item['status']}", flush=True)
            if manifest["cooldown_s"]:
                time.sleep(manifest["cooldown_s"])

    for suite in suites:
        repetitions = 1 if suite == "memory" else manifest["repetitions"]
        for workers, cpus, core in positions(suite, smoke):
            for repetition in range(repetitions):
                execute_round(suite, workers, cpus, core, repetition)
            if smoke or suite not in ("single", "scaling", "stages"):
                continue
            checks = []
            for language in LANGUAGES:
                values = [
                    r["work_s"]
                    for r in manifest["executions"]
                    if (r["suite"], r["workers"], r["core"], r["impl"])
                    == (suite, workers, core, language)
                ]
                cv = statistics.stdev(values) / statistics.mean(values)
                checks.append(
                    {
                        "suite": suite,
                        "workers": workers,
                        "core": core,
                        "impl": language,
                        "initial_cv": cv,
                        "initial_noisy": cv > 0.05,
                        "repeated": False,
                    }
                )
            if any(check["initial_noisy"] for check in checks):
                # Retain the original processes and repeat all language arms;
                # no favorable repetition is selected or substituted.
                for repetition in range(repetitions, 2 * repetitions):
                    execute_round(suite, workers, cpus, core, repetition)
                for check in checks:
                    values = [
                        r["work_s"]
                        for r in manifest["executions"]
                        if (r["suite"], r["workers"], r["core"], r["impl"])
                        == (suite, workers, core, check["impl"])
                    ]
                    check.update(
                        repeated=True,
                        retained_cv=statistics.stdev(values) / statistics.mean(values),
                    )
            manifest["noise_checks"].extend(checks)
            contract.write_json(directory / "manifest.json", manifest)
    manifest["completed"] = True
    contract.write_json(directory / "manifest.json", manifest)
    (ROOT / "results/LATEST").write_text(run_id + "\n")
    print(f"Completed run: {directory}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Benchmark failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
