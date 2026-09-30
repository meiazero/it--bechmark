# Session state: M6 complete; M7 next

Updated September 30, 2026. The active request continues pending milestones for
an optimization and telecommunications lecture. M0–M6 are implemented on main;
there is no configured remote. M5 is commit43f7cf4. M6 adds the real-process
harness, retained environment/raw/cgroup/RSS evidence, all five smoke suites,
and generated Portuguese CSV/PNG/SVG lecture artifacts.

M5 passed make golden, make test (25 tests) and a fresh independent explorer
review. M6 passed make bench SUITE=smoke, make analyze, make test (26 tests),
and a final strengthened real E2E in149.491s. Final smoke run:
results/20260930T232731-91208,40executions. Report:
report/20260930T232731-91208. M6 required review corrections for Portuguese
presentation and missing-data behavior; the final fresh Luna review approved it.
Detailed evidence and review cycles remain in bench/NOTES.md and local logs.

The frozen contract and golden values are unchanged. perf.n_batches remains
null. All implementations use retained taps for isolated channel_conv timing.
No simulator/theory statistical validation, profiler round, calibration,
complete benchmark or final report has yet been completed. Smoke is unpublishable.

M7 must specify fixed independent collection before observing outcomes,
validate theory/compatibility, and replace estimated post-warmup RSS deltas
with an explicit phase boundary. Other Phase2 harness work is listed in NOTES.
M8 owns one profiler round per language, then calibration. M9 requires measured
machine-time estimate, primary turbo-off data and the full control protocol.

The shell omits existing user bus variables; the harness supplies them from
/run/user/1000/bus without starting a service. AC is online; turbo is on and
its sysfs file is root-owned. perf is not installed; apt has matching kernel
tools available. Recheck at M8 and obey the user-action stop condition.
No system package, governor, turbo setting or persistent PATH was changed.
Dependencies remain within the plan, retained in project lockfiles.

Activate tools with eval "$(mise env -s bash)" before make in noninteractive
Bash. Continue acceptance, fresh read-only explorer review, correction and one
commit per milestone. No stubs or disabled tests; no performance claim from smoke.
