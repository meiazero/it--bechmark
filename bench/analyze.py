"""Regenerate Portuguese lecture tables and figures from retained raw runs."""

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy import stats

from bench.common import LANGUAGES, ROOT
from tools import contract

LABELS = {"cpp": "C++/IT++", "python": "Python/NumPy", "rust": "Rust", "julia": "Julia"}
COLORS = ("#000000", "#0072B2", "#D55E00", "#882255")
MARKERS = ("o", "s", "^", "D")
STAGE_LABELS = {
    "bits": "Bits",
    "qam_map": "16-QAM",
    "grid": "Grade",
    "ifft": "IFFT",
    "cp_add": "Adicionar CP",
    "channel_conv": "Convolução",
    "awgn": "Ruído AWGN",
    "cp_remove": "Remover CP",
    "fft": "FFT",
    "chan_est": "Estimação LS",
    "zf": "Equalização ZF",
    "demap_count": "Decisão/erros",
    "e2e": "Ponta a ponta",
}


def bootstrap(values, statistic=np.median):
    if len(values) < 2:
        return None, None
    rng = np.random.default_rng(20260930)
    values = np.asarray(values)
    samples = statistic(
        rng.choice(values, size=(10000, len(values)), replace=True), axis=1
    )
    return tuple(map(float, np.quantile(samples, [0.025, 0.975])))


def batch_interval(record, alpha=0.05):
    n, m = record["n_batches"], 172032
    if record["n_errors"] == 0:
        upper = -math.expm1(math.log(alpha) / record["n_symbols"])
        return 0.0, upper, "limite por símbolo; parada adaptativa sem cobertura nominal"
    mean = record["n_errors"] / (n * m)
    if n < 2:
        return None, None, "lotes insuficientes"
    variance = max(
        0.0, (record["sum_batch_errors_sq"] - record["n_errors"] ** 2 / n) / (n - 1)
    )
    radius = stats.t.ppf(1 - alpha / 2, n - 1) * math.sqrt(variance / n) / m
    return (
        max(0.0, mean - radius),
        min(1.0, mean + radius),
        "IC t por lote; parada adaptativa sem cobertura nominal",
    )


def save_figure(fig, destination, name):
    for ax in fig.axes:
        if not ax.has_data():
            ax.text(
                0.5,
                0.5,
                "Sem dados para esta suíte",
                transform=ax.transAxes,
                ha="center",
            )
    for suffix in ("png", "svg"):
        fig.savefig(destination / f"{name}.{suffix}", dpi=150, facecolor="white")
    plt.close(fig)


def analyze(directory):
    manifest = contract.load_json(directory / "manifest.json")
    env = contract.load_json(directory / "env.json")
    if not manifest["completed"]:
        raise ValueError("Analysis requires a completed run")
    destination = ROOT / "report" / directory.name
    destination.mkdir(parents=True, exist_ok=True)
    grouped = defaultdict(list)
    captures = {}
    for execution in manifest["executions"]:
        captures[execution["id"]] = contract.load_json(directory / execution["capture"])
        if execution["status"] == "complete":
            records = [
                contract.parse_json(line)
                for line in (directory / execution["output"]).read_text().splitlines()
            ]
            for record in records:
                grouped[
                    (
                        execution["suite"],
                        execution["core"],
                        execution["workers"],
                        execution["impl"],
                        record["ebn0_db"],
                    )
                ].append((execution, record))
    rows = []
    for (suite, core, workers, language, point), entries in grouped.items():
        values = [r["work_s"] for _, r in entries]
        median = float(np.median(values))
        lower, upper = bootstrap(values)
        bits = entries[0][1]["n_bits"]
        rows.append(
            {
                "suíte": {
                    "single": "serial",
                    "stages": "estágios",
                    "scaling": "escalabilidade",
                    "memory": "memória",
                    "ber": "BER",
                }[suite],
                "núcleo": "P" if core == "p-core" else "E",
                "trabalhadores": workers,
                "linguagem": LABELS[language],
                "EbN0_dB": point,
                "processos": len(values),
                "mediana_trabalho_s": median,
                "mínimo_s": min(values),
                "IQR_s": float(np.quantile(values, 0.75) - np.quantile(values, 0.25)),
                "IC95_inferior_s": lower,
                "IC95_superior_s": upper,
                "vazão_Mbit_s": bits / median / 1e6,
                "mediana_preparo_s": float(
                    np.median([r["setup_s"] for _, r in entries])
                ),
                "mediana_aquecimento_s": float(
                    np.median([r["warmup_s"] for _, r in entries])
                ),
                "mediana_processo_s": float(
                    np.median([captures[e["id"]]["process_s"] for e, _ in entries])
                ),
            }
        )
    with (destination / "summary.csv").open("w", newline="") as file:
        columns = (
            "suíte",
            "núcleo",
            "trabalhadores",
            "linguagem",
            "EbN0_dB",
            "processos",
            "mediana_trabalho_s",
            "mínimo_s",
            "IQR_s",
            "IC95_inferior_s",
            "IC95_superior_s",
            "vazão_Mbit_s",
            "mediana_preparo_s",
            "mediana_aquecimento_s",
            "mediana_processo_s",
        )
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    smoke = manifest["smoke"]
    prefix = "SMOKE — execução demonstrativa\n" if smoke else ""
    with plt.rc_context(
        {
            "font.size": 13,
            "axes.titlesize": 16,
            "axes.labelsize": 14,
            "svg.fonttype": "none",
        }
    ):
        fig, axes = plt.subplots(
            1, 2, figsize=(13, 5), layout="constrained", sharey=True
        )
        for ax, core, title in zip(
            axes,
            ("p-core", "e-core"),
            ("Núcleo P: CPU 2", "Núcleo E: CPU 4"),
            strict=True,
        ):
            for i, language in enumerate(LANGUAGES):
                entries = grouped.get(("single", core, 1, language, 10), [])
                if not entries:
                    continue
                rates = [r["n_bits"] / r["work_s"] / 1e6 for _, r in entries]
                ax.scatter(
                    [i] * len(rates), rates, color=COLORS[i], marker=MARKERS[i], s=65
                )
                median = float(np.median(rates))
                lower, upper = bootstrap(rates)
                if lower is not None:
                    ax.errorbar(
                        i,
                        median,
                        yerr=[[median - lower], [upper - median]],
                        color=COLORS[i],
                        capsize=4,
                    )
            ax.set(
                xticks=range(4),
                xticklabels=[LABELS[x] for x in LANGUAGES],
                ylabel="Dados úteis (Mbit/s)",
                title=title,
                ylim=(0, None),
            )
            ax.tick_params(axis="x", rotation=20)
        fig.suptitle(prefix + "Vazão — trabalho separado de preparo e aquecimento")
        save_figure(fig, destination, "throughput")

        fig, ax = plt.subplots(figsize=(13, 6), layout="constrained")
        stage_rows = []
        for i, language in enumerate(LANGUAGES):
            entries = grouped.get(("stages", "p-core", 1, language, 10), [])
            if not entries:
                continue
            durations = {
                name: float(
                    np.median([r["stage_ns_per_symbol"][name] for _, r in entries])
                )
                for name in STAGE_LABELS
            }
            ax.plot(
                range(len(STAGE_LABELS)),
                [durations[x] / 1e6 for x in STAGE_LABELS],
                label=LABELS[language],
                color=COLORS[i],
                marker=MARKERS[i],
            )
            isolated = sum(value for name, value in durations.items() if name != "e2e")
            stage_rows.append(
                {
                    "linguagem": LABELS[language],
                    "soma_estágios_ns": isolated,
                    "ponta_a_ponta_ns": durations["e2e"],
                    "resíduo_ns": durations["e2e"] - isolated,
                    **{
                        f"{STAGE_LABELS[name]}_ns": value
                        for name, value in durations.items()
                    },
                }
            )
        ax.set(
            xticks=range(len(STAGE_LABELS)),
            xticklabels=list(STAGE_LABELS.values()),
            ylabel="Tempo (ms por símbolo OFDM)",
            title=prefix + "Estágios isolados e cadeia completa",
            ylim=(0, None),
        )
        ax.tick_params(axis="x", rotation=40)
        if ax.has_data():
            ax.legend()
        save_figure(fig, destination, "stages")
        with (destination / "stages.csv").open("w", newline="") as file:
            columns = [
                "linguagem",
                "soma_estágios_ns",
                "ponta_a_ponta_ns",
                "resíduo_ns",
                *(f"{label}_ns" for label in STAGE_LABELS.values()),
            ]
            writer = csv.DictWriter(file, fieldnames=columns)
            writer.writeheader()
            writer.writerows(stage_rows)

        fig, axes = plt.subplots(1, 2, figsize=(13, 5), layout="constrained")
        scaling_rows = []
        for i, language in enumerate(LANGUAGES):
            serial = grouped.get(("scaling", "e-core", 1, language, 10), [])
            if not serial:
                continue
            t1 = float(np.median([r["work_s"] for _, r in serial]))
            points = []
            for workers in (1, 2, 4, 8):
                entries = grouped.get(("scaling", "e-core", workers, language, 10), [])
                if not entries:
                    continue
                tp = float(np.median([r["work_s"] for _, r in entries]))
                points.append((workers, t1 / tp, t1 / (workers * tp)))
                scaling_rows.append(
                    {
                        "linguagem": LABELS[language],
                        "trabalhadores": workers,
                        "aceleração": t1 / tp,
                        "eficiência": t1 / (workers * tp),
                    }
                )
            for ax, index in zip(axes, (1, 2), strict=True):
                ax.plot(
                    [p[0] for p in points],
                    [p[index] for p in points],
                    color=COLORS[i],
                    marker=MARKERS[i],
                    label=LABELS[language],
                )
        for ax, title, ylabel in zip(
            axes,
            ("Aceleração T1/Tp", "Eficiência T1/(p·Tp)"),
            ("Aceleração", "Eficiência"),
            strict=True,
        ):
            ax.set(
                xlabel="Trabalhadores em núcleos E",
                ylabel=ylabel,
                title=title,
                xticks=[1, 2, 4, 8],
                ylim=(0, None),
            )
            if ax.has_data():
                ax.legend()
        fig.suptitle(prefix + "Escalabilidade — referência na CPU 4")
        save_figure(fig, destination, "scaling")
        with (destination / "scaling.csv").open("w", newline="") as file:
            columns = ["linguagem", "trabalhadores", "aceleração", "eficiência"]
            writer = csv.DictWriter(file, fieldnames=columns)
            writer.writeheader()
            writer.writerows(scaling_rows)

        fig, axes = plt.subplots(1, 2, figsize=(13, 5), layout="constrained")
        memory_rows = []
        for execution in manifest["executions"]:
            if execution["suite"] != "memory":
                continue
            capture = captures[execution["id"]]
            samples = capture["rss_samples"]
            language = execution["impl"]
            i = LANGUAGES.index(language)
            ax = axes[0 if execution["workers"] == 1 else 1]
            ax.plot(
                [s["elapsed_s"] for s in samples],
                [s["rss_bytes"] / 2**20 for s in samples],
                color=COLORS[i],
                label=LABELS[language],
                linestyle=("-", "--", "-.", ":")[i],
            )
            tail = [s for s in samples if s["elapsed_s"] >= 0.2 * capture["process_s"]]
            slope = (
                stats.linregress(
                    [s["elapsed_s"] for s in tail],
                    [s["rss_bytes"] / 2**20 for s in tail],
                ).slope
                * 60
                if len(tail) >= 3
                else None
            )
            memory_rows.append(
                {
                    "linguagem": LABELS[language],
                    "trabalhadores": execution["workers"],
                    "estado": "limite de tempo"
                    if execution["status"] == "timeout"
                    else "concluído",
                    "pico_grupo_de_controle_MiB": capture["memory_peak_bytes"] / 2**20,
                    "pico_memória_residente_MiB": capture["rss_peak_bytes"] / 2**20,
                    "inclinação_memória_residente_MiB_min": slope,
                    "crescimento_sinalizado": None
                    if smoke or slope is None
                    else slope > 1,
                }
            )
        for ax, workers in zip(axes, (1, 8), strict=True):
            ax.set(
                xlabel="Tempo desde início do processo (s)",
                ylabel="Memória residente da árvore (MiB)",
                title=f"{workers} trabalhador(es), núcleos E",
                ylim=(0, None),
            )
            if ax.lines:
                if ax.has_data():
                    ax.legend()
        fig.suptitle(prefix + "Memória residente — pico do grupo de controle em tabela")
        save_figure(fig, destination, "memory")
        with (destination / "memory.csv").open("w", newline="") as file:
            columns = [
                "linguagem",
                "trabalhadores",
                "estado",
                "pico_grupo_de_controle_MiB",
                "pico_memória_residente_MiB",
                "inclinação_memória_residente_MiB_min",
                "crescimento_sinalizado",
            ]
            writer = csv.DictWriter(file, fieldnames=columns)
            writer.writeheader()
            writer.writerows(memory_rows)

        fig, ax = plt.subplots(figsize=(10, 6), layout="constrained")
        ber_rows = []
        for i, language in enumerate(LANGUAGES):
            entries = sorted(
                (key[4], record)
                for key, pairs in grouped.items()
                if key[0] == "ber" and key[3] == language
                for _, record in pairs
            )
            if not entries:
                continue
            for point, record in entries:
                lower, upper, method = batch_interval(record)
                rate = record["n_errors"] / record["n_bits"]
                ber_rows.append(
                    {
                        "linguagem": LABELS[language],
                        "EbN0_dB": point,
                        "BER": None if rate == 0 else rate,
                        "inferior": lower,
                        "superior": upper,
                        "método": method,
                        "lotes": record["n_batches"],
                    }
                )
                if rate == 0:
                    ax.scatter(point, upper, marker="v", color=COLORS[i])
                elif lower is not None:
                    ax.errorbar(
                        point,
                        rate,
                        yerr=[[rate - lower], [upper - rate]],
                        color=COLORS[i],
                        marker=MARKERS[i],
                        capsize=3,
                    )
            ax.plot(
                [point for point, _ in entries],
                [
                    record["n_errors"] / record["n_bits"]
                    if record["n_errors"]
                    else np.nan
                    for _, record in entries
                ],
                color=COLORS[i],
                marker=MARKERS[i],
                label=LABELS[language],
            )
        ax.set(
            xlabel="Eb/N0 (dB)",
            ylabel="BER (escala logarítmica)",
            yscale="log",
            title=prefix + "Rayleigh com CSI estimado — parada adaptativa",
        )
        if ax.has_data():
            ax.legend()
        save_figure(fig, destination, "ber")
        with (destination / "ber.csv").open("w", newline="") as file:
            columns = [
                "linguagem",
                "EbN0_dB",
                "BER",
                "inferior",
                "superior",
                "método",
                "lotes",
            ]
            writer = csv.DictWriter(file, fieldnames=columns)
            writer.writeheader()
            writer.writerows(ber_rows)
    evidence_label = (
        "**Carga smoke: demonstração funcional. Uma repetição, sem cooldown, "
        "sem calibração. Estes valores não sustentam ranking, aceleração publicada "
        "ou estabilidade de memória em dez minutos.**"
        if smoke
        else "**Carga congelada: protocolo registrado em env.json.**"
    )
    description = f"""# OFDM: resultados para lecture

Execução `{directory.name}`. Fonte bruta: `{directory}`.

{evidence_label}

| Campo | Estado observado |
|---|---|
| Linguagens | C++/IT++, Python/NumPy, Rust, Julia |
| Turbo (`no_turbo`) | {env["no_turbo"]} |
| Repetições por configuração | {manifest["repetitions"]} |
| Cooldown | {manifest["cooldown_s"]} s |
| Git | `{env["git_sha"]}`; checkout sujo: {env["dirty"]} |

## Ler os artefatos

1. `summary.csv`: tempos por fase; vazão usa dados úteis/trabalho.
2. `stages.csv`: medianas e resíduo e2e menos soma; não é decomposição exata.
3. `scaling.csv`: referência serial no núcleo E, CPU 4.
4. `memory.csv`: pico do grupo, memória residente e inclinação; inclui observador.
5. `ber.csv`: IC t por lote; parada adaptativa impede cobertura nominal de 95%.

![Vazão por linguagem e classe de núcleo](throughput.png)
![Tempos por estágio em ms por símbolo OFDM](stages.png)
![Aceleração e eficiência em E-cores](scaling.png)
![Trajetórias de memória residente com um e oito workers](memory.png)
![BER por Eb/N0, com intervalos descritivos por lote](ber.png)

## Método e limites

Tempos de processos novos permanecem em `raw/`; a ordem é aleatorizada com semente
{env["order_seed"]}. A mediana é o estimador de trabalho; IC bootstrap de 95% usa
10.000 reamostras e semente fixa quando existem ao menos dois processos. Smoke
com um processo não recebe IC bootstrap. Zero erros recebe limite superior por
símbolo, representado por triângulo para baixo; não recebe BER zero em escala log.
Intervalos que chegam a zero ultrapassam o domínio do eixo logarítmico.

As saídas e comandos preservam os hashes dos bytes exatos de configuração.
Limite de tempo conserva amostras e registra estado; não inventa contagens
para um processo interrompido. A carga curta inclui inicialização/compilação JIT;
não valida tendência de memória residente em carga longa. Deltas após aquecimento
ainda são estimativas no M6; exigem marcador de fase antes da medição publicada.

A diferença entre RNGs, backends FFT, versão FFTW do sistema/Julia, flags genéricas
da IT++ e CPU híbrida limita atribuição causal à linguagem. As quatro versões
foram escritas pelo mesmo agente de IA; ergonomia não mede programadores humanos.
Compatibilidade estatística com teoria e entre linguagens pertence ao M7;
otimização/calibração ao M8; medições completas ao M9. A calibração, CV, conferência
com turbo ligado, IC de razões e ergonomia final serão verificados na Fase 2.

Regenerar: `make analyze RUN={directory}`.
"""
    (destination / "README.md").write_text(description)
    contract.write_json(
        destination / "provenance.json",
        {
            "source": str(directory),
            "run_id": directory.name,
            "bootstrap_seed": 20260930,
            "bootstrap_resamples": 10000,
            "smoke": smoke,
            "figures": ["throughput", "stages", "scaling", "memory", "ber"],
            "size_inches": {
                "throughput": [13, 5],
                "stages": [13, 6],
                "scaling": [13, 5],
                "memory": [13, 5],
                "ber": [10, 6],
            },
            "dpi": 150,
            "formats": ["png", "svg"],
            "missing_intervals": "No bootstrap interval for one process",
        },
    )
    if "projection_source" not in manifest:
        (ROOT / "report/LATEST").write_text(directory.name + "\n")
    print(f"Generated lecture report: {destination}")
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path)
    args = parser.parse_args()
    directory = (
        args.run or ROOT / "results" / (ROOT / "results/LATEST").read_text().strip()
    )
    analyze(directory.resolve())


if __name__ == "__main__":
    main()
