# Methodology and interpretation

[Back to ReclaimLab](../README.md)

## A scheduling probe, not a stopwatch for the UI

A separate Python thread waits about 50 ms at a time and records how late it wakes relative to the requested wait. It does not change OS timer resolution or busy-spin. Lateness can reflect scheduler contention, timer granularity, Python/GIL behaviour, virtualisation and the observer itself. It is not a direct measurement of keyboard-to-display latency, frame pacing, audio glitches or application responsiveness.

The native collector runs at a lower configurable rate. Each record stores the actual counter delta interval, raw wake-delay observations, counter values, collector wall time and optional top process evidence. Delay events are located only to the native sample interval. Nearby delayed records are grouped into episodes.

Summaries calculate wake percentiles from the recorded wake observations, not by averaging per-record percentiles. Resource averages use duration weights and omit unavailable values. Counter coverage reports the proportion of selected duration with a known value. Counter resets and PID reuse do not become giant positive rates.

## Evidence rules

Thresholds are transparent heuristics for investigation, not trained probabilities:

- CPU overlap: at least one delayed record with CPU activity >=85%. Linux CPU PSI >=10% adds corroborating evidence.
- Memory overlap: delayed records with <=10% immediately available physical memory plus memory PSI >=5% or combined swap traffic >=1 MiB/s. Low headroom without that evidence is labelled limited.
- Storage overlap: delayed records with measured device busy time >=85% plus I/O PSI >=10% or CPU iowait >=15%.
- Thermal counter evidence: growth in an available CPU throttle counter. Temperature >=90 C in at least two records without counter growth is labelled exposure, not confirmed throttling.
- Unexplained delay: wake delays cross the chosen threshold without matching the implemented resource rules.

"Strong overlap" means at least three qualifying records with corroboration under that rule. It is not a quantified confidence score or proof of cause. Multiple rules can match the same period. A high resource reading without delayed records is not automatically diagnosed as a responsiveness bottleneck.

## Observer and capture quality

Footer data records total process CPU time (including the heartbeat thread). CPU time divided by elapsed time is reported as a percentage of one logical core, not whole-machine utilisation. Above 5% is flagged. Collector p95 wall time above 15% of the requested sample interval is also flagged, as are sampling gaps over three intervals, short captures, dropped wake observations and incomplete captures.

Collection time can include scheduler delays; it is not identical to CPU overhead. Optional process enumeration can materially increase both. Capture real-workload overhead on the target laptop rather than assuming a benchmark from another machine applies.

The heartbeat queue is bounded. If a very unusual capture gap overflows it, observations are dropped and the footer records the loss. Comparisons refuse a verdict when samples were dropped. Chart downsampling preserves bucket endpoints and extrema, while evidence/statistics use original selected records.

## Before/after comparisons

The primary metric is the difference in p95 timer wake delay, after minus before. The tool groups observations into occupied one-second buckets and resamples whole buckets independently within each capture, preserving short-range dependence within each bucket. Percentiles of the resampled differences form a descriptive 95% block-bootstrap interval.

A directional verdict requires an interval wholly on one side of zero and an observed change of at least the larger of 5 ms or 15% of the initial p95. Otherwise the result is inconclusive. Captures need at least 20 occupied buckets and 200 wake observations each, at least 20 seconds of observed intervals, duration ratio <=1.5, comparable native and heartbeat intervals (within 5%), matching backend/process instrumentation and a matching coarse platform/hardware signature. Incomplete/error captures, dropped observations, excessive recorder CPU overhead, known power-source differences and different declared workloads block a verdict.

Changes over 15 percentage points in average CPU activity or memory headroom are flagged as context: they can be the mechanism of an improvement or a confounding workload change. Unknown power state is reported, not silently treated as AC. Matching signatures do not establish physical machine identity. Sampling gaps and other quality warnings remain visible.

This is a non-randomised observational comparison. The interval is not a guarantee of coverage, a p-value, or proof a tweak caused a change. One-second blocks do not remove long-range dependence. Keep the task, power source, interval, duration and thermal starting conditions similar; change one thing; repeat. For multiple runs, ReclaimLab 0.2 adds [balanced crossover studies](studies.md), with protocol consistency checks and a separate bootstrap whose resampling unit is a whole paired run.

No recommendation automatically applies a system change or promises an upgrade will pay off. Use evidence to choose the next experiment, not to justify deleting random files or disabling security features.
