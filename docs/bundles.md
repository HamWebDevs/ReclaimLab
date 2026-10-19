# Portable measurement bundles

[Back to ReclaimLab](../README.md) · [Network experiments](network-studies.md) · [v1 contracts](compatibility.md)

A `.rlb` bundle is one bounded, measurement-only archive for a repeated browser experiment. It lets a teammate or CI job verify and reanalyse the selected HTTP evidence without receiving the original HARs. It includes a format-v1 protocol, allowlisted measurements, a frozen analysis snapshot and per-file SHA-256 checksums. It includes no executable content or archived HTML.

```bash
reclaimlab bundle create trial/network-study.json --max-growth 0 --output experiment.rlb
reclaimlab bundle verify experiment.rlb --json
reclaimlab bundle verify experiment.rlb --output verified-experiment.html
```

The verifier checks the archive, member inventory, byte counts, checksums and canonical measurement fields, then reanalyses the complete paired experiment. Stored analysis must match fresh reanalysis. HTML output is generated afresh from verified data; the archive is never extracted or executed. A new report shows the archive digest and integrity state along with the pair audit and growth gate.

Try the workflow without collecting data:

```bash
reclaimlab network-study-demo --directory demo-trial --output demo-trial.html
reclaimlab bundle create demo-trial/network-study.json --max-growth 0 --output demo.rlb
reclaimlab bundle verify demo.rlb --output verified-demo.html
```

## What is retained or withheld

| Retained measurement | Withheld source material |
| --- | --- |
| Request/origin grouping, selected resource kinds and standard HTTP methods | Original hosts, paths, queries, fragments, URL credentials and nonstandard method labels |
| Numeric statuses, known/unknown sizes, durations and phase timings | Headers, cookies, request/response bodies and unrecognized HAR fields |
| Relative request timing, capture order, gaps and overlap | Original absolute dates; all captures receive one common shift anchored at 2000-01-01 |
| Browser-consistency groups and synthetic flags | Actual browser names/versions and export metadata |
| Primary metric, paired schedule, seeds and gate policy | User-written titles, workload/build/condition descriptions, context declarations, original pair IDs and filenames |

The selected scope becomes one canonical page per bundled HAR. Aliases and generic descriptions are explicit in the verified report. Unknowns stay unknown. HTTP failures, reused measurements, order/coverage problems, synthetic mixing and other audit blockers remain blockers. Before writing a bundle, the exporter verifies that the transformation preserves the source experiment's metric summaries, pair audit, uncertainty and gate result; otherwise it refuses the export.

Every source capture must be a regular parseable HAR. Missing/malformed exports cannot be packaged into a complete bundle, although normal network-study analysis retains them in its audit. Incomplete numeric coverage and other parseable incompatible evidence can be packaged for review; they still cannot pass verification gates.

Measurements, timing patterns and file sizes can remain identifying. Withholding fields is not anonymization against reidentification. SHA-256 and reanalysis detect internal inconsistencies, not authorship or provenance: someone can create new internally consistent data and checksums. Bundles do not authenticate captures, bind a build/revision or establish causality. Keep a separately trusted archive digest if you need to recognize an exact artifact.

## Budgets and exit status

`create` freezes `--iterations` (500–10,000), `--seed` and optional `--max-growth` in the analysis snapshot. Creation returns 0 when a complete archive is written; that alone does not mean its experiment passed a gate.

`verify` returns **0** for a comparable descriptive analysis without a budget or a passing configured gate, **1** for incompatible/insufficient evidence or an unknown/failed gate, **2** for malformed archives, failed integrity/reanalysis, invalid options or output/resource errors. Interruption is 130. `verify --max-growth AMOUNT` first verifies the stored snapshot, then applies that fresh budget without changing the archive. Units come from the frozen primary metric.

```bash
reclaimlab bundle verify experiment.rlb --max-growth 25 --json
```

## Bounds and format stability

Limits: 64 MiB archive bytes, 128 MiB total uncompressed contents, 44 regular members, 32 MiB per HAR, 2 MiB stored analysis and 256 KiB other metadata. Original selected request timestamps must fit within a 31-day experiment window. Normal HAR/page/origin/request, study-pair and bootstrap limits also apply. Duplicate names/JSON keys, traversal, symlink/special-file metadata, encrypted/unsupported compression, unexpected members and leading/trailing ZIP data are refused. Writes are exclusive; no existing archive or report is replaced.

Format v1 has `bundle.json`, `network-study.json`, `analysis.json`, `README.txt` and `captures/pNN-baseline.har` / `captures/pNN-candidate.har`. All JSON is canonical compact ASCII JSON. ZIP member timestamps are fixed; the exporter is byte-reproducible for identical inputs/options with the same Python/compression runtime. Different compression implementations can produce different archive hashes while preserving measurements.

`analysis.json` stores a fixed evidence contract instead of a presentation report, so additive display/report fields do not invalidate format v1. An analysis correction that changes frozen evidence causes an explicit reanalysis mismatch; the verifier never silently certifies a different result. A committed frozen format-v1 fixture checks reader compatibility independently of the current exporter.

## DevPocket and CI

Install both repositories and enable `reclaimlab-bundle` explicitly:

```json
{
  "version": 1,
  "plugins": ["reclaimlab-bundle"],
  "checks": {
    "portable-experiment": {
      "tool": "reclaimlab-bundle",
      "input": {"bundle": "artifacts/experiment.rlb", "max_growth": 0},
      "cache": {"inputs": ["artifacts/experiment.rlb"]}
    }
  }
}
```

One bundle file is the complete declared file input. Successful verified results can be cached when the file, parameters, runtime and tool source are unchanged; failed verification/gates are not cached. Direct runs and MCP calls remain uncached. An incompatible/failed/unknown result has a nonzero operational code, so a baseline or `--fail-on none` cannot turn it into success. Explicitly allowed failures remain DevPocket project policy.

The plugin is read-only, uses SDK API v1 and can be exposed over MCP with `--plugin reclaimlab-bundle` after project enablement. DevPocket's [GitHub Action](https://github.com/HamWebDevs/DevPocket/blob/v1/docs/github-action.md) can install the optional plugin using a reviewed requirements file and collect the combined JSON/SARIF artifacts.
