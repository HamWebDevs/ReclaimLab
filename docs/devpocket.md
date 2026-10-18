# DevPocket integration

[Back to ReclaimLab](../README.md)

ReclaimLab publishes optional `reclaimlab`, `reclaimlab-study` and `reclaimlab-har` entry points in the `devpocket.tools` group. Standalone use does not import or require DevPocket. All three use API v1, work uncached on DevPocket 0.3 and opt into result caching on 0.4+. The combined AssetGuard workflow additionally requires DevPocket 0.5+.

Install both repositories in the same environment. DevPocket is not assumed to exist on PyPI:

```bash
python -m pip install "git+https://github.com/HamWebDevs/DevPocket.git"
python -m pip install .
devpocket plugins list
devpocket plugins enable reclaimlab
devpocket plugins enable reclaimlab-study
devpocket plugins enable reclaimlab-har
```

From the project containing a saved trace:

```bash
devpocket run reclaimlab --input '{"trace":"before.jsonl"}' --format json
devpocket run reclaimlab --input '{"trace":"before.jsonl"}' --format sarif
devpocket run reclaimlab-study --input '{"manifest":"trial/study.json"}' --format json
devpocket run reclaimlab-har --input '{"capture":"artifacts/page.har","max_errors":0}' --format sarif
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

See the [browser network guide](browser-network.md) and [combined build/network configuration](../examples/web-checks.json). `python examples/verify_devpocket.py` exercises installed discovery, all three plugins, caches, content invalidation, SARIF, MCP and DevPocket 0.5's build auditor.
