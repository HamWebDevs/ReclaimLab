# DevPocket integration

[Back to ReclaimLab](../README.md)

ReclaimLab publishes an optional Python entry point in the `devpocket.tools` group. Standalone use does not import or require DevPocket. The integration targets DevPocket 0.3 API v1.

Install both repositories in the same environment. DevPocket is not assumed to exist on PyPI:

```bash
python -m pip install "git+https://github.com/HamWebDevs/DevPocket.git"
python -m pip install .
devpocket plugins list
devpocket plugins enable reclaimlab
```

From the project containing a saved trace:

```bash
devpocket run reclaimlab --input '{"trace":"before.jsonl"}' --format json
devpocket run reclaimlab --input '{"trace":"before.jsonl"}' --format sarif
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
devpocket serve --root /absolute/path/to/project --plugin reclaimlab
```

Enabling an installed Python plugin is a trust decision. ReclaimLab's adapter only reads a selected trace, but the SDK's read-only declaration is not a sandbox. Reports can include labels and optional process names; the client controls subsequent model or network handling of returned data.
