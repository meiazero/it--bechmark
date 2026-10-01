"""Report trust-boundary checks with invalid, non-measurement input fixtures."""

import copy
import csv
import json
import unittest
from unittest.mock import patch

import contract
from bench.analyze import analyze, plt


class AnalysisBoundaryChecks(unittest.TestCase):
    def setUp(self):
        # Failure boundaries: stale hashes, valid but different workloads pooled,
        # cross-language config mismatches, and an incomplete collection.
        self.directory = (
            contract.ROOT
            / "results/acceptance"
            / f"analysis-fixture-{self._testMethodName}"
        )
        (self.directory / "raw").mkdir(parents=True, exist_ok=True)
        self.profile = copy.deepcopy(contract.load_json(contract.PROFILE))
        self.profile["perf"]["n_batches"] = 1
        self.record = {
            "schema_version": 1,
            "impl": "cpp",
            "git_sha": "0" * 40,
            "mode": "perf",
            "profile_id": self.profile["profile_id"],
            "master_seed": self.profile["master_seed"],
            "workers": 1,
            "ebn0_db": 10,
            "n_batches": 1,
            "n_symbols": 256,
            "n_bits": 172032,
            "n_errors": 0,
            "sum_batch_errors_sq": 0,
            "n_symbols_with_errors": 0,
            "zf_zero_count": 0,
            "setup_s": 0,
            "warmup_s": 0,
            "work_s": 1,
            "status": "fixed_work",
        }
        self.manifest = {
            "smoke": True,
            "completed": True,
            "repetitions": 1,
            "cooldown_s": 0,
            "fixture": "invalid parser input; no simulator or measurement",
            "executions": [],
        }
        contract.write_json(
            self.directory / "env.json",
            {"no_turbo": 0, "git_sha": "0" * 40, "dirty": False, "order_seed": 0},
        )
        self.summary = contract.ROOT / "report" / self.directory.name / "summary.csv"
        self.summary.unlink(missing_ok=True)
        self.addCleanup(plt.close, "all")

    def add_input(self, label, batches, language="cpp", invalid_hash=False):
        config = copy.deepcopy(self.profile)
        config["perf"]["n_batches"] = batches
        path = self.directory / f"{label}.config.json"
        contract.write_json(path, config)
        record = dict(self.record)
        record.update(
            impl=language,
            n_batches=batches,
            n_symbols=batches * 256,
            n_bits=batches * 172032,
            config_sha256="invalid-fixture-fingerprint"
            if invalid_hash
            else contract.config_sha256(path.read_bytes()),
        )
        (self.directory / f"raw/{label}.jsonl").write_text(json.dumps(record) + "\n")
        contract.write_json(
            self.directory / f"raw/{label}.capture.json", {"process_s": 1}
        )
        self.manifest["executions"].append(
            {
                "id": label,
                "suite": "single",
                "core": "p-core",
                "workers": 1,
                "impl": language,
                "mode": "perf",
                "config": path.name,
                "output": f"raw/{label}.jsonl",
                "capture": f"raw/{label}.capture.json",
                "status": "complete",
            }
        )
        contract.write_json(self.directory / "manifest.json", self.manifest)

    def rejects_before_reporting(self, message):
        with (
            patch(
                "bench.analyze.plt.subplots",
                side_effect=AssertionError("Unvalidated plot"),
            ),
            self.assertRaisesRegex(ValueError, message),
        ):
            analyze(self.directory)
        self.assertFalse(self.summary.exists())

    def test_invalid_fingerprint(self):
        self.add_input("invalid", 1, invalid_hash=True)
        self.rejects_before_reporting("metadata")
        self.manifest["completed"] = False
        contract.write_json(self.directory / "manifest.json", self.manifest)
        self.rejects_before_reporting("completed run")

    def test_mixed_workloads_within_language(self):
        self.add_input("one", 1)
        self.add_input("two", 2)
        self.rejects_before_reporting("different configurations")

    def test_mixed_workloads_between_languages(self):
        self.add_input("one", 1)
        self.add_input("two", 2, "python")
        self.rejects_before_reporting("identical configurations")

    def test_scaling_requires_the_same_workload(self):
        self.add_input("serial", 1)
        self.add_input("parallel", 2)
        for workers, execution in enumerate(self.manifest["executions"], start=1):
            execution.update(suite="scaling", core="e-core", workers=workers)
            path = self.directory / execution["output"]
            record = json.loads(path.read_text())
            record["workers"] = workers
            path.write_text(json.dumps(record) + "\n")
        contract.write_json(self.directory / "manifest.json", self.manifest)
        self.rejects_before_reporting("identical configurations")

    def test_stale_source_commit(self):
        self.add_input("stale-source", 1)
        path = self.directory / "raw/stale-source.jsonl"
        record = json.loads(path.read_text())
        record["git_sha"] = "1" * 40
        path.write_text(json.dumps(record) + "\n")
        self.rejects_before_reporting("source commit")

    def test_invalid_geometry_with_matching_fingerprint(self):
        self.add_input("invalid-geometry", 1)
        config = self.directory / "invalid-geometry.config.json"
        value = contract.load_json(config)
        value["N_fft"] = 128
        contract.write_json(config, value)
        output = self.directory / "raw/invalid-geometry.jsonl"
        record = json.loads(output.read_text())
        record["config_sha256"] = contract.config_sha256(config.read_bytes())
        output.write_text(json.dumps(record) + "\n")
        self.rejects_before_reporting("frozen")

    def test_render_failure_preserves_existing_report(self):
        self.add_input("valid-parser-fixture", 1)
        destination = self.summary.parent
        destination.mkdir(parents=True, exist_ok=True)
        previous = destination / "previous-report.txt"
        previous.write_text("Retained previous report\n")
        with (
            patch(
                "bench.analyze.save_figure",
                side_effect=RuntimeError("Render fixture failed"),
            ),
            self.assertRaisesRegex(RuntimeError, "Render fixture failed"),
        ):
            analyze(self.directory)
        self.assertEqual(previous.read_text(), "Retained previous report\n")
        self.assertFalse(self.summary.exists())

    def test_stage_fields_have_no_performance_ratios(self):
        stage_names = contract.load_json(contract.ROOT / "contract/result.schema.json")[
            "oneOf"
        ][1]["properties"]["stage_ns_per_symbol"]["required"]
        for language in ("cpp", "python"):
            for repetition in range(2):
                self.add_input(f"{language}-{repetition}", 1, language)
                execution = self.manifest["executions"][-1]
                execution.update(suite="stages", mode="stages")
                path = self.directory / execution["output"]
                record = json.loads(path.read_text())
                record.update(
                    mode="stages", stage_ns_per_symbol=dict.fromkeys(stage_names, 1)
                )
                path.write_text(json.dumps(record) + "\n")
        contract.write_json(self.directory / "manifest.json", self.manifest)
        fields = (
            "vazão_Mbit_s",
            "aceleração_relativa_Cpp",
            "IC95_aceleração_inferior",
            "IC95_aceleração_superior",
        )

        def inspect_before_fixture_plot(fig, destination, name):
            with (destination / "summary.csv").open() as file:
                rows = list(csv.DictReader(file))
            self.assertEqual(len(rows), 2)
            for row in rows:
                self.assertTrue(all(row[field] == "" for field in fields), row)
            raise RuntimeError("No fixture figures published")

        with (
            patch("bench.analyze.save_figure", side_effect=inspect_before_fixture_plot),
            self.assertRaisesRegex(RuntimeError, "No fixture figures published"),
        ):
            analyze(self.directory)
        self.assertFalse(self.summary.exists())


if __name__ == "__main__":
    unittest.main()
