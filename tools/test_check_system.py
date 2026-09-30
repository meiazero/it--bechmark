import contextlib
import io
import os
import unittest
from unittest.mock import patch

import check_system


class SystemChecks(unittest.TestCase):
    def test_version_mismatch_aborts(self) -> None:
        with self.assertRaisesRegex(
            ValueError, "expected 4.3.1-10build1, found 4.3.1-9"
        ):
            check_system.require_version("libitpp-dev", "4.3.1-9", "4.3.1-10build1")

    def test_doctor_reports_missing_tool_as_failure(self) -> None:
        with patch.object(
            check_system, "check_versions", side_effect=FileNotFoundError("julia")
        ):
            with contextlib.redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(check_system.main(), 1)
        self.assertIn("FAIL julia", errors.getvalue())

    def test_live_probe_reports_fftw_and_rng_findings(self) -> None:
        with patch.dict(
            os.environ, {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"}
        ):
            findings = check_system.probe_itpp()
        self.assertIsInstance(findings["rng_same_seed_two_threads_match"], bool)
        self.assertIsInstance(findings["rng_cross_thread_reseed_independent"], bool)
        self.assertLessEqual(findings["fft_scaling_max_abs_error"], 1e-12)
        self.assertEqual(
            findings["fftw_forward_flags"], findings["fftw_backward_flags"]
        )


if __name__ == "__main__":
    unittest.main()
