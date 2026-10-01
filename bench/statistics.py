"""Fixed-batch uncertainty; bit independence and adaptive coverage are not assumed."""

import math

from scipy import stats

BATCH_BITS = 172032


def batch_summary(record):
    n = record["n_batches"]
    if n < 2 or record["n_bits"] != n * BATCH_BITS:
        raise ValueError("At least two complete fixed batches are required")
    total = record["n_errors"]
    numerator = n * record["sum_batch_errors_sq"] - total * total
    if numerator < 0:
        raise ValueError("Inconsistent batch moments")
    variance = numerator / (n * (n - 1) * BATCH_BITS**2)
    return {
        "n": n,
        "mean": total / (n * BATCH_BITS),
        "variance": variance,
        "se": math.sqrt(variance / n),
    }


def theory_check(record, theory, alpha):
    summary = batch_summary(record)
    result = {
        **summary,
        "theory": theory,
        "alpha_local": alpha,
        "lower": None,
        "upper": None,
        "p_value": None,
        "zero_symbol_upper95": None,
    }
    if record["n_errors"] < 100 or summary["variance"] == 0:
        result["status"] = "evidence_insufficient"
        if record["n_errors"] == 0:
            result["zero_symbol_upper95"] = -math.expm1(
                math.log(0.05) / record["n_symbols"]
            )
        return result
    radius = stats.t.isf(alpha / 2, summary["n"] - 1) * summary["se"]
    result.update(
        lower=max(0.0, summary["mean"] - radius),
        upper=min(1.0, summary["mean"] + radius),
        p_value=float(
            2
            * stats.t.sf(
                abs(summary["mean"] - theory) / summary["se"], summary["n"] - 1
            )
        ),
    )
    result["status"] = (
        "compatible" if result["lower"] <= theory <= result["upper"] else "incompatible"
    )
    return result


def welch(first, second, alpha):
    a, b = batch_summary(first), batch_summary(second)
    difference = a["mean"] - b["mean"]
    v1, v2 = a["variance"] / a["n"], b["variance"] / b["n"]
    result = {
        "difference": difference,
        "alpha_local": alpha,
        "df": None,
        "lower": None,
        "upper": None,
        "ci95_lower": None,
        "ci95_upper": None,
        "p_value": None,
        "statistic": None,
    }
    if v1 + v2 == 0:
        return {**result, "status": "evidence_insufficient"}
    df = (v1 + v2) ** 2 / (v1**2 / (a["n"] - 1) + v2**2 / (b["n"] - 1))
    test = stats.ttest_ind_from_stats(
        a["mean"],
        math.sqrt(a["variance"]),
        a["n"],
        b["mean"],
        math.sqrt(b["variance"]),
        b["n"],
        equal_var=False,
    )
    se = math.sqrt(v1 + v2)
    radius = stats.t.isf(alpha / 2, df) * se
    radius95 = stats.t.isf(0.025, df) * se
    result.update(
        df=df,
        lower=difference - radius,
        upper=difference + radius,
        ci95_lower=difference - radius95,
        ci95_upper=difference + radius95,
        p_value=float(test.pvalue),
        statistic=float(test.statistic),
        status="incompatible" if test.pvalue < alpha else "compatible",
    )
    return result
