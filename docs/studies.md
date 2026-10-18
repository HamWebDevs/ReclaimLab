# Repeated crossover studies

[Back to ReclaimLab](../README.md) · [Commands](commands.md) · [Methodology](methodology.md) · [DevPocket](devpocket.md)

A single before/after comparison can reflect warm-up, cooling, background work or ordinary variation. ReclaimLab 0.2 records a protocol, alternates the condition captured first across pairs and gives each complete pair equal weight in a repeated-run analysis. It guides recording without applying system changes.

## Plan before collecting

```bash
reclaimlab plan --title "Browser playback experiment" --workload "Replay the same local video" --baseline "Original resolution" --candidate "Lower resolution" --pairs 6 --seconds 60 --seed 42 --output trial/study.json
reclaimlab next trial/study.json
```

The JSON manifest records two condition descriptions, task, duration, interval, seed, unique capture paths and planned order. `--pairs` accepts 2–20; a directional assessment requires at least four complete pairs and both capture orders. Six or more pairs are preferable. Half the default pairs are baseline-first and half candidate-first, shuffled with the chosen seed. Odd pair counts differ in order counts by at most one. The manifest and captures stay under the selected manifest directory.

Inspect the next condition, apply it yourself, then start a capture:

```bash
reclaimlab next trial/study.json --record
```

Reproduce the same task during each recording. Use the same power source, keep background work comparable and allow consistent warm-up/cooling between runs. Repeat `next`, apply the displayed condition and use `--record` until all captures exist. The `next` command alone is read-only; `--record` reads native counters and writes the selected fresh trace. No condition description is executed as a command, and no setting is changed automatically.

The recorder stamps the protocol SHA-256, pair ID and condition into the trace header. Formatting the JSON differently does not change its canonical digest; changing the plan does. Keep the protocol fixed once recording starts. Existing files are never overwritten. An interrupted/error capture or mismatched protocol needs your review and a fresh capture path or a new study, rather than silent reuse.

## Audit and report

```bash
reclaimlab study trial/study.json --output study.html
reclaimlab study trial/study.json --iterations 2000 --seed 0 --json
```

The report keeps every planned pair visible. It shows baseline/candidate p95 values, paired differences, compatible-pair counts, order-specific mean changes, blockers, context, sample digests and protocol binding. Switch between changes and paired values, hover the chart or filter the audit to pairs needing attention. All imported text is inert and the report works offline.

Pair compatibility inherits the ordinary comparison gates: platform/coarse hardware, collector/process instrumentation, sampling/heartbeat settings, duration, known power source, workload, completeness, dropped observations and observer CPU overhead. A study additionally checks:

- All runs use the plan's workload and approximately its duration (80–125%) and native interval (within 5%). Collector/instrumentation settings must also remain identical across the study.
- Known hardware and power-source states remain comparable across pairs. Matching coarse hardware does not prove physical machine identity.
- Timezone-aware capture-start timestamps follow the whole planned schedule without overlapping captures, allowing 0.5 seconds of timestamp tolerance.
- Protocol/pair/condition stamps match when present. Legacy/manual captures without stamps remain explicitly unbound context.
- Exact recorded sample payloads are not reused as new runs, even if headers were relabelled. This detects copied observations, not fabricated data.
- Sampling gaps stay below three intervals and collector p95 wall time stays at or below 15% of the native interval.

Any invalid/missing/incompatible pair blocks an aggregate interval and verdict; it is never silently dropped to improve the result. Available compatible-pair summaries remain visible for investigation. Manifests are bounded to 256 KiB and the study's declared trace sizes to 128 MiB combined. Paths must be relative, below the manifest directory and free of symlinks.

## What is resampled

For each compatible pair, calculate **candidate p95 minus baseline p95** from each run's raw timer observations. The study's statistic is the arithmetic mean of those paired differences. It is not a percentile of pooled runs or a weighted mean of all timer observations. A long or densely sampled run does not become many independent experiments.

With no blockers, a seeded paired bootstrap resamples whole paired differences with replacement, keeping the original number of pairs. The 2.5th and 97.5th percentiles of the simulated mean differences form a **descriptive 95% interval**. The default is 2,000 iterations; accepted range 500–10,000. Seed 0 makes repeated analysis reproducible. The bootstrap does not force each resample to retain the original capture-order counts.

A directional verdict requires the whole interval on one side of zero, a mean change at least the larger of 5 ms or 15% of the mean baseline p95, and at least 75% of pairs changing in that direction. Otherwise it is inconclusive. If the two capture-order groups have opposite-signed mean changes separated by at least that material threshold, the report flags an order effect and withholds direction.

This is not a p-value, a guarantee of confidence coverage, measured GUI input lag or proof that the selected change caused anything. Few runs, carryover, slow thermal drift, mistaken workload labels and dependence between pairs remain limitations. Balanced order and stamps improve consistency checking; they do not authenticate a protocol or establish preregistration. Repeat on the actual workload and inspect all evidence before drawing a practical conclusion.

## Try the complete flow

```bash
reclaimlab study-demo --directory synthetic-study --output synthetic-study.html
```

This writes a fresh manifest, twelve synthetic captures and an offline report. The entire example is labelled synthetic and makes no real performance claim.
