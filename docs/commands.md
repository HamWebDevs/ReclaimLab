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

All outputs are UTF-8, created with restrictive permissions where supported, and never overwrite an existing path. Exit codes: 0 completed, 1 a configured HAR budget failed or could not be verified, 2 invalid input/tool error, 130 interrupted. No network requests are made by the application. Normal Python/package installation may use a package registry for build tools.

## Browser network captures

```bash
reclaimlab har artifacts/page.har --output network.html
reclaimlab har artifacts/page.har --max-body-kib 1024 --max-wait-p95-ms 800 --max-errors 0 --json
reclaimlab har artifacts/pages.har --page 2 --include-paths --output named-network.html
reclaimlab har-demo --output synthetic-network.html
```

HAR 1.2 inputs are read offline; no requests are replayed. Aliases are the default; origin/path labels require opt-in. Budget units, pass/fail/unknown behavior, page scoping, discarded fields and interpretation are documented in the [browser network guide](browser-network.md).

## Repeated studies

```bash
reclaimlab plan --workload "same browser task" --candidate "Lower video resolution" --pairs 6 --seed 42 --output trial/study.json
reclaimlab next trial/study.json --json
reclaimlab next trial/study.json --record
reclaimlab study trial/study.json --iterations 2000 --output study.html --json
reclaimlab study-demo --directory synthetic-study --output synthetic-study.html
```

`plan` defaults to six pairs, 60 seconds per capture, a 0.5-second native interval and order seed 0. It accepts 2–20 pairs, 20–3,600 seconds and 0.2–10 seconds between native samples. `--title`, `--baseline` and `--candidate` describe the protocol; `--workload` is required. Descriptions are limited to 200 characters.

`next` only inspects existing files and shows the next condition. Apply that condition yourself before using `--record`; recording starts immediately with that flag. Existing captures are never overwritten. `study` accepts 500–10,000 bootstrap iterations, default 2,000, with separate analysis seed 0. A completed audit can return a not-comparable result with exit 0; inspect its verdict or use the DevPocket plugin's quality gates. [Full protocol and statistical limits](studies.md).
