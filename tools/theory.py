import argparse
import math
import sys
import warnings
from pathlib import Path

import scipy
from scipy import integrate, special

import contract

LEVELS = (-3, -1, 1, 3)
LABELS = ((0, 0), (0, 1), (1, 1), (1, 0))
EDGES = (-math.inf, -2, 0, 2, math.inf)


def normal_interval(lower: float, upper: float) -> float:
    if lower >= 0:
        return float(
            (special.erfc(lower / math.sqrt(2)) - special.erfc(upper / math.sqrt(2)))
            / 2
        )
    return float(
        (special.erfc(-upper / math.sqrt(2)) - special.erfc(-lower / math.sqrt(2))) / 2
    )


def awgn_ber(esn0: float) -> float:
    if not math.isfinite(esn0) or esn0 < 0:
        raise ValueError("Es/N0 must be finite and nonnegative")
    if esn0 == 0:
        return 0.5
    sigma = math.sqrt(5 / esn0)
    error = 0.0
    for level, sent in zip(LEVELS, LABELS, strict=True):
        for index, decided in enumerate(LABELS):
            distance = sum(
                left != right for left, right in zip(sent, decided, strict=True)
            )
            if distance:
                probability = normal_interval(
                    (EDGES[index] - level) / sigma, (EDGES[index + 1] - level) / sigma
                )
                error += distance * probability / 8
    return error


def rayleigh_ber(esn0: float) -> tuple[float, float]:
    if not math.isfinite(esn0) or esn0 < 0:
        raise ValueError("Es/N0 must be finite and nonnegative")
    if esn0 == 0:
        return 0.5, 0.0
    with warnings.catch_warnings():
        warnings.simplefilter("error", integrate.IntegrationWarning)
        value, error = integrate.quad(
            lambda gain: awgn_ber(esn0 * gain) * math.exp(-gain),
            0,
            math.inf,
            epsabs=1e-12,
            epsrel=1e-10,
            limit=200,
        )
    return float(value), float(error)


def generate(profile: dict) -> dict:
    ratio = profile["bits_per_symbol"] / profile["E_sym"]
    points = []
    for ebn0_db in profile["ber"]["ebn0_db"]:
        esn0 = 10 ** (ebn0_db / 10) * ratio
        rayleigh, error = rayleigh_ber(esn0)
        points.append(
            {
                "ebn0_db": ebn0_db,
                "esn0_linear": esn0,
                "awgn_ber": awgn_ber(esn0),
                "rayleigh_perfect_csi_ber": rayleigh,
                "rayleigh_quad_abs_error": error,
            }
        )
    return {
        "schema_version": 1,
        "profile_id": profile["profile_id"],
        "scipy_version": scipy.__version__,
        "csi": "perfect",
        "esn0_per_ebn0": ratio,
        "ebn0_payload_offset_db": 10 * math.log10(ratio / 4),
        "quadrature": {"epsabs": 1e-12, "epsrel": 1e-10, "limit": 200},
        "points": points,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate exact Gray 16-QAM theory curves"
    )
    parser.add_argument("--config", type=Path, default=contract.PROFILE)
    parser.add_argument(
        "--out", type=Path, default=contract.ROOT / "contract/theory/main.json"
    )
    args = parser.parse_args()
    try:
        profile = contract.load_json(args.config)
        contract.validate_config(profile)
        result = generate(profile)
        contract.write_json(args.out, result)
    except (
        OSError,
        ValueError,
        TypeError,
        OverflowError,
        integrate.IntegrationWarning,
    ) as error:
        print(f"FAIL theory: {error}", file=sys.stderr)
        return 1
    print(
        "PASS generated exact AWGN and Rayleigh-CSI theory "
        f"({len(result['points'])} points)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
