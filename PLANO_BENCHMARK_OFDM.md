# Plano: benchmark comparativo de IT++ e Python, Julia e Rust

## Objetivo

Construir um simulador OFDM ponto a ponto reproduzível para comparar a implementação de referência em C++/IT++ com implementações idiomáticas em Python, Julia e Rust. Avaliar separadamente desempenho, correção, memória, escalabilidade e ergonomia; não reduzir o resultado a um único ranking de velocidade.

Princípio de justiça: **mesmo algoritmo, mesma carga, mesmo contrato numérico, mesmas regras de otimização, mesmo ambiente medido**. Tudo o que difere entre linguagens (RNG, backend FFT, runtime) é registrado e isolado por medição de estágios, nunca escondido.

## Regras para o agente implementador (Codex)

1. O diretório `contract/` é a fonte da verdade. Não altere valores do contrato; se algo for impossível de cumprir, pare e reporte com evidência.
2. Um marco (seção "Marcos") por PR. Um marco só termina quando o comando de aceite dele passa.
3. Sem stubs, TODOs ou testes desativados para "passar". Teste que falha é reportado com a saída.
4. Não introduza dependências fora das listadas; qualquer adição exige justificativa no PR.
5. Registre cada desvio do contrato, bug encontrado e otimização aplicada em `impl/<lang>/NOTES.md`.

## Escopo

- Simulação complexa em banda-base, sem codificação de canal, curva BER × `Eb/N0`.
- Caminho completo: bits → 16-QAM → grade de subportadoras + pilotos → IFFT → CP → canal Rayleigh multipercurso (convolução no tempo) + AWGN → remoção do CP → FFT → estimação LS nos pilotos + interpolação linear → equalização ZF → decisão abrupta → contagem de erros.
- Execução single-thread, escalabilidade multi-thread/multiprocesso, medições por estágio e memória.

Fora do escopo: FEC, sincronização, SDR/RF, GPU, precisão `Float32`, comparação de compiladores, tuning de backend FFT como objetivo próprio.
Extensões opcionais, sempre em trilha separada e rotulada: 64-QAM, Numba/JAX, Python free-threaded, energia via RAPL.

**MMSE removido do escopo:** em OFDM SISO com decisão abrupta por subportadora, o MMSE não enviesado coincide com o ZF e o MMSE enviesado piora 16-QAM (encolhe a amplitude antes do fatiador). Não acrescenta informação ao benchmark.

## Ambiente e versões

### Máquina de medição

Coletado em 2026-09-30 via `lscpu -e`, `/sys/devices/cpu_{core,atom}/cpus`, `free -h`, `lsb_release`:

| Item | Valor |
|---|---|
| CPU | Intel Core 7 150U, híbrida |
| P-cores | CPUs lógicas 0–3 (2 núcleos físicos com SMT), máx. 5400 MHz |
| E-cores | CPUs lógicas 4–11 (8 núcleos físicos, sem SMT), máx. 4000 MHz |
| RAM | 15 GiB |
| SO | Pop!_OS 24.04 LTS, kernel 7.1 |
| Governor | `performance`; turbo ligado (`intel_pstate/no_turbo = 0`) |
| cgroup v2 | `memory.peak` disponível via `systemd-run --user --scope` (testado) |

### Versões fixadas

Ferramentas via `mise.toml` (valores de `mise latest` em 2026-09-30):

```toml
[tools]
python = "3.14.7"
uv = "0.12.20"
julia = "1.13.1"
rust = "1.98.1"
cmake = "4.4.3"
ninja = "1.13.2"
tokei = "15.0.0"

[env]
OMP_NUM_THREADS = "1"
OPENBLAS_NUM_THREADS = "1"
MKL_NUM_THREADS = "1"
PYTHONHASHSEED = "0"
```

Bibliotecas por lockfile commitado:

- Python: `uv.lock` em `impl/python` (NumPy; PyPI mostra 2.5.3 com suporte a 3.14) e `uv.lock` separado em `tools/` (SciPy, psutil, matplotlib — nunca importados pela implementação Python).
- Julia: `Project.toml` + `Manifest.toml` (FFTW.jl).
- Rust: `Cargo.lock` (`rustfft`, `num-complex`, `rand`, `rand_distr`, `rayon`, `serde`, `serde_json`).

Sistema (mise não fixa bibliotecas C++; versões de `apt-cache policy` em 2026-09-30):

- `g++` 13.3.0 (sistema), `libitpp-dev=4.3.1-10build1`, `libfftw3-dev=3.3.10-1ubuntu3`.
- `tools/check_system.py` aborta se as versões instaladas divergirem das fixadas.

`mise.toml` também define as tarefas: `doctor`, `golden`, `test`, `ber`, `bench`, `analyze`. Todo comando do plano roda como `mise run <tarefa>`.

## Contrato numérico (congelado)

Arquivos: `contract/profile_main.json`, `contract/config.schema.json`, `contract/result.schema.json`, `contract/golden/*.json`, `contract/invalid_configs/*.json`.

### Grade OFDM

| Parâmetro | Valor |
|---|---:|
| `N_fft` | 256 |
| `N_cp` | 32 (últimas 32 amostras prefixadas; símbolo com 288 amostras) |
| Bins ativos | `k ∈ {−96..−1} ∪ {1..96}` → 192 |
| DC | `k = 0` nulo |
| Guardas | `k ∈ {−128..−97}` (32) e `{97..127}` (31) |
| Pilotos | `k ∈ {±8, ±16, …, ±96}` → 24 |
| Dados | 168 bins restantes, em ordem crescente de `k` |
| Bits por símbolo OFDM | 168 × 4 = 672 |
| Índice FFT | `idx = k mod 256` |

Pilotos nas bordas (±96) eliminam extrapolação. Entre −8 e +8 a interpolação atravessa o DC com distância de 16 bins.

### Modulação 16-QAM

- Bits `(b0 b1 b2 b3)`, MSB primeiro; `(b0,b1)` → I e `(b2,b3)` → Q.
- Níveis Gray por eixo: `00 → −3`, `01 → −1`, `11 → +1`, `10 → +3`; símbolo `(I + jQ)/√10` (energia média 1).
- Decisão por eixo, em unidades de `√10·v`: `−3` se `< −2`; `−1` se `[−2, 0)`; `+1` se `[0, 2)`; `+3` se `≥ 2`. Empate vai para o nível superior.
- C++ pode usar `itpp::QAM` somente se passar nos vetores dourados (inclusive empates); caso contrário, tabela, igual às outras linguagens.

### Pilotos

- BPSK real `±1`, energia 1 (igual à energia média dos dados).
- Sequência fixa de 24 valores listada em `contract/profile_main.json`.

### FFT

DFT unitária em ambos os sentidos:

- `x[n] = (1/√N) Σ_k X[k] e^{+j2πkn/N}`
- `Y[k] = (1/√N) Σ_n y[n] e^{−j2πkn/N}`

Cada implementação ajusta a escala da sua biblioteca (NumPy `norm="ortho"`; FFTW e rustfft não normalizam; IT++ 4.3.1: `fft` sem escala e `ifft` com `1/N`, verificado em 2026-09-30 → usar `fft·(1/√N)` e `ifft·√N`). FFT via biblioteca; implementação manual de FFT é proibida.

### Canal

- 8 taps `h_l ~ CN(0, p_l)`, `l = 0..7`, PDP exponencial `p_l = e^{−l/2} / Σ_m e^{−m/2}` (`Σ p_l = 1`).
- Os valores de `p_l` ficam gravados no perfil com 17 dígitos; nenhuma implementação os recalcula.
- Block fading: nova realização independente por símbolo OFDM.
- Aplicação obrigatória no tempo, por convolução direta de 8 taps: `y = (h * x_cp)[0:288]`; a cauda de 7 amostras é descartada. Convolução via FFT é proibida (mudaria a carga).
- Resposta em frequência equivalente: `H[k] = Σ_l h_l e^{−j2πkl/N}`.
- Perfil `awgn` (validação): `h = [1]`.

### Ruído e `Eb/N0`

- Energia nominal por símbolo OFDM: `E_sym = 192 · (288/256) = 216` (constante do perfil, nunca medida).
- `N0 = E_sym / (672 · 10^(EbN0_dB/10))`.
- Ruído complexo `CN(0, N0)` em todas as 288 amostras: real e imaginário `N(0, N0/2)` cada.
- Como `Σ p_l = 1`, o `Eb/N0` é o mesmo na transmissão e, em média, na recepção.
- Consequência documentada: `Es/N0` por subportadora de dados `= γb · 672/216`. Portanto a curva teórica 16-QAM sem overhead fica deslocada em `10·log10(672/(4·216)) = 10·log10(168/216) ≈ −1,09 dB` (CP: 0,51 dB; pilotos: 0,58 dB). Os testes contra teoria usam essa relação.

### Estimação e equalização

- LS: `Ĥ[k_p] = Y[k_p] / P[k_p]`.
- Interpolação linear em `k` (coordenada real do bin, não índice ativo).
- ZF: `X̂ = Y / Ĥ`. Se `Ĥ == 0` exatamente: `X̂ = 0`, incrementa `zf_zero_count`; nunca NaN.
- Modo diagnóstico `csi = "perfect"`: usa `H[k]` verdadeiro. Não entra nas medições de desempenho.

### RNG e lotes

- Unidade de trabalho: lote de `B = 256` símbolos OFDM (172.032 bits de payload), fixo para todas as linguagens.
- Semente do lote, SplitMix64 padrão implementado igual nas quatro linguagens e coberto por vetor dourado:
  `s = sm64(master_seed); s = sm64(s ^ point_index); s = sm64(s ^ batch_index)`.
- Gerador idiomático semeado com `s`:

| Linguagem | Gerador |
|---|---|
| Python | `numpy.random.Generator(PCG64(s))` |
| Julia | `Xoshiro(s)` |
| Rust | `rand::rngs::SmallRng::seed_from_u64(s)` + `rand_distr::StandardNormal` |
| C++ | RNG da IT++ se M0 provar estado independente por thread; senão `std::mt19937_64(s)`, registrado em `NOTES.md` |

- Sequências não precisam coincidir entre linguagens. A validação cruzada é estatística.
- Resultado de cada lote depende só de `(master_seed, point_index, batch_index)` → independente do número de workers.

### Critério de parada (modo BER)

- `K` = menor índice de lote tal que, somando os lotes `0..K` em ordem: `erros ≥ target_errors` e `lotes ≥ min_batches`; ou `bits ≥ max_bits`.
- Workers podem processar além de `K`; lotes excedentes são descartados.
- Resultado idêntico para qualquer número de workers (testado).
- Padrões: `target_errors = 1000`, `min_batches = 32`, `max_bits = 1e9`, `EbN0_dB = 0:2:30`. Todos configuráveis.

### Validação de configuração

- Rejeitar: dimensões incompatíveis, `N_cp < n_taps − 1`, `M ≠ 16`, valores não finitos, `workers < 1`, `B < 1`, `max_bits < min_batches · B · 672`, semente fora de `u64`.
- Toda implementação rejeita todos os arquivos de `contract/invalid_configs/`: código de saída 2, mensagem em stderr, nenhuma saída de resultado.
- Contadores em `u64`.

### CLI comum

```
<impl> --config <arquivo.json> --mode {golden,ber,perf,stages} --workers <p> --out <arquivo.jsonl>
```

Códigos de saída: 0 sucesso, 1 erro de execução, 2 configuração inválida.

### Saída

JSON Lines validado por `contract/result.schema.json`, um registro por ponto `Eb/N0`:

- `schema_version`, `impl`, `git_sha`, `mode`, `profile_id`, `config_sha256` (JSON canônico), `master_seed`, `workers`, `ebn0_db`.
- `n_batches`, `n_symbols`, `n_bits`, `n_errors`, `sum_batch_errors_sq`, `n_symbols_with_errors`, `zf_zero_count`, `status`.
- `setup_s`, `warmup_s`, `work_s`; no modo `stages`, tempo por estágio.

Metadados de ambiente ficam em arquivo separado (seção "Harness").

## Regras de implementação idiomática

Permitido em todas: pré-alocação de buffers por worker, operações in-place, plano FFT criado uma vez fora do laço, processamento do lote como matriz (layout de memória livre por linguagem).

| Linguagem | Permitido | Proibido na trilha principal |
|---|---|---|
| C++ | tipos/funções IT++, `std::thread`, `-O3 -march=native` | intrínsecos SIMD, asm, `-ffast-math` |
| Python | NumPy vetorizado sobre o lote, `out=` onde natural, `concurrent.futures.ProcessPoolExecutor` | Numba, Cython, JAX, pyFFTW, SciPy na implementação |
| Julia | estabilidade de tipos, `@inbounds`, `@simd`, `Threads.@spawn` | `@fastmath`, `--check-bounds=no` global |
| Rust | código safe, iteradores, `rayon` | `unsafe`, SIMD explícito, fast-math |

Build:

- C++: CMake Release, `-O3 -march=native`, IT++ via `pkg-config`. A IT++ do apt vem compilada com flags genéricas da distro; registrar como ameaça à validade.
- Rust: `opt-level = 3`, `lto = "fat"`, `codegen-units = 1`, `panic = "abort"`, `-C target-cpu=native` em `.cargo/config.toml`.
- Julia: `julia -O3 --startup-file=no --threads=<p>,0`; `FFTW.set_num_threads(1)`, `BLAS.set_num_threads(1)`.
- Python: CPython padrão; start method do multiprocessing fixado explicitamente em `forkserver`.
- FFTW: mesma flag de planejamento em C++ e Julia; M0 descobre qual a IT++ usa e a Julia copia.

**Orçamento de otimização igual:** depois de passar na correção, cada implementação recebe exatamente uma rodada guiada por profiler (`perf` para C++/Rust, `Profile` para Julia, `py-spy` para Python), com mudanças registradas em `NOTES.md`.

## Harness de benchmark

Orquestrador em Python (`bench/`, ambiente de `tools/`), fixado na CPU 0.

### Modos de medição

- **`perf` (primário):** carga fixa em `EbN0 = 10 dB`, `n_batches` calibrado no M0 para que C++ single-thread leve ≥ 5 s, depois congelado. Sem timers internos além de `t0`/`t1` ao redor do trabalho. Throughput = `n_batches · 256 · 672 / work_s`.
- **`stages`:** cada estágio isolado sobre entradas pré-geradas de um lote, R repetições, mediana em ns por símbolo OFDM. Estágios: `bits`, `qam_map`, `grid`, `ifft`, `cp_add`, `channel_conv`, `awgn`, `cp_remove`, `fft`, `chan_est`, `zf`, `demap_count`. Reportar a soma dos estágios contra o `e2e`; a diferença é glue/alocação.
- **`ber`:** curva de qualidade com critério de parada. Não é medição de desempenho.

### Fases do processo

Cada execução separa `setup` (config, planos, pool/threads, buffers), `warmup` (4 lotes com semente distinta, não contados; na Julia inclui compilação JIT) e `work`. O tempo total do processo é medido externamente. Sem I/O dentro de `work`; saída escrita após `t1`.

### Posicionamento em CPUs (CPU híbrida)

- Single-thread primário: CPU 2 (P-core), com a irmã SMT (CPU 3) ociosa.
- Single-thread de referência para escalabilidade: CPU 4 (E-core).
- Escalabilidade: somente E-cores homogêneos, `taskset -c 4..(4+p−1)`, `p ∈ {1, 2, 4, 8}`. Eficiência `T1/(p·Tp)` com `T1` em E-core.
- Execução "todas as 12 CPUs": informativa, fora do cálculo de eficiência.
- Escalonamento dinâmico igual para todas: um lote por tarefa, workers retiram índices de uma fila/contador (`imap_unordered(chunksize=1)`, `Threads.@spawn`, `rayon`, `std::atomic`). Agregação por soma de inteiros.

### Repetições e controle de ruído

- 10 processos novos por configuração. Em cada rodada, as linguagens rodam em permutação aleatória (semente registrada).
- Cooldown de 20 s entre execuções; temperatura (`/sys/class/thermal`) registrada antes e depois.
- Abortar se o notebook estiver na bateria (`/sys/class/power_supply/*/online`).
- Rodada primária com turbo desligado (`no_turbo = 1`) para estabilidade; uma rodada de conferência com turbo ligado. Os dois estados ficam registrados.
- Configuração com CV > 5% é marcada como ruidosa e repetida.

### Memória

- Primária: `memory.peak` do cgroup via `systemd-run --user --scope`. Inclui filhos e page cache.
- Secundária: soma de RSS da árvore de processos amostrada a cada 50 ms (psutil). Reporta pico e delta pós-warmup.
- Carga longa: 10 min por implementação com `p = 1` e `p = 8` E-cores, amostra a cada 1 s. Sinaliza crescimento se a inclinação do RSS nos últimos 80% passar de 1 MiB/min. Timeout mata o processo e registra `status = "timeout"`.

### Metadados (`results/<run_id>/env.json`)

- CPU, mapa de núcleos, governor, `no_turbo`, energia, kernel, distro.
- `mise ls --current --json`, SHA-256 dos lockfiles, `dpkg-query -W g++ libitpp-dev libfftw3-dev`, flags de compilação, variáveis de threads.
- `git_sha` e flag de working tree suja, semente da ordem de execução, data.

Dados brutos nunca são descartados; a agregação lê de `results/<run_id>/raw/`.

## Análise estatística

- **Desempenho:** mediana dos 10 `work_s` por configuração, IC 95% bootstrap (10.000 reamostras, semente fixa). Speedup em relação ao C++ com IC bootstrap da razão das medianas. Reportar também min e IQR.
- **BER:** lotes são i.i.d. (canal independente por símbolo), mas os erros dentro de um símbolo são correlacionados. IC 95% pela média de lotes (`t` com `n_batches − 1` g.l.), calculado de `n_errors` e `sum_batch_errors_sq`. Nunca usar IC binomial por bit.
- **Zero erros:** reportar `BER < 1 − 0,05^(1/n_symbols)` (limite de 95% sobre a probabilidade de um símbolo ter algum erro, que limita a BER). Nunca BER = 0.
- **Equivalência entre linguagens:** para cada ponto e cada par de linguagens, teste z de Welch sobre as médias de lotes, α = 0,01 com Bonferroni (6 pares × número de pontos).

## Validação

### Vetores dourados

`tools/golden/` usa **só a stdlib do Python** (`math`, `cmath`, DFT ingênua O(N²)) e não importa nenhuma implementação competidora. Gera entradas e saídas esperadas para:

1. Mapeamento dos 16 símbolos e demapeamento incluindo empates nos limiares.
2. Montagem da grade para um vetor fixo de 672 bits; extração de dados e pilotos.
3. IFFT/FFT unitárias de vetores fixos; CP add/remove.
4. Convolução com taps fixos; LS + interpolação para `Y` fixo; ZF incluindo `Ĥ = 0`.
5. `N0` para uma lista de `Eb/N0`; cadeia SplitMix64; ponta a ponta sem ruído com taps fixos → bits idênticos.

Cada implementação expõe `--mode golden`, que lê as entradas e grava saídas; um único verificador, `tools/check_golden.py`, compara as quatro com tolerância absoluta de `1e-12` (FFT: `1e-11`).

### Curvas teóricas

`tools/theory.py` (SciPy) calcula numericamente:

- AWGN: BER exata do 16-QAM Gray pelas regiões de decisão, em `Es/N0 = γb · 672/216`.
- Rayleigh com CSI perfeito: média da BER AWGN sobre `|H|² ~ Exp(1)` por integração numérica.

### Testes estatísticos

- AWGN (`h = [1]`, CSI perfeito): a teoria cai no IC 99% simulado em todo ponto com ≥ 100 erros (Bonferroni).
- Rayleigh com CSI perfeito: idem contra a teoria de Rayleigh.
- Rayleigh com CSI estimado (perfil principal): equivalência entre as quatro linguagens pelo teste da seção "Análise".
- Mesma config e semente rodada duas vezes → contagens idênticas.
- `workers = 1` e `workers = 4` → contagens idênticas.
- Carga longa sem crescimento de memória, deadlock ou worker preso.

Testes nativos por linguagem cobrem apenas o que o golden não cobre: validação de configuração e códigos de saída.

## Ergonomia

- LOC de produção e de teste via `tokei`.
- Dependências diretas e transitivas (lockfiles).
- Tempo de build limpo com cache vazio; número de comandos para build e execução.
- Diário de defeitos em `NOTES.md`: onde cada bug foi pego (compilador/tipos, golden, teste estatístico, execução).
- Ameaça à validade, obrigatória no relatório: as quatro versões foram escritas pelo mesmo agente de IA, então essas métricas medem a ergonomia para esse agente, não para um programador humano.

## Estrutura do repositório

```
mise.toml
contract/        perfis, schemas, golden/, invalid_configs/, theory/
tools/           golden (stdlib), theory, check_golden, check_system (uv próprio)
impl/cpp/        CMakeLists.txt, src/, tests/, NOTES.md
impl/python/     pyproject.toml, uv.lock, src/, tests/, NOTES.md
impl/julia/      Project.toml, Manifest.toml, src/, test/, NOTES.md
impl/rust/       Cargo.toml, Cargo.lock, src/, tests/, NOTES.md
bench/           orquestrador, captura de ambiente, análise, figuras
results/<run_id>/raw/, env.json
report/
```

## Marcos (um PR cada)

| Marco | Entrega | Aceite |
|---|---|---|
| M0 Ambiente | `mise.toml`, `check_system.py`, `git init`. Descobrir: flag FFTW da IT++, segurança do RNG IT++ por thread (teste com 2 threads e mesma semente). | `mise run doctor` passa; achados em `impl/cpp/NOTES.md` |
| M1 Contrato | perfil, schemas, `invalid_configs`, gerador golden, `theory.py`, `check_golden.py` | `mise run golden` gera arquivos; autoteste do verificador passa |
| M2 C++/IT++ | serial + paralelo, modos `golden`/`ber`/`perf`/`stages` | golden, configs inválidas, AWGN e Rayleigh-CSI contra teoria |
| M3–M5 Python, Rust, Julia | mesmos modos | tudo do M2 + equivalência estatística com C++ |
| M6 Harness single-thread | orquestrador, env, pinagem, repetições, stages, tabelas | `mise run bench -- --suite single` gera `results/` completo |
| M7 Escalabilidade e memória | E-cores 1/2/4/8, cgroup, psutil, carga longa | `mise run bench -- --suite scaling,memory` |
| M8 Relatório | figuras e tabelas em PT-BR, metodologia, limitações, ameaças à validade | todas as figuras regeneram de `results/` com `mise run analyze` |

Antes do M7, reportar a estimativa de tempo total de máquina (a partir da calibração do M0) e aguardar aprovação.

## Critérios de aceite finais

- As quatro versões passam em todos os vetores dourados e rejeitam todas as configs inválidas.
- AWGN e Rayleigh com CSI perfeito são compatíveis com a teoria; o perfil principal é estatisticamente equivalente entre as quatro linguagens.
- Contagens independem do número de workers.
- Relatório com throughput single-thread (P-core e E-core), stages, escalabilidade em E-cores, memória, BER × `Eb/N0` com IC, todos com IC e metadados suficientes para reproduzir.
- Setup, warmup/JIT e trabalho aparecem separados; nenhuma comparação mistura cargas diferentes.

## Ameaças à validade (registrar no relatório)

- RNGs diferentes por linguagem: custo visível no estágio `bits`/`awgn`/`channel_conv`.
- Backends FFT diferentes: FFTW (IT++ via apt e FFTW.jl com versões possivelmente distintas), pocketfft (NumPy), rustfft.
- IT++ do apt compilada com flags genéricas; C++ do usuário com `-march=native`.
- CPU híbrida e notebook com limite térmico: mitigados por pinagem, turbo desligado, cooldown e ordem aleatória, não eliminados.
- Autoria por agente de IA nas quatro linguagens.

## Decisões assumidas (mudar aqui se discordar)

1. Somente 16-QAM na trilha principal; 64-QAM como extensão.
2. Somente APIs padrão; versões aceleradas (Numba, JAX etc.) em trilha separada.
3. Orçamento de máquina desconhecido: o M0 mede e o M7 espera aprovação.
4. Turbo desligado na rodada primária.
