"""Check aggregate inference against independently retained batch observations."""

import unittest

import numpy as np
from scipy import stats

from bench.statistics import batch_summary, theory_check, welch


def record(samples):
    return {
        "n_batches": len(samples),
        "n_bits": len(samples) * 172032,
        "n_symbols": len(samples) * 256,
        "n_errors": sum(samples),
        "sum_batch_errors_sq": sum(x * x for x in samples),
    }


class InferenceChecks(unittest.TestCase):
    def test_batch_moments_and_interval_against_raw_batches(self):
        samples = [1, 3, 4, 6, 11, 13, 15, 19, 22, 24, 25, 26, 26]
        rates = np.asarray(samples) / 172032
        summary = batch_summary(record(samples))
        np.testing.assert_allclose(summary["mean"], np.mean(rates), rtol=1e-12, atol=0)
        np.testing.assert_allclose(
            summary["variance"], np.var(rates, ddof=1), rtol=1e-12, atol=0
        )
        expected = stats.t.interval(
            0.95, len(samples) - 1, loc=np.mean(rates), scale=stats.sem(rates)
        )
        result = theory_check(record(samples), float(np.mean(rates)), 0.05)
        self.assertEqual(result["status"], "compatible")
        self.assertAlmostEqual(result["lower"], expected[0])
        self.assertAlmostEqual(result["upper"], expected[1])
        self.assertEqual(
            theory_check(record(samples), 0.5, 0.05)["status"], "incompatible"
        )

    def test_welch_against_raw_unequal_size_variance_samples(self):
        a = [1, 3, 4, 6, 11, 13, 15, 19, 22, 24, 25, 26, 26]
        b = [2, 4, 6, 9, 11, 13, 14, 15, 18, 19, 21]
        expected = stats.ttest_ind(
            np.asarray(a) / 172032, np.asarray(b) / 172032, equal_var=False
        )
        actual = welch(record(a), record(b), 0.01 / 96)
        self.assertAlmostEqual(actual["p_value"], expected.pvalue, places=12)
        self.assertAlmostEqual(actual["df"], expected.df, places=12)
        self.assertAlmostEqual(actual["statistic"], expected.statistic, places=12)
        self.assertIn(actual["status"], ("compatible", "incompatible"))

    def test_sparse_or_degenerate_batches_are_never_auto_approved(self):
        zeros = record([0] * 32)
        result = theory_check(zeros, 0, 0.01 / 128)
        self.assertEqual(result["status"], "evidence_insufficient")
        self.assertIsNone(result["lower"])
        self.assertGreater(result["zero_symbol_upper95"], 0)
        self.assertEqual(
            welch(zeros, zeros, 0.01 / 96)["status"], "evidence_insufficient"
        )
        with self.assertRaises(ValueError):
            batch_summary({**record([100, 101, 102]), "sum_batch_errors_sq": 0})


if __name__ == "__main__":
    unittest.main()
