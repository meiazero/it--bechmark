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
results/20260930T232731-91208 with40 executions; generated artifacts are under
report/20260930T232731-91208. A fresh final read-only Luna explorer review found
no blocker and no additional nonblocking finding beyond the recorded Phase2
work. Ruff passed. The frozen contract is unchanged.
