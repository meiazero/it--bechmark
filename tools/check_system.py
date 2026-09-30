import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM_PACKAGES = {
    "libitpp-dev": "4.3.1-10build1",
    "libfftw3-dev": "3.3.10-1ubuntu3",
    "nlohmann-json3-dev": "3.11.3-1",
}
THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "PYTHONHASHSEED": "0",
}
TOOL_COMMANDS = {
    "python": ["python", "--version"],
    "uv": ["uv", "--version"],
    "julia": ["julia", "--version"],
    "rust": ["rustc", "--version"],
    "cmake": ["cmake", "--version"],
    "ninja": ["ninja", "--version"],
    "tokei": ["tokei", "--version"],
}


def run(command: list[str], timeout: int = 30) -> str:
    result = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, timeout=timeout, check=True
    )
    return result.stdout.strip()


def require_version(name: str, actual: str, expected: str) -> None:
    if actual != expected:
        raise ValueError(f"{name}: expected {expected}, found {actual}")
    print(f"PASS {name}: {actual}", flush=True)


def check_versions(config: dict) -> None:
    for tool, command in TOOL_COMMANDS.items():
        output = run(command).splitlines()[0]
        match = re.search(r"\b\d+\.\d+\.\d+\b", output)
        if match is None:
            raise ValueError(f"{tool}: cannot parse version from {output!r}")
        require_version(tool, match.group(), config["tools"][tool])
    require_version(
        "g++ compiler", run(["g++", "-dumpfullversion", "-dumpversion"]), "13.3.0"
    )
    for package, expected in SYSTEM_PACKAGES.items():
        output = run(
            ["dpkg-query", "-W", "-f=${db:Status-Status}\t${Version}", package]
        )
        status, version = output.split("\t")
        if status != "installed":
            raise ValueError(f"{package}: package is not installed ({status})")
        require_version(package, version, expected)
    for library, expected in {"itpp": "4.3.1", "fftw3": "3.3.10"}.items():
        require_version(
            f"pkg-config {library}",
            run(["pkg-config", "--modversion", library]),
            expected,
        )
    for variable, expected in THREAD_ENV.items():
        require_version(variable, os.environ.get(variable, "<unset>"), expected)
    run(["git", "rev-parse", "--git-dir"])
    print("PASS Git repository initialized", flush=True)


def probe_itpp() -> dict:
    flags = shlex.split(run(["pkg-config", "--cflags", "--libs", "itpp", "fftw3"]))
    with tempfile.TemporaryDirectory(prefix="ofdm-m0-") as temporary:
        executable = str(Path(temporary) / "environment_probe")
        run(
            [
                "g++",
                "-std=c++20",
                "-O3",
                "-march=native",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-pthread",
                "-rdynamic",
                str(ROOT / "impl/cpp/tests/environment_probe.cpp"),
                "-o",
                executable,
                *flags,
                "-ldl",
            ],
            timeout=120,
        )
        return json.loads(run([executable]))


def main() -> int:
    try:
        with (ROOT / "mise.toml").open("rb") as source:
            config = tomllib.load(source)
        check_versions(config)
        findings = probe_itpp()
        print(json.dumps(findings, sort_keys=True))
        for direction in ("forward", "backward"):
            require_version(
                f"FFTW {direction} planning flags",
                str(findings[f"fftw_{direction}_flags"]),
                "64",
            )
        independent = (
            findings["rng_same_seed_two_threads_match"]
            and findings["rng_cross_thread_reseed_independent"]
        )
        rng_choice = "thread-local" if independent else "use std::mt19937_64"
        print(f"PASS IT++ RNG investigation: {rng_choice}")
        print("PASS M0 doctor")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"FAIL {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr.strip(), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
