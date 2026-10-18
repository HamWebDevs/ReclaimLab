# Commands

[Back to ReclaimLab](../README.md)

## Capture

`reclaimlab record --output trace.jsonl`

| Option | Default | Meaning |
| --- | --- | --- |
| `--seconds` | 60 | Wall-clock capture budget, 2–3,600 seconds. |
| `--interval` | 0.5 | Native-counter interval, 0.2–10 seconds; actual deltas use observed clock time. |
| `--label` | Laptop capture | Report title, up to 200 characters. |
| `--workload` | Empty | Description of the repeated task; a mismatch blocks an experiment verdict when both are declared. |
| `--processes` | Off | Opt in to names, PIDs, per-process CPU and RSS when accessible. No command lines. |
| `--interactive` | Off | Type a short label and Enter to add a marker; `quit` finishes. |

Ctrl+C finalises an interrupted trace where possible and returns 130. Collector failures retain an error-marked footer where possible, then return a tool error. An incomplete trace can still be analysed if it has usable complete samples, but cannot support a comparison verdict. A power failure can leave truncated JSON, which is rejected rather than guessed at.

The tool reads counters and writes only the requested output. It does not change services, startup items, power plans, registry values, priorities, swap settings, timer resolution or device settings.

## Analyse and report

```bash
reclaimlab analyze trace.jsonl --json
reclaimlab analyze trace.jsonl --window 10:30
reclaimlab analyze trace.jsonl --around "video froze" --radius 5
reclaimlab report trace.jsonl --output report.html
```

`--threshold` defaults to 50 ms and accepts 5–5,000 ms. It controls which timer observations are labelled delayed; it is not a universal perceptual threshold. `--radius` accepts 0.1–600 seconds. Marker matching is exact and case-sensitive, selecting the first matching label. Windows select whole sample records whose endpoints fall in the range; observations inside a record are not individually timestamped. Around-marker selection takes precedence over an explicit window if both are supplied.

The report's sliders zoom already plotted data. They do not recompute the evidence or summary cards. Use the analysis command for selected-window statistics.

## Compare

```bash
reclaimlab compare before.jsonl after.jsonl --json
reclaimlab compare before.jsonl after.jsonl --iterations 500 --output experiment.html
```

`--iterations` accepts 50–2,000; the default is 300 with deterministic seed 0. A completed comparison, including a not-comparable result, returns 0. Inspect its verdict and incompatibility reasons rather than treating exit 0 as an improvement. The HTML timeline is the first capture; the experiment tab compares both summaries.

## Demonstration and capabilities

```bash
reclaimlab demo --output demo.html --trace-output synthetic.jsonl
reclaimlab doctor
```

The demonstration is synthetic and labelled accordingly. `doctor` probes the live backend; it fails clearly on platforms without a capture backend. Offline analysis/report/demo commands work there.

All outputs are UTF-8, created with restrictive permissions where supported, and never overwrite an existing path. Exit codes: 0 completed, 2 invalid input/tool error, 130 interrupted. No network requests are made by the application. Normal Python/package installation may use a package registry for build tools.
