"""Batched NumPy OFDM simulation and the shared artifact CLI."""

import argparse
import concurrent.futures
import json
import math
import multiprocessing
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tools import contract

MASK = (1 << 64) - 1
BATCH_BITS = 256 * 672
SQRT10 = math.sqrt(10)


def splitmix(seed: int) -> int:
    value = (seed + 0x9E3779B97F4A7C15) & MASK
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & MASK
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & MASK
    return value ^ (value >> 31)


def batch_seed(master: int, point: int, batch: int) -> int:
    return splitmix(splitmix(splitmix(master) ^ point) ^ batch)


def decode(values: list) -> np.ndarray:
    pairs = np.asarray(values, dtype=np.float64)
    return pairs[..., 0] + 1j * pairs[..., 1]


def encode(values: np.ndarray) -> list:
    return np.stack((values.real, values.imag), axis=-1).tolist()


def map_qam(bits: np.ndarray) -> np.ndarray:
    groups = bits.reshape(*bits.shape[:-1], -1, 4)
    levels = np.array([-3, -1, 3, 1])
    return (
        levels[2 * groups[..., 0] + groups[..., 1]]
        + 1j * levels[2 * groups[..., 2] + groups[..., 3]]
    ) / SQRT10


def demap(values: np.ndarray) -> np.ndarray:
    axes = np.stack((values.real, values.imag), axis=-1) * SQRT10
    bits = np.stack((axes >= 0, (axes >= -2) & (axes < 2)), axis=-1)
    return bits.reshape(*values.shape[:-1], -1).astype(np.uint8)


def convolve(values: np.ndarray, taps: np.ndarray) -> np.ndarray:
    output = np.zeros_like(values)
    for delay in range(taps.shape[-1]):
        output[..., delay:] += (
            taps[..., delay, None] * values[..., : values.shape[-1] - delay]
        )
    return output


def equalize(data: np.ndarray, estimates: np.ndarray) -> tuple[np.ndarray, int]:
    nonzero = estimates != 0
    return np.divide(data, estimates, out=np.zeros_like(data), where=nonzero), int(
        np.count_nonzero(~nonzero)
    )


def noise_variance(point: float, config: dict) -> float:
    value = config["E_sym"] / (672 * 10 ** (point / 10))
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Eb/N0 exceeds the finite noise range")
    return value


class Worker:
    def __init__(self, config: dict) -> None:
        self.config = config
        self.data = np.array(config["data_bins"]) % 256
        self.pilots = np.array(config["pilot_bins"]) % 256
        bins = np.array(config["pilot_bins"])
        self.right = np.searchsorted(bins, config["data_bins"], side="right")
        self.left = self.right - 1
        self.fraction = (np.array(config["data_bins"]) - bins[self.left]) / (
            bins[self.right] - bins[self.left]
        )
        self.tap_scale = np.sqrt(np.array(config["pdp"]) / 2)
        self.rng = np.random.Generator(np.random.PCG64(0))
        np.fft.fft(np.zeros((256, 256), dtype=np.complex128), norm="ortho")

    def bits(self) -> np.ndarray:
        return self.rng.integers(0, 2, size=(256, 672), dtype=np.uint8)

    def taps(self) -> np.ndarray:
        if self.config["channel"] == "awgn":
            return np.ones((256, 1), dtype=np.complex128)
        draws = self.rng.standard_normal((256, 8, 2))
        return (draws[..., 0] + 1j * draws[..., 1]) * self.tap_scale

    def grid(self, values: np.ndarray) -> np.ndarray:
        output = np.zeros((*values.shape[:-1], 256), dtype=np.complex128)
        output[..., self.data] = values
        output[..., self.pilots] = self.config["pilots"]
        return output

    def estimate(self, spectrum: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        pilots = spectrum[..., self.pilots] / np.array(self.config["pilots"])
        return pilots, pilots[..., self.left] + self.fraction * (
            pilots[..., self.right] - pilots[..., self.left]
        )

    def awgn(self, values: np.ndarray, n0: float) -> np.ndarray:
        draws = self.rng.standard_normal((*values.shape, 2))
        return values + (draws[..., 0] + 1j * draws[..., 1]) * math.sqrt(n0 / 2)

    def decide(self, values: np.ndarray, original: np.ndarray) -> dict:
        errors = demap(values) != original
        return {
            "n_errors": int(np.count_nonzero(errors)),
            "n_symbols_with_errors": int(np.count_nonzero(np.any(errors, axis=-1))),
        }

    def batch(self, seed: int, point: float) -> dict:
        self.rng = np.random.Generator(np.random.PCG64(seed))
        original = self.bits()
        spectrum = self.grid(map_qam(original))
        values = np.fft.ifft(spectrum, norm="ortho")
        prefixed = np.concatenate((values[..., -32:], values), axis=-1)
        taps = self.taps()
        received = self.awgn(
            convolve(prefixed, taps), noise_variance(point, self.config)
        )
        rx = np.fft.fft(received[..., 32:288], norm="ortho")
        estimates = (
            np.fft.fft(taps, n=256)[..., self.data]
            if self.config["csi"] == "perfect"
            else self.estimate(rx)[1]
        )
        values, zeros = equalize(rx[..., self.data], estimates)
        counts = self.decide(values, original)
        counts.update(
            n_batches=1,
            zf_zero_count=zeros,
            sum_batch_errors_sq=counts["n_errors"] ** 2,
        )
        return counts

    def stages(self, seed: int, point: float) -> dict:
        self.rng = np.random.Generator(np.random.PCG64(seed))
        original = self.bits()
        qam = map_qam(original)
        spectrum = self.grid(qam)
        values = np.fft.ifft(spectrum, norm="ortho")
        prefixed = np.concatenate((values[..., -32:], values), axis=-1)
        taps = self.taps()
        received = convolve(prefixed, taps)
        n0 = noise_variance(point, self.config)
        noisy = self.awgn(received, n0)
        stripped = noisy[..., 32:288].copy()
        rx = np.fft.fft(stripped, norm="ortho")
        estimates = self.estimate(rx)[1]
        eq = equalize(rx[..., self.data], estimates)[0]
        actions = {
            "bits": self.bits,
            "qam_map": lambda: map_qam(original),
            "grid": lambda: self.grid(qam),
            "ifft": lambda: np.fft.ifft(spectrum, norm="ortho"),
            "cp_add": lambda: np.concatenate((values[..., -32:], values), axis=-1),
            "channel_conv": lambda: convolve(prefixed, self.taps()),
            "awgn": lambda: self.awgn(received, n0),
            "cp_remove": lambda: noisy[..., 32:288].copy(),
            "fft": lambda: np.fft.fft(stripped, norm="ortho"),
            "chan_est": lambda: self.estimate(rx),
            "zf": lambda: equalize(rx[..., self.data], estimates),
            "demap_count": lambda: self.decide(eq, original),
            "e2e": lambda: self.batch(seed, point),
        }
        timings = {}
        for name, action in actions.items():
            samples = []
            for _ in range(self.config["stages"]["repetitions"]):
                start = time.perf_counter_ns()
                action()
                samples.append((time.perf_counter_ns() - start) / 256)
            timings[name] = statistics.median(samples)
        return timings

    def golden(self, case_id: str, inputs: dict) -> dict:
        if case_id == "qam_map":
            return {"symbols": encode(map_qam(np.array(inputs["bits"])))}
        if case_id == "demap":
            return {"bits": demap(decode(inputs["symbols"])).tolist()}
        if case_id == "grid":
            spectrum = self.grid(decode(inputs["symbols"]))
            return {
                "spectrum": encode(spectrum),
                "data": encode(spectrum[self.data]),
                "pilots": encode(spectrum[self.pilots]),
            }
        if case_id in ("transforms", "fft_impulse"):
            values = decode(inputs["values"])
            return {
                "fft": encode(np.fft.fft(values, norm="ortho")),
                "ifft": encode(np.fft.ifft(values, norm="ortho")),
            }
        if case_id == "cp":
            values = decode(inputs["values"])
            prefixed = np.concatenate((values[-32:], values))
            return {"with_cp": encode(prefixed), "without_cp": encode(prefixed[32:288])}
        if case_id == "channel":
            taps = decode(inputs["taps"])
            return {
                "convolved": encode(convolve(decode(inputs["values"]), taps)),
                "response": encode(np.fft.fft(taps, n=256)),
            }
        if case_id == "estimation":
            pilots, estimates = self.estimate(decode(inputs["spectrum"]))
            return {
                "pilot_estimates": encode(pilots),
                "data_estimates": encode(estimates),
            }
        if case_id == "zf":
            values, zeros = equalize(
                decode(inputs["data"]), decode(inputs["estimates"])
            )
            return {"equalized": encode(values), "zf_zero_count": zeros}
        if case_id == "noise_seed":
            return {
                "N0": [noise_variance(p, self.config) for p in inputs["ebn0_db"]],
                "splitmix_outputs": [splitmix(s) for s in inputs["splitmix_inputs"]],
                "batch_seeds": [
                    batch_seed(*triple) for triple in inputs["batch_seed_inputs"]
                ],
            }
        if case_id != "end_to_end":
            raise ValueError(f"Unknown golden case: {case_id}")
        original = np.array(inputs["bits"])
        taps = decode(inputs["taps"])
        spectrum = self.grid(map_qam(original))
        values = np.fft.ifft(spectrum, norm="ortho")
        prefixed = np.concatenate((values[-32:], values))
        received = convolve(prefixed, taps) + decode(inputs["noise"])
        rx = np.fft.fft(received[32:288], norm="ortho")
        pilots, estimates = self.estimate(rx)
        eq, zeros = equalize(rx[self.data], estimates)
        perfect = equalize(rx[self.data], np.fft.fft(taps, n=256)[self.data])[0]
        bits = demap(eq)
        return {
            "spectrum": encode(spectrum),
            "time": encode(values),
            "with_cp": encode(prefixed),
            "received": encode(received),
            "received_fft": encode(rx),
            "pilot_estimates": encode(pilots),
            "data_estimates": encode(estimates),
            "equalized": encode(eq),
            "bits": bits.tolist(),
            "perfect_bits": demap(perfect).tolist(),
            "n_errors": int(np.count_nonzero(bits != original)),
            "zf_zero_count": zeros,
        }


_worker: Worker | None = None


def initialize(config: dict, barrier: Any) -> None:
    global _worker
    _worker = Worker(config)
    barrier.wait(timeout=60)


def task(arguments: tuple[int, float] | None) -> dict | None:
    if _worker is None:
        raise RuntimeError("Worker not initialized")
    return _worker.batch(*arguments) if arguments is not None else None


def measure(
    config: dict, mode: str, workers: int, base: dict, setup_start: float
) -> list[dict]:
    context = multiprocessing.get_context("forkserver")
    barrier = context.Barrier(workers + 1)
    records = []
    local = Worker(config) if mode == "stages" else None
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=workers,
        mp_context=context,
        initializer=initialize,
        initargs=(config, barrier),
    ) as pool:
        # Blocking initialization forces all processes to exist before warmup.
        futures = [pool.submit(task, None) for _ in range(workers)]
        barrier.wait(timeout=60)
        for future in futures:
            future.result()
        setup_s = time.perf_counter() - setup_start
        start = time.perf_counter()
        warm_seed = splitmix(config["master_seed"] ^ 0x7761726D7570)
        list(
            pool.map(
                task, ((batch_seed(warm_seed, 0, i), 10) for i in range(4)), chunksize=1
            )
        )
        warmup_s = time.perf_counter() - start
        points = config["ber"]["ebn0_db"] if mode == "ber" else [10]
        for point_index, point in enumerate(points):
            counts = dict.fromkeys(
                (
                    "n_batches",
                    "n_errors",
                    "sum_batch_errors_sq",
                    "n_symbols_with_errors",
                    "zf_zero_count",
                ),
                0,
            )
            limit = (
                (config["ber"]["max_bits"] + BATCH_BITS - 1) // BATCH_BITS
                if mode == "ber"
                else config["perf"]["n_batches"]
                if mode == "perf"
                else 1
            )
            start = time.perf_counter()
            status = "max_bits" if mode == "ber" else "fixed_work"
            stop = False
            for first in range(0, limit, max(4, workers * 2)):
                last = min(limit, first + max(4, workers * 2))
                results = list(
                    pool.map(
                        task,
                        (
                            (batch_seed(config["master_seed"], point_index, i), point)
                            for i in range(first, last)
                        ),
                        chunksize=1,
                    )
                )
                for result in results:
                    for name, value in result.items():
                        counts[name] += value
                        if counts[name] > MASK:
                            raise OverflowError("u64 counter overflow")
                    if mode == "ber":
                        if (
                            counts["n_batches"] >= config["ber"]["min_batches"]
                            and counts["n_errors"] >= config["ber"]["target_errors"]
                        ):
                            status, stop = "target_errors", True
                        elif (
                            counts["n_batches"] * BATCH_BITS
                            >= config["ber"]["max_bits"]
                        ):
                            stop = True
                    if stop:
                        break
                if stop:
                    break
            timings = (
                local.stages(batch_seed(config["master_seed"], point_index, 0), point)
                if local
                else None
            )
            work_s = time.perf_counter() - start
            record = {
                **base,
                **counts,
                "ebn0_db": point,
                "n_symbols": counts["n_batches"] * 256,
                "n_bits": counts["n_batches"] * BATCH_BITS,
                "status": status,
                "setup_s": setup_s,
                "warmup_s": warmup_s,
                "work_s": work_s,
            }
            if timings:
                record["stage_ns_per_symbol"] = timings
            records.append(record)
    return records


def main() -> int:
    setup_start = time.perf_counter()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument(
        "--mode", required=True, choices=("golden", "ber", "perf", "stages")
    )
    parser.add_argument("--workers", required=True, type=int)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        contract.integer(args.workers, "workers")
        data = args.config.read_bytes()
        config = contract.parse_json(data.decode("utf-8"))
        contract.validate_config(config, args.mode)
        for point in config["ber"]["ebn0_db"]:
            noise_variance(point, config)
    except (OSError, ValueError, TypeError, OverflowError) as error:
        print(f"Invalid configuration: {error}", file=sys.stderr)
        return 2
    try:
        git_sha = subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
        ).strip()
        base = {
            "schema_version": 1,
            "impl": "python",
            "git_sha": git_sha,
            "mode": args.mode,
            "profile_id": config["profile_id"],
            "master_seed": config["master_seed"],
            "config_sha256": contract.config_sha256(data),
            "workers": args.workers,
        }
        if args.mode == "golden":
            worker = Worker(config)
            vectors = [
                contract.load_json(path)
                for path in sorted((ROOT / "contract/golden").glob("*.json"))
            ]
            records = [
                {
                    **base,
                    "case_id": vector["case_id"],
                    "outputs": worker.golden(vector["case_id"], vector["inputs"]),
                }
                for vector in vectors
            ]
        else:
            records = measure(config, args.mode, args.workers, base, setup_start)
        output = "".join(
            json.dumps(record, allow_nan=False) + "\n" for record in records
        )
        temporary = args.out.with_name(
            args.out.name + f".tmp.{multiprocessing.current_process().pid}"
        )
        temporary.write_text(output)
        temporary.replace(args.out)
        return 0
    except (OSError, RuntimeError, ValueError, TypeError, OverflowError) as error:
        print(f"Execution failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
