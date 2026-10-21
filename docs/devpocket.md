# DevPocket integration

ReclaimLab 1.2 adds the seventh read-only plugin, `reclaimlab-har-assets`, for per-request asset-size/duration rankings and coverage-aware budgets. [Measurement scope, policies and complete-input caching](har-assets.md).

ReclaimLab 1.1 adds `reclaimlab-har-compare` for descriptive differences between two saved captures. [Comparison, privacy and complete-input caching](har-comparison.md). ReclaimLab 1.0 added `reclaimlab-bundle`. It verifies and reanalyses a portable `.rlb` artifact entirely in memory and supports complete-input caching with just that file. [Configuration and CI example](bundles.md#devpocket-and-ci). Existing trace/study/HAR/network-study names remain unchanged. Installed integration checks use DevPocket 1.x and verify all seven plugins, preflight, cached invalidation, workspace reports and MCP.

[Back to ReclaimLab](../README.md)

ReclaimLab publishes `reclaimlab`, `reclaimlab-study`, `reclaimlab-har`, `reclaimlab-network-study`, `reclaimlab-bundle`, `reclaimlab-har-compare` and `reclaimlab-har-assets` entry points in the `devpocket.tools` group. Standalone use does not import or require DevPocket. All seven use API v1 and omit optional cache fields on older API v1 hosts. AssetGuard requires DevPocket 0.5+; workspace orchestration requires 0.6+; the combined verification script uses DevPocket 1.x configuration preflight.

Install both repositories in the same environment. DevPocket is not assumed to exist on PyPI:

```bash
python -m pip install "git+https://github.com/HamWebDevs/DevPocket.git"
python -m pip install .
devpocket plugins list
devpocket plugins enable reclaimlab
devpocket plugins enable reclaimlab-study
devpocket plugins enable reclaimlab-har
devpocket plugins enable reclaimlab-network-study
devpocket plugins enable reclaimlab-bundle
devpocket plugins enable reclaimlab-har-compare
devpocket plugins enable reclaimlab-har-assets
```

From the project containing a saved trace:

```bash
devpocket run reclaimlab --input '{"trace":"before.jsonl"}' --format json
devpocket run reclaimlab --input '{"trace":"before.jsonl"}' --format sarif
devpocket run reclaimlab-study --input '{"manifest":"trial/study.json"}' --format json
devpocket run reclaimlab-har-compare --input '{"before":"before.har","after":"after.har"}' --format json
devpocket run reclaimlab-har-assets --input '{"capture":"artifacts/page.har","max_asset_kib":256}' --format sarif
devpocket run reclaimlab-har --input '{"capture":"artifacts/page.har","max_errors":0}' --format sarif
devpocket run reclaimlab-network-study --input '{"manifest":"trial/network-study.json","max_growth":0}' --format sarif
```

The plugin resolves the trace under the project's root, analyses it and returns warning findings plus the complete structured summary. Warnings deliberately return gate status 1 by default. Use DevPocket's normal baseline/severity controls to choose your gate policy. There are no automatic recordings, settings changes or uploads.

Add a project check:

```json
{
  "version": 1,
  "plugins": ["reclaimlab"],
  "checks": {
    "laptop-evidence": {
      "tool": "reclaimlab",
      "input": {"trace": "before.jsonl"}
    }
  }
}
```

For an MCP client, explicitly expose the enabled read-only plugin:

```bash
devpocket serve --root /absolute/path/to/project --plugin reclaimlab --plugin reclaimlab-study
```

Enabling an installed Python plugin is a trust decision. ReclaimLab's adapter only reads a selected trace, but the SDK's read-only declaration is not a sandbox. Reports can include labels and optional process names; the client controls subsequent model or network handling of returned data.

## Repeated-study gates and caching

The study plugin returns an error-severity finding for consistently higher measured wake delay, warning findings for incompatible/inconclusive results, and notes for lower delay, synthetic data and context. These are findings, not execution failures; choose normal severity/baseline policy explicitly.

In DevPocket 0.4, cache a study only when **the manifest and every referenced capture** are covered by the declared inputs. For a protocol at `trial/study.json` with captures below `trial/captures`, selecting the whole `trial` directory is a complete file dependency declaration:

```json
{
  "version": 1,
  "plugins": ["reclaimlab-study"],
  "checks": {
    "repeated-performance": {
      "tool": "reclaimlab-study",
      "input": {"manifest": "trial/study.json", "iterations": 2000},
      "cache": {"inputs": ["trial"], "max_age": 3600}
    }
  }
}
```

For a single trace, declare that trace path in `cache.inputs`. Keep generated reports outside a cached input directory to avoid unnecessary invalidation. A changed capture invalidates the study's cache; baseline and severity gates are always reapplied. Direct `devpocket run` and MCP calls remain uncached. Study paths stay beneath the manifest directory, itself resolved within the selected project root.

## Browser-network checks

The HAR plugin keeps aliases on, reads only a selected saved capture and returns compact summaries with metric coverage, explicit budget states and at most 20 slow-wait rows. Headers, cookies, bodies and raw URLs never enter the adapter's result. Failed/unverifiable budgets are error findings; captured HTTP errors or incomplete measurements are warnings. Use `--fail-on error` when the explicit budgets should determine the gate; the default warning gate also blocks quality warnings.

Declare the capture file itself in `cache.inputs`. A changed HAR invalidates the result; budget inputs are also part of the cache key. To expose it over MCP, enable `reclaimlab-har` in the root config and add `--plugin reclaimlab-har` to `devpocket serve`.

See the [browser network guide](browser-network.md) and [combined build/network configuration](../examples/web-checks.json). `python examples/verify_devpocket.py` exercises installed discovery, all seven plugins, caches, content invalidation, SARIF, MCP, AssetGuard and workspace orchestration.

## Paired HAR experiment gates

The `reclaimlab-network-study` adapter runs the complete [network-study audit](network-studies.md) and returns bounded pair summaries. Incompatible studies and failed/unknown configured growth gates return `ToolResult.exit_code=1` as well as error findings. Baselines or `--fail-on none` cannot turn an unverifiable growth gate into success. Complete studies without a budget are descriptive; consistently higher measurements add a warning finding.

```json
{
  "version": 1,
  "plugins": ["reclaimlab-network-study"],
  "checks": {
    "browser-experiment": {
      "tool": "reclaimlab-network-study",
      "input": {"manifest": "trial/network-study.json", "max_growth": 0},
      "cache": {"inputs": ["trial"]}
    }
  }
}
```

The declared input directory must contain the manifest and **all referenced HARs**. Invalid/failed gate results are not cached. A changed HAR invalidates a successful result. MCP exposure requires both project enablement and an explicit `--plugin reclaimlab-network-study`; it performs no capture, browser automation or writes.

For DevPocket 1.x, put a finished-build check and browser-study check in separate project roots and make the browser project `needs` the build project in `.devpocket-workspace.json`. `devpocket workspace plan` reviews dependencies without importing plugins; `devpocket workspace check --format sarif` runs the selected checks with project-relative roots and one worker limit. This orders checks; it cannot prove that manual HAR exports came from that build.
