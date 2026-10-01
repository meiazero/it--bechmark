"""Short real CLI correctness checks; no random comparison or timed workload."""

import subprocess
import unittest

import check_golden

import contract
from bench.common import LANGUAGES, command


class CodeGoldenChecks(unittest.TestCase):
    def test_all_golden_interfaces(self):
        # Failure boundaries: missing executable, wrong transform scale/mapping,
        # stale config fingerprint, incomplete vectors, and invalid CLI output.
        directory = contract.ROOT / "results/acceptance/code-golden"
        directory.mkdir(parents=True, exist_ok=True)
        expected = check_golden.load_expected(contract.ROOT / "contract/golden")
        profile = contract.load_json(contract.PROFILE)
        fingerprint = contract.config_sha256(contract.PROFILE.read_bytes())
        for language in LANGUAGES:
            with self.subTest(language=language):
                output = directory / f"{language}.jsonl"
                output.unlink(missing_ok=True)
                result = subprocess.run(
                    command(language, 1, contract.PROFILE, "golden", output),
                    cwd=contract.ROOT,
                    text=True,
                    capture_output=True,
                    timeout=30,
                )
                (directory / f"{language}.stdout").write_text(result.stdout)
                (directory / f"{language}.stderr").write_text(result.stderr)
                self.assertEqual(result.returncode, 0, result.stderr)
                check_golden.verify_records(
                    check_golden.read_records(output), expected, profile, fingerprint, 1
                )


if __name__ == "__main__":
    unittest.main()
