"""Run one simulator inside its cgroup and retain bounded process-tree samples."""

import argparse
import os
import signal
import subprocess
import time
from pathlib import Path

import psutil

from tools import contract


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    args = parser.parse_args()
    spec = contract.load_json(args.spec)
    cgroup = Path("/sys/fs/cgroup") / Path(
        "/proc/self/cgroup"
    ).read_text().strip().split(":", 2)[2].lstrip("/")
    peak = cgroup / "memory.peak"
    if not peak.is_file():
        raise RuntimeError("cgroup memory.peak is unavailable")
    start = time.monotonic()
    samples = []
    status = "complete"
    phase_path = Path(spec["phase_path"])
    work_started = None
    with open(spec["stdout"], "w") as stdout, open(spec["stderr"], "w") as stderr:
        process = subprocess.Popen(
            spec["command"],
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
            env={**os.environ, "BENCH_PHASE_PATH": str(phase_path)},
        )
        tree = psutil.Process(process.pid)
        while process.poll() is None:
            elapsed = time.monotonic() - start
            rss = 0
            cpu_s = 0.0
            if work_started is None and phase_path.exists():
                work_started = elapsed
            phase = "warmup" if work_started is None else "work"
            try:
                children = [tree, *tree.children(recursive=True)]
            except psutil.NoSuchProcess:
                children = []
            for child in children:
                try:
                    rss += child.memory_info().rss
                    cpu = child.cpu_times()
                    cpu_s += cpu.user + cpu.system
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            samples.append(
                {"elapsed_s": elapsed, "rss_bytes": rss, "cpu_s": cpu_s, "phase": phase}
            )
            warmup_expired = (
                work_started is None and elapsed >= spec["warmup_timeout_s"]
            )
            expired = (
                (
                    elapsed - work_started >= spec["timeout_s"]
                    if work_started is not None
                    else False
                )
                if spec["limit_work"]
                else elapsed >= spec["timeout_s"]
            )
            if expired or warmup_expired:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                status = "warmup_timeout" if warmup_expired else "timeout"
                break
            time.sleep(spec["sample_s"])
        process.wait()
    result = {
        "status": status,
        "returncode": process.returncode,
        "process_s": time.monotonic() - start,
        "memory_peak_bytes": int(peak.read_text()),
        "cgroup": str(cgroup),
        "rss_samples": samples,
        "rss_peak_bytes": max((s["rss_bytes"] for s in samples), default=0),
    }
    work_samples = [sample for sample in samples if sample["phase"] == "work"]
    baseline = work_samples[0]["rss_bytes"] if work_samples else None
    work_peak = max((sample["rss_bytes"] for sample in work_samples), default=None)
    result.update(
        phase_marker_observed=work_started is not None,
        work_start_observed_s=work_started,
        work_observed_s=None
        if work_started is None
        else result["process_s"] - work_started,
        rss_after_warmup_bytes=baseline,
        rss_postwarmup_peak_bytes=work_peak,
        rss_work_delta_bytes=None if baseline is None else work_peak - baseline,
        cpu_progress_during_work=None
        if len(work_samples) < 2
        else work_samples[-1]["cpu_s"] - work_samples[0]["cpu_s"],
    )
    contract.write_json(Path(spec["capture"]), result)
    return 0 if status == "timeout" or process.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
