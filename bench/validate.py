"""Collect predeclared fixed samples and report theory/mean compatibility."""

import argparse
import copy
import csv
import itertools
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from bench.common import LANGUAGES, ROOT, ac_online, command, environment, read_results
from bench.statistics import theory_check, welch
from tools import contract

LABELS = {"cpp": "C++/IT++", "python": "Python/NumPy", "rust": "Rust", "julia": "Julia"}
STATUS = {
    "compatible": "compatível",
    "incompatible": "incompatível",
    "evidence_insufficient": "evidência insuficiente",
}


def collect():
    protocol = contract.load_json(ROOT / "bench/validation_protocol.json")
    profile = contract.load_json(contract.PROFILE)
    n = protocol["fixed_batches"]
    run_id = datetime.now(UTC).strftime("validation-%Y%m%dT%H%M%S") + f"-{os.getpid()}"
    directory = ROOT / "results" / run_id
    (directory / "raw").mkdir(parents=True, exist_ok=False)
    env = environment(0, "validation")
    os.sched_setaffinity(0, {0})
    contract.write_json(directory / "env.json", env)
    manifest = {
        "run_id": run_id,
        "protocol": protocol,
        "completed": False,
        "points": profile["ber"]["ebn0_db"],
        "executions": [],
        "prepared_at_utc": datetime.now(UTC).isoformat(),
        "protocol_sha256": contract.config_sha256(
            (ROOT / "bench/validation_protocol.json").read_bytes()
        ),
    }
    for scenario in protocol["scenarios"]:
        config = copy.deepcopy(profile)
        config.update(
            channel=scenario["channel"],
            csi=scenario["csi"],
            master_seed=protocol["master_seed"],
        )
        config["ber"].update(
            min_batches=n, max_bits=n * 172032, target_errors=n * 172032 + 1
        )
        config_path = directory / f"{scenario['id']}.json"
        contract.write_json(config_path, config)
        for language in LANGUAGES:
            manifest["executions"].append(
                {
                    "id": f"{scenario['id']}-{language}",
                    "scenario": scenario["id"],
                    "impl": language,
                    "config": config_path.name,
                    "output": f"raw/{scenario['id']}-{language}.jsonl",
                    "completed": False,
                }
            )
    # Protocol, configurations and entire execution list exist before outcomes.
    contract.write_json(directory / "manifest.json", manifest)
    for execution in manifest["executions"]:
        if not ac_online():
            raise RuntimeError("AC disconnected; connect the charger")
        output = directory / execution["output"]
        invocation = [
            "taskset",
            "-c",
            "2",
            *command(
                execution["impl"], 1, directory / execution["config"], "ber", output
            ),
        ]
        execution["command"] = invocation
        contract.write_json(directory / "manifest.json", manifest)
        with (
            (directory / f"raw/{execution['id']}.stdout").open("w") as stdout,
            (directory / f"raw/{execution['id']}.stderr").open("w") as stderr,
        ):
            result = subprocess.run(
                invocation,
                stdout=stdout,
                stderr=stderr,
                cwd=ROOT,
                timeout=900,
                env={
                    **os.environ,
                    "BENCH_PHASE_PATH": str(directory / f"raw/{execution['id']}.phase"),
                },
            )
        if result.returncode:
            raise RuntimeError(f"{execution['id']} failed; see its retained stderr")
        records = read_results(
            output, directory / execution["config"], execution["impl"], 1, "ber"
        )
        if any(r["n_batches"] != n or r["status"] != "max_bits" for r in records):
            raise ValueError("Validation did not stop at the predeclared fixed budget")
        execution["completed"] = True
        contract.write_json(directory / "manifest.json", manifest)
        print(
            f"Collected {execution['id']}: {n} fixed batches × {len(records)} points",
            flush=True,
        )
    manifest["completed"] = True
    contract.write_json(directory / "manifest.json", manifest)
    (ROOT / "results/VALIDATION_LATEST").write_text(directory.name + "\n")
    return directory


def analyze(directory):
    manifest = contract.load_json(directory / "manifest.json")
    if not manifest["completed"]:
        raise ValueError("Validation collection is incomplete")
    protocol = manifest["protocol"]
    points = manifest["points"]
    data = {}
    for execution in manifest["executions"]:
        records = read_results(
            directory / execution["output"],
            directory / execution["config"],
            execution["impl"],
            1,
            "ber",
        )
        if any(
            r["n_batches"] != protocol["fixed_batches"] or r["status"] != "max_bits"
            for r in records
        ):
            raise ValueError("Retained validation budget differs")
        data[execution["scenario"], execution["impl"]] = {
            r["ebn0_db"]: r for r in records
        }
    theory = {
        point["ebn0_db"]: point
        for point in contract.load_json(ROOT / "contract/theory/main.json")["points"]
    }
    theory_family = 2 * len(points) * len(LANGUAGES)
    pair_family = 6 * len(points)
    theory_results, pairs = [], []
    for scenario, key in (
        ("awgn-perfect", "awgn_ber"),
        ("rayleigh-perfect", "rayleigh_perfect_csi_ber"),
    ):
        for language in LANGUAGES:
            for point in points:
                record = data[scenario, language][point]
                result = theory_check(
                    record,
                    theory[point][key],
                    protocol["theory_family_alpha"] / theory_family,
                )
                theory_results.append(
                    {
                        "scenario": scenario,
                        "impl": language,
                        "ebn0_db": point,
                        "n_errors": record["n_errors"],
                        **result,
                    }
                )
    for first, second in itertools.combinations(LANGUAGES, 2):
        for point in points:
            result = welch(
                data["rayleigh-estimated", first][point],
                data["rayleigh-estimated", second][point],
                protocol["pair_family_alpha"] / pair_family,
            )
            pairs.append({"first": first, "second": second, "ebn0_db": point, **result})
    failures = [r for r in (*theory_results, *pairs) if r["status"] == "incompatible"]
    insufficient = [
        r for r in (*theory_results, *pairs) if r["status"] == "evidence_insufficient"
    ]
    summary = {
        "protocol": protocol,
        "theory_family_tests": theory_family,
        "pair_family_tests": pair_family,
        "theory": theory_results,
        "pairs": pairs,
        "incompatible_count": len(failures),
        "insufficient_count": len(insufficient),
        "sparse_points_approved": False,
        "all_points_approved": not failures and not insufficient,
        "equivalence_claimed": False,
    }
    contract.write_json(directory / "validation.json", summary)
    destination = ROOT / "report" / directory.name
    destination.mkdir(parents=True, exist_ok=True)
    theory_rows = [
        {
            "cenário": "AWGN, CSI perfeito"
            if r["scenario"] == "awgn-perfect"
            else "Rayleigh, CSI perfeito",
            "linguagem": LABELS[r["impl"]],
            "EbN0_dB": r["ebn0_db"],
            "erros": r["n_errors"],
            "estado": STATUS[r["status"]],
            "BER": None if r["n_errors"] == 0 else r["mean"],
            "teoria": r["theory"],
            "IC_simultâneo_inferior": r["lower"],
            "IC_simultâneo_superior": r["upper"],
            "limite_superior_zero_erros_95": r["zero_symbol_upper95"],
        }
        for r in theory_results
    ]
    pair_rows = [
        {
            "primeira": LABELS[r["first"]],
            "segunda": LABELS[r["second"]],
            "EbN0_dB": r["ebn0_db"],
            "diferença_BER": r["difference"],
            "IC95_inferior": r["ci95_lower"],
            "IC95_superior": r["ci95_upper"],
            "IC_simultâneo_inferior": r["lower"],
            "IC_simultâneo_superior": r["upper"],
            "p_valor": r["p_value"],
            "graus_de_liberdade": r["df"],
            "estado": STATUS[r["status"]],
        }
        for r in pairs
    ]
    for name, rows in (("theory.csv", theory_rows), ("compatibility.csv", pair_rows)):
        with (destination / name).open("w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
    (destination / "README.md").write_text(f"""# Validação OFDM para lecture

Fonte: `{directory}`. Amostra independente: {protocol["fixed_batches"]} lotes por
ponto, {len(points)} pontos e quatro linguagens; semente {protocol["master_seed"]}.
Protocolo e configurações foram gravados antes de executar qualquer simulador.
Parada exclusivamente por orçamento: mínimo N, máximo N×172032 bits e alvo
N×172032+1 erros. Tempos desta coleta não são comparação de desempenho.

`theory.csv`: família de {theory_family} intervalos simultâneos de 99% por média
de lotes, incluindo os dois cenários teóricos e todas as linguagens/pontos.
Abaixo de 100 erros: **evidência insuficiente**, sem aprovação e sem aumentar N
após observar resultados. Pontos sem erros mostram limite por símbolo de 95%;
não mostram BER zero nem recebem aprovação automática.

`compatibility.csv`: {pair_family} comparações de Welch com correção de Bonferroni
(α da família = 0,01), diferença de BER, IC de 95%, IC simultâneo e p-valor.
Não rejeitar diferença não demonstra equivalência. Nenhuma margem foi definida.

Estados observados: {len(failures)} incompatíveis; {len(insufficient)} com evidência
insuficiente. Todos os pontos aprovados: {summary["all_points_approved"]}.
Resultado por ponto permanece explícito; cobertura estatística completa não é
alegada quando há pontos insuficientes. Aproximação t requer lotes independentes;
os erros dentro de um símbolo não são tratados como ensaios independentes.

Recalcular sobre as mesmas observações:
`uv run --project tools --locked python -m bench.validate --run {directory}`.
O relatório de desempenho permanece no diretório apontado por `report/LATEST`.
""")
    print(
        f"Validation: {len(failures)} incompatible, {len(insufficient)} insufficient; "
        "no sparse-point approval",
        flush=True,
    )
    print(f"Generated validation report: {destination}")
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path)
    args = parser.parse_args()
    return analyze(args.run.resolve() if args.run else collect())


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Validation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
