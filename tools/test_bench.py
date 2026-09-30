"""Artifact-producing orchestration acceptance; implementations are real processes."""

import json
import shutil
import subprocess
import sys
import unittest

import contract


class HarnessChecks(unittest.TestCase):
    def test_smoke_e2e(self):
        # Failure boundaries: missing toolchain/cgroup, battery, wrong affinity,
        # thread oversubscription, stale hashes, incomplete output, and timeout.
        directory = contract.ROOT / "results/acceptance/harness"
        directory.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["make", "bench", "SUITE=smoke"],
            cwd=contract.ROOT,
            text=True,
            capture_output=True,
            timeout=300,
        )
        (directory / "command.log").write_text(result.stdout + result.stderr)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        run = (
            contract.ROOT
            / "results"
            / (contract.ROOT / "results/LATEST").read_text().strip()
        )
        manifest = json.loads((run / "manifest.json").read_text())
        environment = json.loads((run / "env.json").read_text())
        self.assertTrue(environment["ac_online"])
        self.assertEqual(
            environment["threads"],
            {
                "OMP_NUM_THREADS": "1",
                "OPENBLAS_NUM_THREADS": "1",
                "MKL_NUM_THREADS": "1",
                "PYTHONHASHSEED": "0",
            },
        )
        self.assertEqual(
            {r["impl"] for r in manifest["executions"]},
            {"cpp", "python", "rust", "julia"},
        )
        self.assertEqual(
            {r["suite"] for r in manifest["executions"]},
            {"single", "stages", "scaling", "memory", "ber"},
        )
        for execution in manifest["executions"]:
            capture = json.loads((run / execution["capture"]).read_text())
            self.assertGreater(capture["memory_peak_bytes"], 0)
            self.assertTrue(capture["rss_samples"])
            if execution["status"] == "timeout":
                self.assertEqual(execution["suite"], "memory")
                continue
            records = [
                json.loads(line)
                for line in (run / execution["output"]).read_text().splitlines()
            ]
            self.assertTrue(records)
            for record in records:
                self.assertEqual(record["workers"], execution["workers"])
                self.assertEqual(record["impl"], execution["impl"])
                self.assertEqual(record["config_sha256"], execution["config_sha256"])
                self.assertEqual(record["n_bits"], record["n_batches"] * 172032)
        analysis = subprocess.run(
            ["make", "analyze", f"RUN={run}"],
            cwd=contract.ROOT,
            text=True,
            capture_output=True,
            timeout=60,
        )
        self.assertEqual(analysis.returncode, 0, analysis.stdout + analysis.stderr)
        for name in (
            "README.md",
            "summary.csv",
            "throughput.png",
            "stages.png",
            "scaling.png",
            "memory.png",
            "ber.png",
        ):
            self.assertTrue(
                (contract.ROOT / "report" / run.name / name).is_file(), name
            )
        self.assertIn(
            "smoke", (contract.ROOT / "report" / run.name / "README.md").read_text()
        )
        # Retain a projection of eight real timeout artifacts. An accepted
        # memory-only run has no simulator JSONL records, and still needs analysis.
        projection = directory / "memory-only"
        projection.mkdir(exist_ok=True)
        subset = dict(manifest)
        subset["executions"] = [
            r for r in manifest["executions"] if r["suite"] == "memory"
        ]
        subset["projection_source"] = str(run)
        contract.write_json(projection / "manifest.json", subset)
        shutil.copyfile(run / "env.json", projection / "env.json")
        for execution in subset["executions"]:
            target = projection / execution["capture"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(run / execution["capture"], target)
        analysis = subprocess.run(
            [sys.executable, "-m", "bench.analyze", "--run", str(projection)],
            cwd=contract.ROOT,
            text=True,
            capture_output=True,
            timeout=60,
        )
        self.assertEqual(analysis.returncode, 0, analysis.stdout + analysis.stderr)
        self.assertTrue((contract.ROOT / "report/memory-only/memory.csv").is_file())
        for name in ("summary", "stages", "scaling", "ber"):
            self.assertTrue(
                (contract.ROOT / f"report/memory-only/{name}.csv").is_file()
            )
        for name in ("throughput", "stages", "scaling", "ber"):
            self.assertIn(
                "Sem dados para esta suíte",
                (contract.ROOT / f"report/memory-only/{name}.svg").read_text(),
            )


if __name__ == "__main__":
    unittest.main()
