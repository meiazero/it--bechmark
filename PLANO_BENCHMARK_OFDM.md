# Plano: benchmark comparativo de IT++ e Python, Julia e Rust

## Objetivo

Construir um simulador OFDM ponto a ponto reproduzível para comparar a implementação de referência em C++/IT++ com implementações idiomáticas em Python, Julia e Rust. Avaliar separadamente desempenho, correção, memória, escalabilidade e ergonomia; não reduzir o resultado a um único ranking de velocidade.

Princípio de justiça: **mesmo algoritmo, mesma carga, mesmo contrato numérico, mesmas regras de otimização, mesmo ambiente medido**. Tudo o que difere entre linguagens (RNG, backend FFT, runtime) é registrado e isolado por medição de estágios, nunca escondido.

## Uso como lecture: otimização, trade-offs e telecomunicações

A revisão de 2026-09-30 prepara o código já entregue em M0–M4 para uma lecture.
Nessa revisão inicial, o escopo era C++/IT++, Python/NumPy, Rust e este plano;
M5–M10 estavam pendentes. A versão legível precisa manter as mesmas contagens para
cada semente e os mesmos vetores dourados, com evidência anterior/posterior.
O roteiro executável e as derivações estão em `LECTURE.md`.

Na continuação para a lecture, M5 Julia passou no aceite e na revisão
independente. As quatro linguagens agora compartilham o roteiro executável;
M6 também passou: harness, cinco suítes smoke e figuras/tabelas em PT-BR.
M7 passou com coleta fixa independente: 128 verificações de teoria e 96 pares
de linguagens, sem incompatibilidade. Os 32 casos AWGN de 16–30 dB com menos de
100 erros permanecem com evidência insuficiente, sem aprovação automática.
M8 passou no aceite: uma rodada de profiler por linguagem, otimizações mínimas
e 2.048 lotes congelados após C++ na CPU 2 superar 5 s. M9–M10 permanecem
pendentes. M8 passou em duas revisões independentes após correções de texto
e proveniência, sem achado bloqueante restante.

| Bloco | Pergunta que a lecture responde | Evidência prática |
|---|---|---|
| Modelo OFDM | Por que o CP transforma a convolução em ganho por subportadora? | golden de CP/canal, Parseval e resposta `H[k]` |
| Receptor | O que LS, interpolação e ZF preservam ou amplificam? | golden de estimação, gap no DC, caso `Ĥ = 0` |
| Custo computacional | Qual trabalho é invariável e qual cresce com lote/símbolo? | geometria preparada no setup, convolução direta, FFT de biblioteca |
| Trade-offs | Como lote vetorizado, buffers por símbolo e processos trocam memória por trabalho? | leitura da mesma cadeia nas quatro versões; medição completa somente em M9 |
| Inferência | O que correção numérica e uma medição curta permitem concluir? | golden/E2E, limites da parada adaptativa, diferença entre compatibilidade e equivalência |

Separar três tipos de afirmação: **derivação** do modelo, **verificação** por
artefato e **medição** sob protocolo. Remover consultas JSON e geometria
invariável do laço aproxima C++ da preparação já feita por Python e Rust;
esta revisão não estima speedup. A única rodada de profiler por linguagem
foi executada no M8, após as quatro versões funcionarem; não há estimativa de
speedup anterior/posterior baseada nessas amostras.

## Regras para o agente implementador (Codex)

1. O diretório `contract/` é a fonte da verdade. Não altere valores do contrato; se algo for impossível de cumprir, pare e reporte com evidência.
2. Execute M2 → M10 em sequência pelo "Loop de execução" (seção "Marcos"), sem pedir confirmação entre marcos. Um commit por marco, no `main`, só com o aceite passando e a validação sem achado bloqueante.
3. Sem stubs, TODOs ou testes desativados para "passar". Teste que falha é corrigido dentro do loop.
4. Não introduza dependências fora das listadas; qualquer adição exige justificativa no `NOTES.md` e na mensagem do commit.
5. Registre cada desvio do contrato, bug encontrado e otimização aplicada em `impl/<lang>/NOTES.md`.

## Escopo

- Simulação complexa em banda-base, sem codificação de canal, curva BER × `Eb/N0`.
- Caminho completo: bits → 16-QAM → grade de subportadoras + pilotos → IFFT → CP → canal Rayleigh multipercurso (convolução no tempo) + AWGN → remoção do CP → FFT → estimação LS nos pilotos + interpolação linear → equalização ZF → decisão abrupta → contagem de erros.
- Execução single-thread, escalabilidade multi-thread/multiprocesso, medições por estágio e memória.

Fora do escopo: FEC, sincronização, SDR/RF, GPU, precisão `Float32`, comparação de compiladores, tuning de backend FFT como objetivo próprio.
Extensões opcionais, sempre em trilha separada e rotulada: 64-QAM, Numba/JAX, Python free-threaded, energia via RAPL.

**MMSE fora da trilha principal:** no modelo escalar SISO com energia unitária, o coeficiente MMSE é `H* / (|H|² + N0)`. Seu ganho sobre o símbolo é `a = |H|²/(|H|² + N0)`. Para `H ≠ 0`, remover esse ganho produz ZF. Aplicar o coeficiente enviesado aos limiares fixos de 16-QAM muda a decisão por encolher a amplitude; isso não fundamenta uma afirmação universal de BER pior. Comparar políticas de receptor seria outro experimento. A trilha principal preserva ZF para comparar implementações do mesmo algoritmo.

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

**mise é só gerenciador de versões de linguagem/ferramenta.** `mise.toml` contém apenas `[tools]`: sem `[env]`, sem `[tasks]`, e nenhum comando do projeto usa `mise run` ou `mise exec`. O shell interativo tem `mise activate`; em shell não interativo (agente), rodar `eval "$(mise env -s bash)"` antes de qualquer `make`, senão o `make doctor` acusa versões erradas de `uv`, `rust` e `cmake`. Tarefas e variáveis de ambiente ficam no `Makefile` da raiz (GNU Make 4.3, já instalado).

`mise.toml` (valores de `mise latest` em 2026-09-30):

```toml
[tools]
python = "3.14.7"
uv = "0.12.20"
julia = "1.13.1"
rust = "1.98.1"
cmake = "4.4.3"
ninja = "1.13.2"
tokei = "15.0.0"
```

Variáveis de ambiente de threads (`OMP_NUM_THREADS=1`, `OPENBLAS_NUM_THREADS=1`, `MKL_NUM_THREADS=1`, `PYTHONHASHSEED=0`) são exportadas pelo `Makefile` (`export VAR := valor`) e herdadas por tudo que os alvos lançam. O orquestrador grava os valores efetivos em `env.json` e aborta se algum divergir.

Bibliotecas por lockfile commitado:

- Python: `uv.lock` em `impl/python` (NumPy; PyPI mostra 2.5.3 com suporte a 3.14) e `uv.lock` separado em `tools/` (SciPy, psutil, matplotlib — nunca importados pela implementação Python). JSON via stdlib.
- Julia: `Project.toml` + `Manifest.toml` (FFTW.jl, JSON3.jl).
- Rust: `Cargo.lock` (`rustfft`, `num-complex`, `rand`, `rand_distr`, `rayon`, `serde`, `serde_json`).

Sistema (mise não fixa bibliotecas C++; versões de `apt-cache policy` em 2026-09-30):

- `g++` 13.3.0 (sistema), `libitpp-dev=4.3.1-10build1`, `libfftw3-dev=3.3.10-1ubuntu3`, `nlohmann-json3-dev=3.11.3-1` (parser JSON do C++).
- `tools/check_system.py` aborta se as versões instaladas divergirem das fixadas.

Alvos do `Makefile` (todos `.PHONY`; cada marco acrescenta os seus):

| Alvo | Executa |
|---|---|
| `make doctor` | `python tools/check_system.py` |
| `make golden` | `python -m tools.golden.generate`, `uv run --project tools --locked python tools/theory.py`, `python tools/check_golden.py --self-test` |
| `make test` | `uv run --project tools --locked python -m unittest discover -s tools -p 'test_*.py'` + testes de cada implementação já existente |
| `make bench SUITE=smoke` / `SUITE=single` / `SUITE=scaling,memory` | `uv run --project tools --locked python -m bench --suite $(SUITE)` |
| `make validate` | `uv run --project tools --locked python -m bench.validate` (testes estatísticos da seção "Validação") |
| `make analyze` | `uv run --project tools --locked python -m bench.analyze` |

Build por linguagem também vira alvo (`make build-cpp`, `build-rust`, ...) quando o marco correspondente chegar.

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
| C++ | RNG da IT++ (M0 provou estado independente por thread), semeado pelo estado completo: ver abaixo |

**Semente de 64 bits na IT++:** `RNG_reset(unsigned int)` aceita só 32 bits. Truncar `s` gera colisão de sementes com probabilidade ≈ 0,39% dentro de um ponto (5.813 lotes com `max_bits = 1e9`) e ≈ 63% na curva inteira (93.008 lotes), por cálculo de aniversário sobre 2³² em 2026-09-30. Regra: preencher o estado inteiro via `RNG_set_state` com palavras consecutivas de um fluxo SplitMix64 iniciado em `s`. Teste C++ obrigatório: mesmo `s` → mesma sequência; dois `s` que diferem só nos 32 bits altos → sequências diferentes. Se `RNG_set_state` rejeitar estado arbitrário ou o teste falhar, usar `std::mt19937_64(s)` para todo o C++ e registrar em `impl/cpp/NOTES.md`. Truncar para 32 bits é proibido.

- Sequências não precisam coincidir entre linguagens. A validação cruzada é estatística.
- Resultado de cada lote depende só de `(master_seed, point_index, batch_index)` → independente do número de workers.

### Critério de parada (modo BER)

- `K` = menor índice de lote tal que, somando os lotes `0..K` em ordem: `erros ≥ target_errors` e `lotes ≥ min_batches`; ou `bits ≥ max_bits`.
- Workers podem processar além de `K`; lotes excedentes são descartados.
- Resultado idêntico para qualquer número de workers (testado).
- Padrões: `target_errors = 1000`, `min_batches = 32`, `max_bits = 1e9`, `EbN0_dB = 0:2:30`. Todos configuráveis.

### Validação de configuração

- `workers` existe **só** na CLI (`--workers`), nunca no arquivo de configuração: uma única fonte de verdade, e o mesmo arquivo serve para todos os `p` da escalabilidade.
- Rejeitar: dimensões incompatíveis, `N_cp < n_taps − 1`, `M ≠ 16`, valores não finitos, `--workers < 1`, `B < 1`, `max_bits < min_batches · B · 672`, semente fora de `u64`.
- Toda implementação rejeita todos os arquivos de `contract/invalid_configs/`: código de saída 2, mensagem em stderr, nenhuma saída de resultado.
- Contadores em `u64`.

### CLI comum

```
<impl> --config <arquivo.json> --mode {golden,ber,perf,stages} --workers <p> --out <arquivo.jsonl>
```

Códigos de saída: 0 sucesso, 1 erro de execução, 2 configuração inválida.

### Saída

JSON Lines validado por `contract/result.schema.json`, um registro por ponto `Eb/N0`:

- `schema_version`, `impl`, `git_sha`, `mode`, `profile_id`, `config_sha256` (SHA-256 dos bytes do arquivo de configuração como lido do disco; nenhuma linguagem reserializa JSON), `master_seed`, `workers`, `ebn0_db`.
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
- FFTW: mesma flag de planejamento em C++ e Julia; o M0 mediu `FFTW_ESTIMATE` (flag 64) na IT++, então a Julia usa `flags=FFTW.ESTIMATE`.

**Orçamento de otimização igual:** depois de passar na correção, cada implementação recebe exatamente uma rodada guiada por profiler (`perf` para C++/Rust, `Profile` para Julia, `py-spy` para Python), com mudanças registradas em `NOTES.md`.

## Harness de benchmark

Orquestrador em Python (`bench/`, ambiente de `tools/`), fixado na CPU 0.

### Modos de medição

- **`perf` (primário):** carga fixa em `EbN0 = 10 dB`, `n_batches` calibrado no M8 para que C++ single-thread leve ≥ 5 s, depois congelado; até lá fica `null` no perfil e a suíte `smoke` usa uma config derivada (ver "Marcos"). Sem timers internos além de `t0`/`t1` ao redor do trabalho. Throughput = `n_batches · 256 · 672 / work_s`.
- **`stages`:** cada estágio isolado sobre entradas pré-geradas de um lote, R repetições, mediana em ns por símbolo OFDM. `channel_conv` recebe taps retidos, sem RNG dentro do timer. `bits` e `awgn` incluem seus sorteios por definição; a geração de taps está no `e2e` e no profiler. O `e2e` usa semente distinta e reprodutível em cada repetição, igual nas regras das linguagens. Estágios: `bits`, `qam_map`, `grid`, `ifft`, `cp_add`, `channel_conv`, `awgn`, `cp_remove`, `fft`, `chan_est`, `zf`, `demap_count`. Reportar a soma dos estágios contra o `e2e`; a diferença é um resíduo descritivo: inclui geração de taps, glue, alocação e efeitos de cache/temporização; a soma de medianas isoladas não decompõe exatamente a mediana ponta a ponta.
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
- `mise ls --current --json` (só leitura de versões), SHA-256 dos lockfiles, `dpkg-query -W g++ libitpp-dev libfftw3-dev`, flags de compilação, variáveis de threads.
- `git_sha` e flag de working tree suja, semente da ordem de execução, data.

Dados brutos nunca são descartados; a agregação lê de `results/<run_id>/raw/`.

## Análise estatística

- **Desempenho:** mediana dos 10 `work_s` por configuração, IC 95% bootstrap (10.000 reamostras, semente fixa). Speedup em relação ao C++ com IC bootstrap da razão das medianas. Reportar também min e IQR.
- **BER:** sob carga fixa, lotes são i.i.d. (canal independente por símbolo), mas os erros dentro de um símbolo são correlacionados. IC 95% pela média de lotes (`t` com `n_batches − 1` g.l.), calculado de `n_errors` e `sum_batch_errors_sq`. Nunca usar IC binomial por bit.
- **Zero erros:** sob tamanho fixo, reportar `BER < 1 − 0,05^(1/n_symbols)` (limite de 95% sobre a probabilidade de um símbolo ter algum erro, que limita a BER). Nunca BER = 0.
- **Comparação entre linguagens:** para cada ponto e cada par de linguagens, teste **t de Welch**, com graus de liberdade de Welch–Satterthwaite, sobre as médias de lotes; α = 0,01 com Bonferroni (6 pares × número de pontos). O resultado testa diferença de médias: não rejeitar não demonstra equivalência. Reportar diferença, IC e p-valor como compatibilidade estatística. Equivalência formal requer margens de BER com justificativa de telecomunicações, definidas antes da coleta, e TOST; nenhuma margem será inventada nesta revisão.

A curva `ber` usa parada por erros e permanece descritiva: o número de lotes
observados depende dos erros. IC t e limite de zero erros não têm cobertura
nominal garantida sob parada adaptativa. Para validação inferencial no M7,
usar coleta independente com quantidade de lotes `N` definida antes de observar
os resultados: config derivada com `min_batches = N`,
`max_bits = N · 256 · 672` e `target_errors = max_bits + 1`, dentro de `u64`.
Isso usa a CLI existente e força parada por orçamento, sem mudar `contract/`.
Não escolher `N` após olhar o p-valor.

Referências metodológicas: [Welch na documentação SciPy](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.ttest_ind.html)
e [TOST e margens na documentação statsmodels](https://www.statsmodels.org/stable/generated/statsmodels.stats.weightstats.ttost_ind.html).
Estas referências não acrescentam dependências à implementação.

## Validação

### Vetores dourados

`tools/golden/` usa **só a stdlib do Python** (`math`, `cmath`, DFT direta O(N²) com twiddles indexados por `(k·n) mod N`, nunca `exp` de `2π·k·n/N` com argumento grande) e não importa nenhuma implementação competidora. Gera entradas e saídas esperadas para:

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

- AWGN (`h = [1]`, CSI perfeito), na coleta fixa independente: avaliar teoria com IC simultâneos de família 99%; cada um usa `α_local = 0,01/m`, em que `m` conta os pontos e implementações dos dois cenários teóricos. O critério de ≥ 100 erros indica suficiência para a aproximação por lotes; abaixo disso, registrar "evidência insuficiente", sem aprovação automática ou coleta até obter significância.
- Rayleigh com CSI perfeito: mesma coleta fixa e família de IC contra a teoria de Rayleigh.
- Rayleigh com CSI estimado (perfil principal): comparação das quatro linguagens na coleta fixa pela seção "Análise estatística"; compatibilidade não será rotulada como equivalência.
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
mise.toml        só [tools]
Makefile         tarefas e variáveis de ambiente
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

## Marcos (um commit cada)

Duas fases. A Fase 1 entrega o caminho inteiro funcionando, das quatro implementações até `make analyze`, em carga reduzida. A Fase 2 analisa, corrige, otimiza e só então mede em escala. M0–M8 estão concluídos e commitados; M9–M10 permanecem pendentes.

**Regra da Fase 1:** sem teste estatístico contra teoria, profiling ou calibração. Achado não bloqueante vai para a seção "Pendente para a Fase 2" do `NOTES.md` da linguagem e é resolvido no M7.

### Loop de execução

Para cada marco, de M2 a M10, sem pausa entre eles:

1. **Implementar** a entrega do marco.
2. **Aceite:** rodar o comando de aceite do marco. Falhou → corrigir e repetir este passo.
3. **Validar com GPT Luna:** abrir um subagente `explorer` novo (`~/.codex/agents/explorer.toml`, modelo `gpt-5.6-luna`), sem o histórico de rodadas anteriores. Ele não edita arquivos; pode ler o repositório e rodar testes e comandos de aceite. Entrada: este plano, `AGENTS.md`, `git diff HEAD` e a saída do aceite. Saída: lista de achados, cada um com `arquivo:linha`, evidência e classe `bloqueante` ou `não bloqueante`.
4. **Corrigir:** achado bloqueante → corrigir e voltar ao passo 2. Achado não bloqueante → na Fase 1, registrar em "Pendente para a Fase 2"; na Fase 2, corrigir e voltar ao passo 2.
5. **Fechar:** aceite passando e validação sem bloqueante → registrar no `NOTES.md` cada ciclo (achados e correções), commitar `feat(mN): ...` e seguir para o próximo marco.

**Bloqueante** = viola o contrato, uma regra de "Regras de implementação idiomática" ou o `AGENTS.md`, ou faz o aceite passar sem provar o que promete (stub, teste tautológico, tolerância afrouxada).

**Condições de parada (as únicas):**

1. Valor do contrato impossível de cumprir: parar e reportar com evidência.
2. Ação que só o usuário pode fazer (`sudo`, instalar pacote do sistema, gravar `no_turbo`, ligar o carregador): parar e reportar o comando exato.
3. O mesmo achado bloqueante sobrevive a 3 ciclos de correção: parar e reportar a premissa suspeita, o teste que a confirma e um caminho alternativo.

**Carga `smoke`:** config derivada pelo harness a partir de `profile_main.json` (`perf.n_batches` pequeno, poucos pontos `Eb/N0`, 1 repetição, sem cooldown, carga longa curta), gravada em `results/<run_id>/`. Nunca entra em `contract/` e nunca é usada em comparação publicada. Antes do M6, os testes de `perf` e `stages` usam uma cópia temporária do perfil com `perf.n_batches` pequeno, criada pelo próprio teste.

### Fase 1 — ponta a ponta

| Marco | Entrega | Aceite |
|---|---|---|
| M0 Ambiente | `mise.toml`, `check_system.py`, `git init`. Descobrir: flag FFTW da IT++, segurança do RNG IT++ por thread (teste com 2 threads e mesma semente). | `make doctor` passa; achados em `impl/cpp/NOTES.md` |
| M1 Contrato | perfil, schemas, `invalid_configs`, gerador golden, `theory.py`, `check_golden.py` | `make golden` e `make test` passam; regenerar produz arquivos byte-idênticos |
| M2 C++/IT++ | serial + paralelo, modos `golden`/`ber`/`perf`/`stages` | golden, configs inválidas, teste da semente de 64 bits, `--workers 1` e `--workers 4` com contagens idênticas |
| M3–M5 Python, Rust, Julia | mesmos modos | mesmo aceite do M2, exceto o teste da semente de 64 bits |
| M6 Harness e relatório esqueleto | orquestrador, `env.json`, pinagem, todas as suítes (`single`, `stages`, `scaling`, `memory`, `ber`) na carga `smoke`; análise, tabelas e figuras em PT-BR | `make bench SUITE=smoke` e `make analyze` rodam sem erro e geram `results/` e `report/` com as quatro linguagens |

### Fase 2 — análises e correções

| Marco | Entrega | Aceite |
|---|---|---|
| M7 Validação e correções | revisão das quatro implementações e do harness contra este plano; testes estatísticos (AWGN e Rayleigh-CSI contra teoria, compatibilidade entre linguagens, determinismo); correção de todo achado, incluindo os pendentes da Fase 1 | `make test`, golden e `make validate` passam; cada achado e correção registrado em `NOTES.md` |
| M8 Otimização e calibração | uma rodada de profiler por linguagem; depois calibrar `perf.n_batches` (C++ single-thread na CPU 2 ≥ 5 s), gravar no perfil e congelar | golden e `make validate` continuam passando; `n_batches` gravado |
| M9 Medição completa | suítes `single`, `scaling`, `memory` na carga congelada, com repetições e controle de ruído completos | `make bench SUITE=single` e `make bench SUITE=scaling,memory` geram `results/` completo |
| M10 Relatório final | figuras e tabelas em PT-BR, metodologia, limitações, ameaças à validade | todas as figuras regeneram de `results/` com `make analyze` |

Antes do M9, registrar em `bench/NOTES.md` a estimativa de tempo total de máquina (a partir da calibração do M8 e dos tempos medidos no smoke do M6) e seguir sem pausa.

## Critérios de aceite finais

- As quatro versões passam em todos os vetores dourados e rejeitam todas as configs inválidas.
- AWGN e Rayleigh com CSI perfeito são compatíveis com a teoria; o perfil principal tem a comparação entre linguagens reportada com diferença, IC e p-valor; equivalência só pode ser afirmada com margens previamente justificadas e TOST.
- Contagens independem do número de workers.
- Relatório com throughput single-thread (P-core e E-core), stages, escalabilidade em E-cores, memória, BER × `Eb/N0` com IC, todos com IC e metadados suficientes para reproduzir.
- Setup, warmup/JIT e trabalho aparecem separados; nenhuma comparação mistura cargas diferentes.

## Ameaças à validade (registrar no relatório)

- RNGs diferentes por linguagem: custo de bits e ruído nos estágios `bits`/`awgn`; taps no `e2e` e no profiler, fora do timer de `channel_conv`.
- Backends FFT diferentes: FFTW (IT++ via apt e FFTW.jl com versões possivelmente distintas), pocketfft (NumPy), rustfft. C++ delega o ciclo de vida dos planos à interface IT++; Rust retém planos e scratch explícitos. M0 verificou flags e escala, não reutilização de planos; M8 deve observar esse custo.
- IT++ do apt compilada com flags genéricas; C++ do usuário com `-march=native`.
- CPU híbrida e notebook com limite térmico: mitigados por pinagem, turbo desligado, cooldown e ordem aleatória, não eliminados.
- Autoria por agente de IA nas quatro linguagens.

## Decisões assumidas (mudar aqui se discordar)

1. Somente 16-QAM na trilha principal; 64-QAM como extensão.
2. Somente APIs padrão; versões aceleradas (Numba, JAX etc.) em trilha separada.
3. Orçamento de máquina desconhecido: o M6 mede o smoke, o M8 calibra e a estimativa fica registrada antes do M9, sem pausa.
4. Turbo desligado na rodada primária.
