"""Artifact-producing CLI acceptance shared by existing implementations."""

import copy
import json
import subprocess
import unittest
from pathlib import Path

import check_golden
import contract


class ImplementationChecks(unittest.TestCase):
    def test_cpp_e2e(self):
        self.accept("cpp", [str(contract.ROOT / "build/cpp/ofdm")])
        result = subprocess.run(
            [str(contract.ROOT / "build/cpp/seed64_check"), str(contract.PROFILE),
             str(contract.ROOT / "results/acceptance/cpp/seed64.json")],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def accept(self, name, command):
        # Failure boundaries: malformed JSON/CLI, geometry, raw-byte hashes,
        # seed truncation, reordered stopping, zero ZF, and phase contamination.
        directory = contract.ROOT / "results/acceptance" / name
        directory.mkdir(parents=True, exist_ok=True)
        profile = contract.load_json(contract.PROFILE)

        def run(config, mode, workers=1, label="run", expected=0):
            output = directory / f"{label}.jsonl"
            output.unlink(missing_ok=True)
            result = subprocess.run(
                [*command, "--config", str(config), "--mode", mode,
                 "--workers", str(workers), "--out", str(output)],
                capture_output=True, text=True, timeout=90,
            )
            self.assertEqual(result.returncode, expected, result.stderr)
            if expected:
                self.assertTrue(result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertFalse(output.exists())
                return []
            records = check_golden.read_records(output)
            self.assertTrue(records)
            return records

        golden = run(contract.PROFILE, "golden", label="golden")
        check_golden.verify_records(
            golden, check_golden.load_expected(contract.ROOT / "contract/golden"),
            profile, contract.config_sha256(contract.PROFILE.read_bytes()), 1,
        )
        for fixture in sorted((contract.ROOT / "contract/invalid_configs").glob("*.json")):
            run(fixture, "ber", label=fixture.stem, expected=2)
        for workers in (0, -1, "1.5", contract.U64_MAX + 1):
            run(contract.PROFILE, "ber", workers, label="bad-workers", expected=2)
        for text in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}',
                     contract.PROFILE.read_text().replace('"master_seed": 20260930',
                         '"master_seed": 20260930, "master_seed": 7')):
            path = directory / "malformed.json"
            path.write_text(text)
            run(path, "ber", label="malformed", expected=2)
        config = copy.deepcopy(profile)
        config["ber"].update(target_errors=30000, min_batches=3,
                             max_bits=8 * 256 * 672, ebn0_db=[0, 10, 30])
        config["perf"]["n_batches"] = 5
        config["stages"]["repetitions"] = 3
        path = directory / "smoke.json"
        path.write_text(json.dumps(config, indent=4) + "\r\n")
        runs = [run(path, "ber", w, f"ber-{w}-{i}")
                for i, w in enumerate((1, 4, 1))]
        counters = ("n_batches", "n_symbols", "n_bits", "n_errors",
                    "sum_batch_errors_sq", "n_symbols_with_errors", "zf_zero_count", "status")
        self.assertEqual([[{k: r[k] for k in counters} for r in x] for x in runs],
                         [[{k: r[k] for k in counters} for r in runs[0]]] * 3)
        self.assertEqual(runs[0][0]["status"], "target_errors")
        self.assertEqual(runs[0][-1]["status"], "max_bits")
        fixed = [run(path, "perf", w, f"perf-{w}") for w in (1, 4)]
        self.assertEqual([{k: x[0][k] for k in counters} for x in fixed],
                         [{k: fixed[0][0][k] for k in counters}] * 2)
        stages = run(path, "stages", label="stages")
        self.assertEqual(set(stages[0]["stage_ns_per_symbol"]),
            {"bits", "qam_map", "grid", "ifft", "cp_add", "channel_conv", "awgn",
             "cp_remove", "fft", "chan_est", "zf", "demap_count", "e2e"})
        for records in (*runs, *fixed, stages):
            for record in records:
                self.assertEqual(record["config_sha256"], contract.config_sha256(path.read_bytes()))
                self.assertEqual(record["n_bits"], record["n_batches"] * 256 * 672)
                self.assertEqual(record["n_symbols"], record["n_batches"] * 256)
                self.assertLessEqual(record["n_errors"], record["n_bits"])
                self.assertLessEqual(record["n_symbols_with_errors"], record["n_symbols"])
                self.assertGreaterEqual(record["sum_batch_errors_sq"],
                    record["n_errors"] ** 2 / record["n_batches"])
        high = copy.deepcopy(config)
        high["master_seed"] += 1 << 32
        high_path = directory / "high-seed.json"
        contract.write_json(high_path, high)
        other = run(high_path, "perf", label="high-seed")
        self.assertNotEqual(other[0]["n_errors"], fixed[0][0]["n_errors"])
        for channel, csi in (("awgn", "perfect"), ("rayleigh", "perfect")):
            diagnostic = copy.deepcopy(config)
            diagnostic.update(channel=channel, csi=csi)
            diagnostic["ber"]["ebn0_db"] = [10]
            diagnostic_path = directory / f"{channel}-perfect.json"
            contract.write_json(diagnostic_path, diagnostic)
            run(diagnostic_path, "ber", label=f"{channel}-perfect")
            run(diagnostic_path, "perf", label="invalid-perfect", expected=2)


if __name__ == "__main__":
    unittest.main()
