import bisect
import cmath
import math

U64_MASK = (1 << 64) - 1
GRAY_LEVELS = {(0, 0): -3, (0, 1): -1, (1, 1): 1, (1, 0): 3}
LEVEL_BITS = {level: bits for bits, level in GRAY_LEVELS.items()}
SQRT10 = math.sqrt(10)


def encode(values: list[complex]) -> list[list[float]]:
    return [[float(value.real), float(value.imag)] for value in values]


def map_qam(bits: list[int]) -> list[complex]:
    return [
        complex(
            GRAY_LEVELS[tuple(bits[i : i + 2])], GRAY_LEVELS[tuple(bits[i + 2 : i + 4])]
        )
        / SQRT10
        for i in range(0, len(bits), 4)
    ]


def demap_qam(symbols: list[complex]) -> list[int]:
    bits = []
    for symbol in symbols:
        for axis in (symbol.real, symbol.imag):
            scaled = axis * SQRT10
            level = (-3, -1, 1, 3)[bisect.bisect_right((-2, 0, 2), scaled)]
            bits.extend(LEVEL_BITS[level])
    return bits


def grid(symbols: list[complex], profile: dict) -> list[complex]:
    result = [0j] * profile["N_fft"]
    for bins, values in (
        (profile["data_bins"], symbols),
        (profile["pilot_bins"], profile["pilots"]),
    ):
        for bin_number, value in zip(bins, values, strict=True):
            result[bin_number % len(result)] = complex(value)
    return result


def dft(values: list[complex], inverse: bool = False) -> list[complex]:
    size = len(values)
    sign = 1 if inverse else -1
    twiddles = [cmath.exp(sign * 2j * math.pi * index / size) for index in range(size)]
    return [
        sum(value * twiddles[(k * n) % size] for n, value in enumerate(values))
        / math.sqrt(size)
        for k in range(size)
    ]


def add_cp(values: list[complex], length: int) -> list[complex]:
    return values[-length:] + values if length else values[:]


def remove_cp(values: list[complex], length: int, size: int) -> list[complex]:
    return values[length : length + size]


def convolve(values: list[complex], taps: list[complex]) -> list[complex]:
    return [
        sum(tap * values[n - delay] for delay, tap in enumerate(taps) if delay <= n)
        for n in range(len(values))
    ]


def response(taps: list[complex], size: int) -> list[complex]:
    return [
        sum(
            tap * cmath.exp(-2j * math.pi * k * delay / size)
            for delay, tap in enumerate(taps)
        )
        for k in range(size)
    ]


def estimate(
    spectrum: list[complex], profile: dict
) -> tuple[list[complex], list[complex]]:
    bins = profile["pilot_bins"]
    pilots = [
        spectrum[k % profile["N_fft"]] / pilot
        for k, pilot in zip(bins, profile["pilots"], strict=True)
    ]
    estimates = []
    for bin_number in profile["data_bins"]:
        right = bisect.bisect_right(bins, bin_number)
        left = right - 1
        fraction = (bin_number - bins[left]) / (bins[right] - bins[left])
        estimates.append(pilots[left] + fraction * (pilots[right] - pilots[left]))
    return pilots, estimates


def equalize(
    data: list[complex], estimates: list[complex]
) -> tuple[list[complex], int]:
    return (
        [
            value / estimate if estimate != 0 else 0j
            for value, estimate in zip(data, estimates, strict=True)
        ],
        sum(estimate == 0 for estimate in estimates),
    )


def noise_variance(ebn0_db: float, profile: dict) -> float:
    return profile["E_sym"] / (profile["bits_per_symbol"] * 10 ** (ebn0_db / 10))


def splitmix64(seed: int) -> int:
    value = (seed + 0x9E3779B97F4A7C15) & U64_MASK
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & U64_MASK
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & U64_MASK
    return value ^ (value >> 31)


def batch_seed(master: int, point: int, batch: int) -> int:
    return splitmix64(splitmix64(splitmix64(master) ^ point) ^ batch)
