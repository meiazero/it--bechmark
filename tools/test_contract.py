import copy
import hashlib
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scipy import fft
from tools.golden import reference

import check_golden
import contract
import theory


class ConfigurationChecks(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = contract.load_json(contract.PROFILE)

    def test_profile_geometry_and_power(self) -> None:
        contract.validate_config(self.profile)
        self.assertEqual(len(self.profile["active_bins"]), 192)
        self.assertEqual(len(self.profile["pilot_bins"]), 24)
        self.assertEqual(len(self.profile["data_bins"]), 168)
        self.assertEqual(self.profile["bits_per_symbol"], 672)
        self.assertEqual(self.profile["E_sym"], 192 * (288 / 256))
        self.assertAlmostEqual(sum(self.profile["pdp"]), 1, places=15)
        weights = [math.exp(-delay / 2) for delay in range(8)]
        for stored, weight in zip(self.profile["pdp"], weights, strict=True):
            self.assertAlmostEqual(stored, weight / sum(weights), places=16)
        self.assertNotIn(0, self.profile["active_bins"])
        self.assertEqual(self.profile["pilot_bins"][0], -96)
        self.assertEqual(self.profile["pilot_bins"][-1], 96)

    def test_invalid_fixtures_exit_2_without_result(self) -> None:
        fixtures = sorted((contract.ROOT / "contract/invalid_configs").glob("*.json"))
        self.assertGreater(len(fixtures), 0)
        for path in fixtures:
            with self.subTest(config=path.name):
                result = subprocess.run(
                    [
                        sys.executable,
                        str(contract.ROOT / "tools/contract.py"),
                        str(path),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertIn("Invalid configuration:", result.stderr)

    def test_valid_overrides_and_perf_calibration_boundary(self) -> None:
        self.profile.update(master_seed=contract.U64_MAX, channel="awgn", csi="perfect")
        self.profile["ber"].update(target_errors=2000, ebn0_db=[-2, 4.5])
        contract.validate_config(self.profile, "ber")
        with self.assertRaisesRegex(ValueError, "awaits M2"):
            contract.validate_config(self.profile, "perf")
        self.profile["perf"]["n_batches"] = 10
        with self.assertRaisesRegex(ValueError, "diagnostic only"):
            contract.validate_config(self.profile, "perf")
        self.profile["csi"] = "estimated"
        contract.validate_config(self.profile, "perf")

    def test_json_boundary_and_hash(self) -> None:
        for text in ('{"x":NaN}', '{"x":Infinity}', '{"x":1e309}', '{"x":1,"x":2}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                contract.parse_json(text)
        data = contract.PROFILE.read_bytes()
        self.assertEqual(contract.config_sha256(data), hashlib.sha256(data).hexdigest())

    def test_workers_are_cli_only(self) -> None:
        commands = (
            [
                sys.executable,
                str(contract.ROOT / "tools/contract.py"),
                str(contract.PROFILE),
            ],
            [
                sys.executable,
                str(contract.ROOT / "tools/check_golden.py"),
                "--self-test",
            ],
        )
        for command in commands:
            for workers in ("4", "0", "-1", "1.5", str(contract.U64_MAX + 1)):
                with self.subTest(command=command[1], workers=workers):
                    result = subprocess.run(
                        [*command, "--workers", workers],
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=10,
                    )
                    self.assertEqual(
                        result.returncode, 0 if workers == "4" else 2, result.stderr
                    )
                    if workers != "4":
                        self.assertEqual(result.stdout, "")
                        self.assertTrue(result.stderr)
        config = copy.deepcopy(self.profile)
        config["workers"] = 4
        with self.assertRaises(ValueError):
            contract.validate_config(config)


class GoldenChecks(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = contract.load_json(contract.PROFILE)

    def test_gray_levels_and_threshold_ties(self) -> None:
        bits = [0, 0, 1, 0, 0, 1, 1, 1]
        symbols = reference.map_qam(bits)
        self.assertEqual(
            symbols, [complex(-3, 3) / math.sqrt(10), complex(-1, 1) / math.sqrt(10)]
        )
        self.assertEqual(reference.demap_qam(symbols), bits)
        tie_symbols = [
            complex(-2, -2) / math.sqrt(10),
            0j,
            complex(2, 2) / math.sqrt(10),
        ]
        self.assertEqual(
            reference.demap_qam(tie_symbols), [0, 1, 0, 1, 1, 1, 1, 1, 1, 0, 1, 0]
        )

    def test_unitary_dft_sign_scale_and_parseval(self) -> None:
        values = [1 + 2j, -1j, -3 + 0j, 0.5 + 0.25j, 0j, 2j, -1 + 1j, 4 - 2j]
        spectrum = reference.dft(values)
        recovered = reference.dft(spectrum, True)
        for actual, expected in zip(recovered, values, strict=True):
            self.assertLess(abs(actual - expected), 1e-12)
        self.assertAlmostEqual(
            sum(abs(v) ** 2 for v in values), sum(abs(v) ** 2 for v in spectrum)
        )
        shifted_impulse = reference.dft([0j, 1 + 0j, 0j, 0j])
        for actual, expected in zip(
            shifted_impulse, [0.5, -0.5j, -0.5, 0.5j], strict=True
        ):
            self.assertLess(abs(actual - expected), 1e-12)

    def test_cp_convolution_matches_frequency_response(self) -> None:
        size = self.profile["N_fft"]
        values = [complex(n % 3, n % 5) / 8 for n in range(size)]
        taps = [1 + 0j, 0.2j, -0.1 + 0.1j]
        received = reference.convolve(
            reference.add_cp(values, self.profile["N_cp"]), taps
        )
        received_fft = reference.dft(
            reference.remove_cp(received, self.profile["N_cp"], size)
        )
        transmitted_fft = reference.dft(values)
        response = reference.response(taps, size)
        for actual, symbol, channel in zip(
            received_fft, transmitted_fft, response, strict=True
        ):
            self.assertLess(abs(actual - symbol * channel), 1e-11)
        self.assertEqual(
            reference.convolve([1 + 0j, 2 + 0j, 3 + 0j], [1 + 0j, 2 + 0j]),
            [1 + 0j, 4 + 0j, 7 + 0j],
        )

    def test_full_size_transform_precision(self) -> None:
        vector = contract.load_json(contract.ROOT / "contract/golden/transforms.json")
        values = [complex(*value) for value in vector["inputs"]["values"]]
        for inverse, transform in ((False, fft.fft), (True, fft.ifft)):
            with self.subTest(inverse=inverse):
                expected = transform(values, norm="ortho")
                actual = reference.dft(values, inverse)
                self.assertLess(
                    max(abs(a - b) for a, b in zip(actual, expected, strict=True)),
                    1e-14,
                )

    def test_estimation_interpolates_across_dc_in_bin_coordinates(self) -> None:
        spectrum = [0j] * self.profile["N_fft"]
        for bin_number, pilot in zip(
            self.profile["pilot_bins"], self.profile["pilots"], strict=True
        ):
            spectrum[bin_number % len(spectrum)] = pilot * (2 if bin_number < 0 else 6)
        _, estimates = reference.estimate(spectrum, self.profile)
        self.assertEqual(estimates[self.profile["data_bins"].index(-1)], 3.75)
        self.assertEqual(estimates[self.profile["data_bins"].index(1)], 4.25)

    def test_zf_exact_zero_and_noise_overhead(self) -> None:
        values, count = reference.equalize([1j, 1e-15j], [0j, 1e-15 + 0j])
        self.assertEqual(values, [0j, 1j])
        self.assertEqual(count, 1)
        self.assertEqual(reference.noise_variance(0, self.profile), 216 / 672)
        self.assertEqual(reference.noise_variance(10, self.profile), 216 / 6720)

    def test_splitmix_known_answers_and_high_bits(self) -> None:
        self.assertEqual(reference.splitmix64(0), 0xE220A8397B1DCDAF)
        self.assertEqual(reference.splitmix64(1), 0x910A2DEC89025CC1)
        self.assertNotEqual(
            reference.batch_seed(1, 0, 7), reference.batch_seed((1 << 32) | 1, 0, 7)
        )
        self.assertLessEqual(
            reference.batch_seed(contract.U64_MAX, 15, 5812), contract.U64_MAX
        )

    def test_verifier_self_test_and_jsonl_cli(self) -> None:
        expected = check_golden.load_expected(contract.ROOT / "contract/golden")
        config_hash = contract.config_sha256(contract.PROFILE.read_bytes())
        check_golden.self_test(expected, self.profile, config_hash, 1)
        records = [
            {
                "schema_version": 1,
                "impl": "cpp",
                "git_sha": "0" * 40,
                "mode": "golden",
                "profile_id": self.profile["profile_id"],
                "config_sha256": config_hash,
                "master_seed": self.profile["master_seed"],
                "workers": 1,
                "case_id": case_id,
                "outputs": vector["expected"],
            }
            for case_id, vector in expected.items()
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.jsonl"
            path.write_text("".join(json.dumps(record) + "\n" for record in records))
            command = [
                sys.executable,
                str(contract.ROOT / "tools/check_golden.py"),
                "--actual",
                str(path),
            ]
            passed = subprocess.run(
                command, capture_output=True, text=True, check=False, timeout=10
            )
            self.assertEqual(passed.returncode, 0, passed.stderr)
            path.write_text(path.read_text() + "\n")
            failed = subprocess.run(
                command, capture_output=True, text=True, check=False, timeout=10
            )
            self.assertEqual(failed.returncode, 1)
            self.assertIn("blank JSON Lines record", failed.stderr)

    def test_verifier_uses_file_bytes_and_cli_workers(self) -> None:
        expected = check_golden.load_expected(contract.ROOT / "contract/golden")
        profile = self.profile
        encodings = (
            json.dumps(profile, separators=(",", ":")).encode(),
            (json.dumps(profile, indent=4) + "\n").encode(),
            (
                json.dumps(dict(reversed(list(profile.items()))), indent=2) + "\r\n"
            ).encode(),
        )
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            actual_path = Path(directory) / "golden.jsonl"
            command = [
                sys.executable,
                str(contract.ROOT / "tools/check_golden.py"),
                "--config",
                str(config_path),
                "--actual",
                str(actual_path),
                "--workers",
                "4",
            ]
            for data in encodings:
                with self.subTest(data_sha256=hashlib.sha256(data).hexdigest()):
                    config_path.write_bytes(data)
                    records = [
                        {
                            "schema_version": 1,
                            "impl": "cpp",
                            "git_sha": "0" * 40,
                            "mode": "golden",
                            "profile_id": profile["profile_id"],
                            "config_sha256": hashlib.sha256(data).hexdigest(),
                            "master_seed": profile["master_seed"],
                            "workers": 4,
                            "case_id": case_id,
                            "outputs": vector["expected"],
                        }
                        for case_id, vector in expected.items()
                    ]
                    actual_path.write_text(
                        "".join(json.dumps(record) + "\n" for record in records)
                    )
                    result = subprocess.run(
                        command, capture_output=True, text=True, check=False, timeout=10
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    mismatch = subprocess.run(
                        [*command[:-1], "1"],
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=10,
                    )
                    self.assertEqual(mismatch.returncode, 1, mismatch.stderr)
                    self.assertIn("workers", mismatch.stderr)
                    config_path.write_bytes(data + b" ")
                    mismatch = subprocess.run(
                        command, capture_output=True, text=True, check=False, timeout=10
                    )
                    self.assertEqual(mismatch.returncode, 1, mismatch.stderr)
                    self.assertIn("config_sha256", mismatch.stderr)

    def test_complex_absolute_tolerance_and_exact_integer(self) -> None:
        with self.assertRaisesRegex(ValueError, "complex absolute error"):
            check_golden.compare([0.0, 0.0], [0.8e-12, 0.8e-12], 1e-12, "complex")
        with self.assertRaises(ValueError):
            check_golden.compare(contract.U64_MAX, contract.U64_MAX - 1, 1e-12, "seed")
        with self.assertRaises(ValueError):
            check_golden.compare(1, True, 1e-12, "bit")


class TheoryChecks(unittest.TestCase):
    def test_regions_match_independent_gray_closed_form(self) -> None:
        def tail(value: float) -> float:
            return math.erfc(value / math.sqrt(2)) / 2

        for esn0 in (0.01, 0.1, 1, 10, 100, 1000):
            argument = math.sqrt(esn0 / 5)
            expected = (
                0.75 * tail(argument)
                + 0.5 * tail(3 * argument)
                - 0.25 * tail(5 * argument)
            )
            self.assertAlmostEqual(theory.awgn_ber(esn0), expected, places=14)
        self.assertEqual(theory.awgn_ber(0), 0.5)

    def test_rayleigh_quadrature_matches_averaged_closed_form(self) -> None:
        def averaged_tail(multiplier: float, esn0: float) -> float:
            argument_sq = multiplier**2 * esn0 / 5
            return (1 - math.sqrt(argument_sq / (argument_sq + 2))) / 2

        for esn0 in (0.1, 1, 10, 100, 1000):
            expected = (
                0.75 * averaged_tail(1, esn0)
                + 0.5 * averaged_tail(3, esn0)
                - 0.25 * averaged_tail(5, esn0)
            )
            actual, error = theory.rayleigh_ber(esn0)
            self.assertLess(abs(actual - expected), 1e-12)
            self.assertLess(error, 1e-10)
        self.assertEqual(theory.rayleigh_ber(0), (0.5, 0.0))

    def test_stored_theory_and_overhead(self) -> None:
        profile = contract.load_json(contract.PROFILE)
        stored = contract.load_json(contract.ROOT / "contract/theory/main.json")
        self.assertEqual(
            [point["ebn0_db"] for point in stored["points"]], profile["ber"]["ebn0_db"]
        )
        self.assertAlmostEqual(
            stored["ebn0_payload_offset_db"], 10 * math.log10(168 / 216)
        )
        for left, right in zip(
            stored["points"][:-1], stored["points"][1:], strict=True
        ):
            self.assertGreater(left["awgn_ber"], right["awgn_ber"])
            self.assertGreater(
                left["rayleigh_perfect_csi_ber"], right["rayleigh_perfect_csi_ber"]
            )


if __name__ == "__main__":
    unittest.main()
