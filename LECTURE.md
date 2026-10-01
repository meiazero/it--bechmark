# OFDM optimization lecture

This lecture uses the C++/IT++, Python/NumPy, Rust, and Julia simulators from
M2–M5. The M6 smoke harness generates Portuguese figures and tables for all four
languages. M7 adds fixed-sample statistical validation; sparse points retain an
insufficient-evidence status. Profiler rounds and the complete benchmark remain
future milestones. Smoke timings demonstrate execution only;
primary performance conclusions require M8–M9.

## 1. Start with an executable numerical model

Activate the pinned tools in a noninteractive Bash shell and run acceptance:

```bash
eval "$(mise env -s bash)"
make doctor
make test
```

The E2E scenarios write inputs and outputs under
`results/acceptance/{cpp,python,rust,julia}/`. These are short correctness checks,
not publication measurements. `golden.jsonl` contains intermediate signals;
`ber-1-0.jsonl` and `ber-4-1.jsonl` demonstrate worker-independent stopping;
`stages.jsonl` contains isolated timing diagnostics.

Read each `Worker.batch` beside the plan. Follow the same signal through mapping,
resource grid, inverse FFT, cyclic prefix, direct channel convolution, noise,
prefix removal, FFT, channel estimation, equalization, and decisions.
In Python the first array axis holds independent OFDM symbols; C++, Rust, and Julia
advance through one symbol at a time. A batch contains 256 OFDM symbols and
172,032 payload bits in every implementation.

## 2. Derive the telecommunications invariants

For the frozen profile, $N=256$, $N_{cp}=32$, $N_d=168$, $N_p=24$, and
$L=8$. Four payload bits label each Gray 16-QAM symbol. On each axis,
`00, 01, 11, 10` label `-3, -1, +1, +3`; division by $\sqrt{10}$ makes
mean constellation energy one. Threshold ties select the higher level.
The complete mapping and its threshold behavior are golden inputs.

The signal transforms are unitary:

$$x[n]=\frac{1}{\sqrt{N}}\sum_k X[k]e^{j2\pi kn/N},\qquad
Y[k]=\frac{1}{\sqrt{N}}\sum_n y[n]e^{-j2\pi kn/N}.$$

Parseval therefore gives $\sum_n|x[n]|^2=\sum_k|X[k]|^2$.
Library normalization is part of the interface: NumPy uses `norm="ortho"`;
IT++ requires inverse multiplication by $\sqrt{N}$ and forward division by
$\sqrt{N}$; rustfft and Julia's FFTW forward/backward plans require division
by $\sqrt{N}$ on both paths. Julia retains concrete plans with `FFTW.ESTIMATE`,
matching the planning flag observed in IT++.
The IT++ scaling and planning flags are established by the local M0 probe.
C++ delegates plan lifetime to the IT++ function interface and pre-exercises
both directions during setup; Rust retains explicit plans and scratch. M0
does not establish plan reuse, which M8 should inspect before timing claims. NumPy's
[normalization documentation](https://numpy.org/doc/stable/reference/routines.fft.html#normalization)
explains `ortho`. Neither convention licenses rescaling the channel gains.

Because $N_{cp}\ge L-1$, removing the prefix leaves a circular convolution of
the useful samples. Under the profile's symbol-local block fading model,

$$Y[k]=H[k]X[k]+W[k],\qquad
H[k]=\sum_{\ell=0}^{L-1}h_\ell e^{-j2\pi k\ell/N}.$$

$H$ is the **unscaled** DFT of the taps even when the signal FFTs are unitary.
Scaling $H$ as a signal FFT would change equalized amplitudes. The causal
288-sample receive window discards the seven-sample convolution tail; this
models independent prefixed symbols, not an RF synchronization experiment.

The noise convention accounts for pilot and prefix overhead:

$$E_{sym}=192\frac{288}{256}=216,\qquad
N_0=\frac{216}{672\,10^{E_b/N_0\,[dB]/10}}.$$

This is nominal ensemble energy, not a measured energy adjustment for each
symbol. Each real noise component has variance $N_0/2$.
Data-subcarrier $E_s/N_0=\gamma_b\,672/216$; the payload-only 16-QAM reference
has an overhead offset of $10\log_{10}(168/216)\approx-1.09$ dB.
Using the payload-only curve without that adjustment is a model error.

LS estimates on pilots are $\hat H_p=Y_p/P_p$. For data bin $k$ between pilots
$k_l$ and $k_r$, $a=(k-k_l)/(k_r-k_l)$ and
$\hat H[k]=\hat H_l+a(\hat H_r-\hat H_l)$. Use signed physical bins,
not wrapped FFT storage indices. Across DC the interval is 16 bins.
ZF computes $\hat X=Y/\hat H$: small gains amplify noise; the exact-zero
policy returns zero and increments a separate counter. It does not clip
small nonzero gains. These are distinct mathematical behaviors.

## 3. Locate work before optimizing it

| Operation | Work per OFDM symbol | Implementation trade-off |
|---|---|---|
| Mapping, grid, CP, ZF, decisions | Linear in their input sizes | Contiguous arrays simplify memory access; temporary arrays add traffic |
| Library FFT/IFFT | Typical $O(N\log N)$ | Backend and normalization differ; runtime timings must include the chosen library |
| Direct causal convolution | $O((N+N_{cp})L)$ | Eight taps keep the workload small; FFT convolution would change the experiment |
| LS and interpolation | $O(N_p+N_d)$ after setup | Retained indices and weights trade a small fixed allocation for repeated search/parsing |
| Random bits, taps, noise | Linear in the draw count | Idiomatic RNGs have different costs and different sample streams |
| Perfect-CSI response | Direct tap DFT in C++/Rust; FFT in Python | Diagnostic only, outside performance comparisons |

The refactor moves C++ JSON access, wrapped indices, interpolation searches,
and tap scale calculation into `DspConfig` during setup. Python retains its
pilot values and Gray level table; Rust already prepared geometry and tap
scales. The same operations remain in the same model. Removing invariant
work is justified by where it occurs, not by a claimed stopwatch result.
All four paths now name transmit and receive signals explicitly.

Python vectorizes a full batch and exchanges more live array storage for fewer
interpreter loops. C++, Rust, and Julia use symbol-sized temporary vectors and exchange
smaller live working sets for repeated allocation. Persistent processes in
Python avoid per-batch interpreter startup but add serialization and process
memory. Threads share address space in C++, Rust, and Julia. These are mechanisms to
investigate in M8–M9, not conclusions about which implementation is faster.
For one complex128 signal buffer, the payload alone is 1 MiB for a
256-by-256 batch versus 4 KiB for one 256-sample symbol; a prefixed buffer
is 1.125 MiB versus 4.5 KiB. These are element-count derivations, not RSS
measurements; live intermediates, allocators, FFT scratch, and processes add memory.
Do not add buffer pools or specialized kernels until the permitted profiler
round identifies a hotspot.

## 4. Interpret timing with the correct denominator

Every isolated stage consumes a retained batch of inputs. `channel_conv` also
consumes retained channel taps; it excludes tap generation. `bits` and `awgn`
include their random draws because generation is their operation. Each `e2e`
repetition derives a distinct reproducible batch seed. Time is reported in
nanoseconds per **OFDM symbol**, not per QAM symbol or per bit.

The sum of isolated stage medians does not equal the end-to-end median by
construction. Its residual includes tap generation, orchestration, allocation,
cache interactions, and timer/dispatch overhead. It can even be negative;
it is not an estimate of one named physical component. Retained stage inputs
and a complete chain also have different cache histories.

For primary performance, use fixed batches and payload throughput:

$$R_b=\frac{n_{batches}\,256\,672}{t_{work}}.$$

Compare the same frozen workload, core class, worker count, thread limits,
and turbo state. Separate setup, warmup, work, and external process time.
M8 calibrates workload; M9 collects independent process repetitions and memory.
A P-core single-worker run cannot be the efficiency denominator for E-core
scaling. Changing the contract to make a version faster invalidates the comparison.

## 5. Separate verification from scientific inference

Golden agreement checks mathematical operators against an independent stdlib
oracle. E2E agreement checks execution, metadata, stopping, invalid inputs,
and worker determinism. Neither establishes agreement with theoretical BER
or a performance advantage. M7's independent collection uses 256 fixed batches
at every one of the 16 profile points. Its 128 simultaneous theory checks and
96 Welch pair comparisons found no incompatible case. The 32 AWGN cases at
16–30 dB had fewer than 100 errors and remain insufficient, without approval
or extra collection after outcomes. The generated tables are under the validation
run identified by `results/VALIDATION_LATEST`; its protocol was saved first.

Within a channel realization, bit errors can be correlated. Batch error rates,
not individual bits, are the sampling units used for uncertainty.
For $n>1$ fixed batches with $m=172032$ bits each, let $S_1$ be `n_errors`
and $S_2$ be `sum_batch_errors_sq`. Then

$$\hat p=\frac{S_1}{nm},\qquad
s_e^2=\frac{S_2-S_1^2/n}{n-1},\qquad
SE(\hat p)=\frac{\sqrt{s_e^2/n}}{m}.$$

A batch-mean t interval uses $n-1$ degrees of freedom, with its limits
restricted to $[0,1]$ for reporting. It is an approximation whose adequacy
must be assessed, particularly with sparse errors; zero-error intervals
use the bound below. The shared counters support this calculation without
assuming independent bit errors. The adaptive
BER stopping rule makes observed batch count depend on errors; ordinary fixed
sample t intervals do not automatically retain their coverage under that rule.
M7 uses an independent fixed-batch validation collection specified before
outcomes are observed in `bench/validation_protocol.json`.

Welch's t-test asks whether means differ. A large p-value does not demonstrate
equivalence. See the [SciPy test definition](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.ttest_ind.html).
Formal equivalence requires a scientifically justified interval of acceptable
BER differences set before collection; [TOST](https://www.statsmodels.org/stable/generated/statsmodels.stats.weightstats.ttost_ind.html)
tests that interval. No equivalence margin is supplied by this lecture and no
statsmodels dependency is introduced.

For zero observed errors at a fixed sample size, the 95% upper bound on the
probability of an OFDM symbol having any error is
$1-0.05^{1/n_{symbols}}$. That probability also bounds BER because a symbol's
error fraction cannot exceed its indicator of any error. Report an upper bound,
not a measured BER of zero. State the independent-symbol and fixed-size assumptions.

Useful lecture exercises are to explain the DC interpolation interval from
`golden.jsonl`, recover payload throughput units from a `perf` record, and
identify what evidence would be needed before calling a change an optimization
success. Each answer should name its supporting derivation or artifact.
