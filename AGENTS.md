# Working on ReclaimLab

- Python 3.10+; no runtime dependencies.
- Run checks from the repository root: `python -m unittest discover -s tests -v`.
- Native capture supports Windows/Linux. Analysis/report tests run on macOS too; do not fake a native backend there.
- `native.py` reads counters; `record.py` captures; `trace.py` validates; `analysis.py` explains; `experiment.py` compares; `report.py` creates offline HTML.
- Preserve unknown values, unit conversions, counter-reset/PID-reuse handling and monotonic timing.
- Do not add system tweaks, elevation, shell commands, network calls or automatic uploads without an explicit user request.
- Protect trace/report boundaries and exclusive writes. All trace text is untrusted; never insert it with innerHTML or directly into executable JavaScript.
- The report template is package data. Verify an installed-wheel report from outside the source checkout after packaging changes.
- Keep confidence language honest: scheduling probe lateness is not GUI input latency; overlap is not cause; synthetic data is not measured performance.
- The optional DevPocket adapter must remain read-only and import the SDK only when used.
- Study protocols stay below their manifest directory. Preserve protocol stamps, schedule checks, reused-sample detection and all incompatible pairs in the audit.
- The study bootstrap resamples whole paired runs with equal weights; do not pool heartbeat observations as independent experiments.
- Study plugins remain compatible with DevPocket API v1; only host 0.4+ provides optional caching. Declare every referenced capture in cache inputs.
- HAR exports keep only allowlisted measurements; discard headers/cookies/bodies/query/userinfo before returning report data. Preserve default aliases and explicit origin/path opt-in.
- HAR missing/-1 values remain unknown, TLS stays inside connect, multi-page scope is explicit and incomplete measurements cannot pass dependent budgets. Keep the HAR plugin read-only and its model-facing data compact.
- Network studies resample whole paired HAR runs, audit every planned pair and both capture orders, and gate interval/order-group growth conservatively. Incomplete data or uncertainty must never pass a configured budget.
- HAR experiment declarations/hashes are not capture authentication or revision binding. Discard absolute timestamps, browser identities and measurement signatures after internal consistency audits; never claim causality.
- Cache a network study only with its manifest and all referenced HARs covered. Verify the installed fourth plugin and cross-project workspace workflow, plus both network report interfaces in real-browser CI.
