# Benchmark harness notes

## M6 design and failure boundaries

The real-process E2E scenario was written before orchestration. It covers all
four languages and five suites, memory timeout retention, byte fingerprints,
thread limits, raw counters, and regenerated lecture artifacts.
Failure boundaries include missing tools/cgroup, battery power, incompatible
CPU geometry/affinity, oversubscription, stale hashes, partial output, process
failure, and timeout. Each subprocess is pinned; the orchestrator uses CPU 0.

Smoke derives its configuration outside contract/: four perf batches, three
stage repetitions, three BER points, one new process per configuration, zero
cooldown, and ten-second long-memory timeouts. All raw commands, output streams,
RSS samples, temperatures, fingerprints and environment metadata are retained.
No smoke timing is a publication result, and no missing interval is invented.

The planned psutil and matplotlib dependencies were added to tools/uv.lock.
No production implementation imports either. Pkg's Julia FFTW artifact differs
from the system IT++ backend; lock hashes remain in environment provenance.

The agent shell omitted the existing user-session bus variables. An initial
systemd-run probe failed with "No medium found"; supplying /run/user/1000/bus
through the subprocess environment made memory.peak available. No service or
system setting was changed. A race between polling and reading a terminated
process's children is handled as an empty tree rather than failing capture.

Each memory scope includes the observer process and page cache. RSS samples
cover only the simulator tree. Memory timeouts preserve samples and metadata,
without fabricating simulator counters. Post-warmup deltas are explicitly
estimates in M6, derived from the reported work window; M7 must replace them
with an explicit phase marker before published memory measurement.

## Pending for Phase 2

M7: explicit warmup boundary for memory baselines; statistical validation using
fixed predeclared sample sizes; recheck result counter/schema relationships.
M8: the single profiler round per language and real workload calibration.
Before M9: measured machine-time estimate, CV noise detection/repetition,
turbo-on confirmation, ratio/scaling confidence intervals, and complete
memory growth classification. M10: clean-build/LOC/dependency ergonomics and
final interpretation. These are unmeasured, not silently accepted by smoke.

## M6 review cycle 1

make bench SUITE=smoke completed 40 real executions (8 single, 4 stages,
16 scaling, 8 memory, 4 BER) and make analyze generated all lecture artifacts.
make test passed 26 tests in 272.636 seconds. Independent review found a blocker:
English figure/CSV labels violated the Portuguese presentation requirement.
Labels were translated while retaining English code identifiers and raw contract
keys. A nonblocking memory-only analysis failure (rows[0] on no completed JSONL)
was also corrected; empty summaries retain the full column schema and figures
explicitly mark unavailable suites. The E2E now retains a projection of real
memory timeout captures to reproduce this boundary without invented results.

## M6 review cycle 2

The corrected smoke/analysis completed again; the targeted E2E passed in
151.245 seconds. Fresh review accepted the Portuguese labels and memory-only
summary, but found that throughput lacked the promised missing-data annotation
and that three empty CSVs cited by the README were absent. The figure exporter
now marks each empty axis, all tables keep explicit headers even without rows,
and the real-artifact E2E checks every absent-suite annotation/table. Projection
analysis no longer replaces report/LATEST for the actual benchmark run.

## M6 missing-data premise correction

The real memory-only regression revealed that Matplotlib has_data is true for
empty BER lines created solely for legend labels. The data boundary now skips
languages with no retained BER records before creating artists. Censored zero
error points remain upper-bound markers, with gaps in the connecting line.
This changes the missing-data premise, rather than adding another renderer flag.
No raw observation was removed or replaced. The regression retains all empty
CSV schemas and demands no-data annotations in every absent suite.

## M6 closure

The final real E2E (make bench SUITE=smoke, make analyze, and the real timeout
projection) passed in 149.491 seconds. The actual run is
results/20260930T232731-91208 with 40 executions; generated artifacts are under
report/20260930T232731-91208. A fresh final read-only Luna explorer review found
no blocker and no additional nonblocking finding beyond the recorded Phase2
work. Ruff passed. The frozen contract is unchanged.

## M7 fixed validation and corrections

The artifact protocol was saved before collection:256 batches,16 points, reserved
master_seed 1312221634. Failure boundaries were listed before writing the checks:
wrong sample budget, adaptive stopping, bit-level rather than batch variance,
loss of u64 moments, wrong multiplicity family, sparse automatic approval,
and mismatched result fingerprints/counters. Unit checks compare aggregate
inference to retained raw batch observations through SciPy's independent APIs.

make validate completed all 12 real processes, 49,152 batches total. No incompatible
case was found among 128 theory checks and 96 language-pair checks. The 32 AWGN cases
at 16–30 dB are evidence_insufficient, not approved, and not resampled after seeing
results. Full point approval is explicitly false. Raw data/protocol/results are
in results/validation-20260930T234334-97147; Portuguese tables/report share that
run id under report/. All 96 main-profile comparisons are compatible at the
predeclared family criterion; this is not an equivalence conclusion.

All four versions now emit an exclusive phase marker outside work. Memory uses
the first sample after that marker, a peak restricted to post-warmup samples,
and the 600-second deadline starts after warmup. A separate 90-second warmup guard
reports failure rather than accepting it as a normal memory timeout. Sampled CPU
progress is retained; smoke checks actual work duration and progress. Ten-minute
memory stability remains an M9 measurement, not a smoke claim.

Result checks now enforce exact perf/stages batch budgets and consistency of
batch-square moments. Full performance suites compute CV after ten processes;
if any arm exceeds 5%, all language arms repeat with ten fresh processes, retaining
all original observations. Remaining noise is reported, never silently removed.
A separate explicit TURBO=on mode enforces turbo-on metadata. A 12-CPU run is
informative and excluded from E-core efficiency. None has been measured yet.

Analysis now uses payload divided by median work time consistently, 95% bootstrap
ratio intervals against C++ and the E-core serial baseline, and real post-warmup
memory deltas. Single-process smoke still receives no invented bootstrap interval.
No optimization round or calibration was performed; perf.n_batches stays null.

## M7 closure and review

make golden, make test (29 tests in 296.658 seconds), and make validate passed.
A fresh independent read-only Luna explorer confirmed the fixed sampling unit,
families, Welch degrees of freedom, sparse-point nonapproval, phase markers,
real memory baseline, and bootstrap estimators, with no blocking finding.
Ruff, Rust formatting, and Clippy with warnings denied passed. The strengthened
result guards were rechecked on all 32 completed real smoke executions and the
retained validation observations. No contract value or dependency changed.

The full-only CV/turbo/12-CPU paths and ten-minute memory stability will receive
real measured evidence in M9; smoke is not that evidence. M8 profiling is next.
The required perf executable is absent and the matching system tools are not
installed. The plan's user-action stop condition applies to their sudo install.

## M8 profiling, calibration, and measured budget

One profiler round per language is retained at
results/profiling-20261001T002110-111626, with derived 4,096-batch config,
environment, actual command arrays, stdout/stderr, raw profiles and counters.
Native rounds use perf 7.1.5 cpu-clock:u at 99 Hz with DWARF stacks; Python uses
isolated uvx py-spy 0.4.2 native/subprocess stacks; Julia uses stdlib Profile.
A profiler preflight sampled /usr/bin/true, without an OFDM workload. It is not
a second implementation profiling round. Per-language findings and deliberate
lecture ceilings are logged in each implementation's NOTES.md. The Python
shutdown error is preserved with complete sampled data and simulator output;
no rerun was used to hide it. No unlisted dependency or lockfile was changed.

The existing E2E passed 29 checks in 292.222 seconds after optimization. Retained
before/after integer counters match in 64 real records, including 4,096-batch
perf loads for all four languages. Golden intermediate signals remain checked
against the independent oracle, not against another implementation. Neither
instrumented timings nor one unprofiled observation establish an optimization
speedup. The comparison regenerates with the retained verify_numeric.py.

Calibration used one C++ worker on CPU 2 after other test workloads completed.
The first candidate, 2,048 batches, measured work_s=8.856117789 with turbo on.
The raw config/result, command, environment and frozen fingerprint are under
results/profiling-20261001T002110-111626/calibration. This exceeds the required
5 seconds. Only perf.n_batches changes from null to 2048 in the contract; all
physical values, schemas, golden vectors, seeds and numeric tolerances remain
unchanged. This is the M8 calibration explicitly required by the plan, not a
contract deviation. Primary measurements still require turbo off.

The post-freeze contract suite exposed a pre-calibration test that depended on
the live profile retaining null. Its fixture now explicitly sets null before
checking that boundary, then checks the calibrated and diagnostic-CSI cases.
No production validation was weakened. All 18 contract checks pass in 2.793 s.
Ruff also found an existing import-order issue in that test; imports were sorted.
Ruff, Rust formatting/Clippy with warnings denied, make doctor and make golden
pass. The FFT interposition probe directly observes one plan per direction in
101 transform calls for the installed IT++ binary; absent CPU samples alone
would not prove that lifetime.

### Budget before M9

The retained machine-estimate.json records the extrapolation and its inputs:
M6 smoke results/20260930T232731-91208 for single/scaling/stages timings,
M7 phase-marked smoke results/20260930T235156-99613 for memory startup, and
M8 calibration for the frozen batch count. Work scales by 2048/4; observed
non-work launch time is retained. The unmeasured mixed 12-CPU arm uses the
8-worker time only as a budget proxy, never as measured mixed-core performance.

Required primary single/scaling/memory suites project 227 minutes: 280 fresh
perf processes, eight 600-second memory windows, 96 minutes of cooldown, and
about 51 minutes of projected process work/setup. Supplementary full stages
project 15 minutes. Primary plus stages therefore projects 242 minutes.
If every CV arm triggers its one retained repeat, the required primary suites
project 371 minutes before supplementary stages. A turbo-on single suite adds
44 projected minutes without noise repeats. Fixed-budget M8 validation supplies
the quality curves; it is not a performance suite or adaptive stopping evidence.

These are planning estimates, not runtime upper bounds. Four-batch smoke has
large scheduling noise; extrapolation may overstate it. Turbo-off frequencies,
thermal behavior and CV repeats can increase time. Reporting/ergonomics work
is additional. No primary timing, ten-minute memory outcome or final ranking
is claimed before M9. Continue the milestone loop without requesting a budget.

### M8 statistical acceptance

make validate collected a new independent run at
results/validation-20261001T003344-116836 using the unchanged predeclared protocol:
12 processes, 49,152 fixed batches, 128 simultaneous theory checks and 96 Welch
pair comparisons. It found zero incompatible cases and retained 32 sparse AWGN
points as evidence_insufficient. No sample-size increase or point approval was
made. The corresponding Portuguese report regenerated successfully. The earlier
M7 run remains available; outcomes are not substituted or pooled after inspection.

### M8 review cycle 1 and provenance correction

Fresh read-only Luna review found no blocker and three stale calibration texts:
contract/config.schema.json's description, contract/README.md, and tools/NOTES.md.
They now describe the frozen 2048-batch profile and retain null only for derived
uncalibrated inputs. Only descriptive schema text changed; validation constraints,
numeric fields and tolerances did not. The Julia profiler wrapper will be staged.

A local audit found that manual profiler/calibration launchers had not pinned
themselves to CPU 0, although every simulator/profiler command pins CPU 2.
Their common environment record incorrectly claimed orchestrator_cpu=0. The
original records are preserved with metadata-corrections.json in the profiling
and calibration directories, explicitly marking the original launcher affinity
as unrecorded. This is a provenance deviation for diagnostic profiling/calibration,
not an accepted primary run. No profiler round was repeated.

The already frozen 2048-batch C++ workload was then verified with an explicitly
CPU-0-pinned launcher and CPU-2-pinned simulator. It measured 7.842908383 seconds,
still above five, and retained its raw config fingerprint, result, environment,
command and assertion artifact under calibration/pinned-verification.*. The
workload count did not change. Full benchmark orchestration pins CPU 0 before
launching any simulator. Recomputed fixed-budget validation from the retained
M8 observations and the golden/contract checks pass after these documentation
corrections; no statistical data were recollected or pooled after outcomes.

### M8 review cycle 2 and closure

A second fresh read-only Luna explorer review found no blocking finding or
unresolved correction. It verified the post-freeze contract/golden/validation
artifacts, one-round profile budget, unchanged numeric counters, pinned workload
verification and explicit provenance corrections. It executed no new profiling
or primary measurement. M8 closes on main with one feat(m8) commit. M9 requires
the human-only no_turbo write when its current value is zero; no primary suite
is launched with turbo on.

## M9 lecture protocol revision before collection

The user asked to continue in the current state after the turbo-off stop.
The lecture collection therefore keeps no_turbo=0 and uses the existing
explicit TURBO=on option. No system setting or scientific contract is changed.
The original turbo-off primary guard remains intact; measurement=turbo_check
is the existing internal label, and the report will identify this as the full
turbo-on lecture collection. No unobserved turbo-off result or turbo effect is
inferred. This decision is recorded before any M9 process or performance result.

The single combined command is make bench SUITE=single,scaling,memory,stages
TURBO=on. It retains ten fresh processes per perf/stage configuration, random
language order, twenty-second cooldown, homogeneous E-core scaling, the separate
12-CPU informative arm, eight ten-minute work-only memory windows, and complete
CV-triggered repeats with original processes retained. The contract's 2048-batch
load, independent numerical validation, build flags and profiler budget stay
frozen. The measured-input estimate is 242 minutes before CV repeats; the extra
turbo confirmation run is unnecessary because this collection already uses turbo.

## Code-only scope correction and implementation validation

The user explicitly prohibited experimental execution after the initial M9
start, restricting the task to writing code and assuring validity. The collection
was stopped immediately after seven completed processes. Run
results/20261001T010257-124574 is retained with completed=false,
interrupted_by_user=true and an explicit reason. No remaining simulator/capture
process for that run exists. No new performance outcome or complete comparison
is claimed; M9 measurement and the scientific M10 report are deferred.

make check provides short builds, contract/inference checks, all four real golden
CLIs, planning-only acceptance and report-boundary regression checks. It does not
call make bench, the smoke harness, profiling or simulation-based validate.
The existing complete experimental tests remain available for a future explicitly
authorized run; they are not disabled. make bench-plan / --dry-run validates the
configuration and planned geometry without probing hardware or launching tools.
Execution and preview share CPU-position selection. Planning acceptance poisons
PATH with executable sentinels, verifies none was called, and retains plan.json.
Duplicate/unknown suite selections are rejected. The full preview schedules
328 baseline processes and up to 320 repeats; no observed work time is emitted.
The first plan test incorrectly expected 32 total groups (the noise-checked count)
instead of 40 including eight memory groups; corrected from the plan's geometry.

Report acceptance first reproduced that a stale config fingerprint could reach
plotting. The generator now uses common.read_results, verifies homogeneous
configuration fingerprints before pooling and comparing languages, and rejects
incomplete runs before output. Invalid-input fixtures include internally valid
but different loads, not simulated/observed measurements; they never produce
figures. Isolated stages and adaptive BER do not receive payload throughput or
performance ratios. The batch variance numerator now uses exact integer moments
before division, matching the already validated statistical formula. Turbo state
and the existing internal turbo_check label are described explicitly in reports.

make check passed 27 short checks, including four real golden CLI subcases,
without any comparative collection. Logs: results/code-check-final.log. No
contract value, numerical tolerance, lockfile, RNG or DSP algorithm changed.

### Code-only review cycle 1

Fresh read-only Luna review found no blocker and a publication gap: a plotting
failure could leave a newly written summary alongside an incomplete report.
A regression case was written before the correction. Report rendering now uses
a temporary directory; complete assets are promoted only after successful
rendering, and the previous report is restored if promotion fails. A render
failure leaves the prior report intact. No measurement was executed to test it.

Local review also found a residual C++ self-ratio interval on repeated stage
records even when their ratio was inapplicable. The phase-field regression now
verifies absent throughput/ratio/ratio-interval fields before trapping fixture
plotting; no fixture figures are published. The condition is fixed. Further
boundary cases reject differing scaling loads and stale source commits against
the collection environment before any output. All fixtures are expressly parser
inputs, not empirical measurements. Their contract-shaped counters only exercise
trust boundaries and phase semantics.

The complete make check passes 31 short tests (18 contract, 3 inference,
2 non-executing planning, 1 four-language golden, 7 analysis boundaries).
Evidence: results/code-check-complete.log. Ruff passes. The original contract,
lockfiles and DSP implementations remain unchanged; no comparative collection
has run since cancellation. A fresh final read-only review precedes the
user-authorized code preparation commit.

### Final code preparation checks

A fresh second review accepted the report publication correction and found no
remaining issue. The public Make preview default was then independently checked:
GNU Make split the literal comma-separated fallback into separate or() arguments,
leaving only single. A regression using make -n was written first; a target-local
SUITE default now preserves all four suites. The preview explicitly identifies
its representative command as the first repetition. Finally, a matching hash
must not legitimize invalid geometry: analysis now calls the existing full
configuration validator before the strict result validator; its regression
mutates N_fft and recomputes the fixture hash, then requires rejection.

make check passes 33 short checks (18 contract, 3 inference, 3 planning,
1 four-language golden and 8 report boundaries), recorded in
results/code-check-ready.log. Ruff and git diff --check pass. No experiment was
executed. Final focused fresh review covers the two last corrections before the
single authorized code-preparation commit. Physical M9/M10 acceptance remains
explicitly deferred.

### Final read-only review and closure

Fresh focused final review found no blocking or nonblocking issue in the last
Make preview and full-config-validation corrections. It executed no experiment
or prohibited test. The user-authorized commit closes code preparation only;
it does not claim completion of M9 measurements or the M10 scientific report.
No automatic resumption or scheduled experimental execution is created.
