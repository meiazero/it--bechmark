import itertools
import math

from tools import contract
from tools.golden import reference as ref


def cases(profile: dict) -> dict[str, tuple[dict, dict]]:
    result = {}
    size = profile["N_fft"]
    bits16 = list(itertools.chain.from_iterable(itertools.product((0, 1), repeat=4)))
    symbols16 = ref.map_qam(bits16)
    result["qam_map"] = ({"bits": bits16}, {"symbols": ref.encode(symbols16)})
    thresholds = [-2 / ref.SQRT10, 0.0, 2 / ref.SQRT10]
    levels = [-3 / ref.SQRT10, -1 / ref.SQRT10, 1 / ref.SQRT10, 3 / ref.SQRT10]
    axes = levels + [
        value + delta for value in thresholds for delta in (-1e-10, 0, 1e-10)
    ]
    decisions = [complex(real, imag) for real in axes for imag in axes]
    result["demap"] = (
        {"symbols": ref.encode(decisions)},
        {"bits": ref.demap_qam(decisions)},
    )
    bits = [
        ((index * 37 + index // 7 + 11) % 17) % 2
        for index in range(profile["bits_per_symbol"])
    ]
    symbols = ref.map_qam(bits)
    spectrum = ref.grid(symbols, profile)
    result["grid"] = (
        {"bits": bits, "symbols": ref.encode(symbols)},
        {
            "spectrum": ref.encode(spectrum),
            "data": ref.encode([spectrum[k % size] for k in profile["data_bins"]]),
            "pilots": ref.encode([spectrum[k % size] for k in profile["pilot_bins"]]),
        },
    )
    fixed = [
        complex(((n * 13) % 29 - 14) / 16, ((n * 7) % 23 - 11) / 32)
        for n in range(size)
    ]
    result["transforms"] = (
        {"values": ref.encode(fixed)},
        {"fft": ref.encode(ref.dft(fixed)), "ifft": ref.encode(ref.dft(fixed, True))},
    )
    impulse = [1 + 0j] + [0j] * (size - 1)
    result["fft_impulse"] = (
        {"values": ref.encode(impulse)},
        {
            "fft": ref.encode(ref.dft(impulse)),
            "ifft": ref.encode(ref.dft(impulse, True)),
        },
    )
    time = ref.dft(spectrum, True)
    prefixed = ref.add_cp(time, profile["N_cp"])
    result["cp"] = (
        {"values": ref.encode(time)},
        {
            "with_cp": ref.encode(prefixed),
            "without_cp": ref.encode(ref.remove_cp(prefixed, profile["N_cp"], size)),
        },
    )
    taps = [
        0.9 + 0.1j,
        0.04 - 0.025j,
        -0.02 + 0.01j,
        0.012 + 0.008j,
        -0.006 - 0.004j,
        0.003 + 0.002j,
        -0.001 + 0.002j,
        0.001 - 0.001j,
    ]
    received = ref.convolve(prefixed, taps)
    result["channel"] = (
        {"values": ref.encode(prefixed), "taps": ref.encode(taps)},
        {
            "convolved": ref.encode(received),
            "response": ref.encode(ref.response(taps, size)),
        },
    )
    pilot_channels = [
        complex(1 + k / 128 + (k / 96) ** 2 / 5, k / 256 + (k / 96) ** 3 / 7)
        for k in profile["pilot_bins"]
    ]
    fixed_y = fixed[:]
    for k, pilot, channel in zip(
        profile["pilot_bins"], profile["pilots"], pilot_channels, strict=True
    ):
        fixed_y[k % size] = pilot * channel
    pilots, estimates = ref.estimate(fixed_y, profile)
    result["estimation"] = (
        {"spectrum": ref.encode(fixed_y)},
        {
            "pilot_estimates": ref.encode(pilots),
            "data_estimates": ref.encode(estimates),
        },
    )
    zf_data = [1 + 2j, 3 - 4j, 0j, -2 + 0.5j, 1e-15j]
    zf_estimates = [2 - 1j, 0j, 0j, -0.5 + 0.25j, 1e-15 + 0j]
    zf, zero_count = ref.equalize(zf_data, zf_estimates)
    result["zf"] = (
        {"data": ref.encode(zf_data), "estimates": ref.encode(zf_estimates)},
        {"equalized": ref.encode(zf), "zf_zero_count": zero_count},
    )
    points = [-10, 0, 10, 20, 30]
    seeds = [0, 1, 0xFFFFFFFF, 0x100000000, 0x0123456789ABCDEF, ref.U64_MASK]
    triples = [
        [0, 0, 0],
        [profile["master_seed"], 15, 5812],
        [ref.U64_MASK, ref.U64_MASK, ref.U64_MASK],
        [1, 0, 7],
        [1 << 32 | 1, 0, 7],
    ]
    result["noise_seed"] = (
        {"ebn0_db": points, "splitmix_inputs": seeds, "batch_seed_inputs": triples},
        {
            "N0": [ref.noise_variance(point, profile) for point in points],
            "splitmix_outputs": [ref.splitmix64(seed) for seed in seeds],
            "batch_seeds": [ref.batch_seed(*triple) for triple in triples],
        },
    )
    received_fft = ref.dft(ref.remove_cp(received, profile["N_cp"], size))
    rx_data = [received_fft[k % size] for k in profile["data_bins"]]
    pilots, estimates = ref.estimate(received_fft, profile)
    estimated, zero_count = ref.equalize(rx_data, estimates)
    response = ref.response(taps, size)
    perfect, _ = ref.equalize(
        rx_data, [response[k % size] for k in profile["data_bins"]]
    )
    recovered = ref.demap_qam(estimated)
    perfect_bits = ref.demap_qam(perfect)
    if recovered != bits or perfect_bits != bits or zero_count:
        raise ValueError(
            "Noiseless multipath golden case failed to recover its payload"
        )
    result["end_to_end"] = (
        {
            "bits": bits,
            "taps": ref.encode(taps),
            "noise": ref.encode([0j] * len(prefixed)),
        },
        {
            "spectrum": ref.encode(spectrum),
            "time": ref.encode(time),
            "with_cp": ref.encode(prefixed),
            "received": ref.encode(received),
            "received_fft": ref.encode(received_fft),
            "pilot_estimates": ref.encode(pilots),
            "data_estimates": ref.encode(estimates),
            "equalized": ref.encode(estimated),
            "bits": recovered,
            "perfect_bits": perfect_bits,
            "n_errors": 0,
            "zf_zero_count": zero_count,
        },
    )
    if not math.isclose(sum(abs(value) ** 2 for value in symbols16) / 16, 1):
        raise ValueError("The QAM alphabet has incorrect average energy")
    return result


def main() -> None:
    profile = contract.load_json(contract.PROFILE)
    contract.validate_config(profile)
    vectors = cases(profile)
    for name, (inputs, expected) in vectors.items():
        contract.write_json(
            contract.ROOT / f"contract/golden/{name}.json",
            {
                "schema_version": 1,
                "profile_id": profile["profile_id"],
                "case_id": name,
                "inputs": inputs,
                "expected": expected,
            },
        )
    print(f"PASS generated {len(vectors)} golden cases (Python standard library only)")


if __name__ == "__main__":
    main()
