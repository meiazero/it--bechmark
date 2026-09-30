"""Run one simulator inside its cgroup and retain bounded process-tree samples."""

import argparse
import json
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
    with open(spec["stdout"], "w") as stdout, open(spec["stderr"], "w") as stderr:
        process = subprocess.Popen(
            spec["command"], stdout=stdout, stderr=stderr, start_new_session=True
        )
        tree = psutil.Process(process.pid)
        while process.poll() is None:
            elapsed = time.monotonic() - start
            rss = 0
            try:
                children = [tree, *tree.children(recursive=True)]
            except psutil.NoSuchProcess:
                children = []
            for child in children:
                try:
                    rss += child.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            samples.append({"elapsed_s": elapsed, "rss_bytes": rss})
            if elapsed >= spec["timeout_s"]:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                status = "timeout"
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
    # Internal work duration locates the final work window approximately; M7
    # adds a phase boundary marker before published post-warmup memory deltas.
    output = Path(spec["output"])
    if status == "complete" and process.returncode == 0 and output.is_file():
        records = [json.loads(line) for line in output.read_text().splitlines()]
        work_start = result["process_s"] - sum(r["work_s"] for r in records)
        baseline = next(
            (s["rss_bytes"] for s in samples if s["elapsed_s"] >= work_start), None
        )
        result["rss_after_warmup_bytes_estimate"] = baseline
        result["rss_work_delta_bytes_estimate"] = (
            None if baseline is None else result["rss_peak_bytes"] - baseline
        )
    contract.write_json(Path(spec["capture"]), result)
    return 0 if status == "timeout" or process.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
