# Contributing

Keep collection cheap, evidence explainable and system changes explicit.

- Use Python 3.10-compatible code and standard-library runtime dependencies only.
- Add real fixtures for counter maths, unavailable data, resets and platform boundaries.
- Do not turn a correlation into a cause or an unsupported counter into zero.
- Preserve exclusive output creation, input bounds and HTML/text injection boundaries.
- Test with `python -m unittest discover -s tests -v`.
- Update counter coverage and methodology when a new measurement or rule is added.
- Add backends behind the snapshot/delta contract. Keep recording, analysis, experiments and reports separate.
- Keep `reclaimlab/report_template.html` packaged; installed-wheel report generation must work without the source checkout.
- Mark every synthetic fixture and demonstration as synthetic.

Useful contributions include real-device counter validation, older Windows testing, accessibility improvements, a native macOS collector and controlled multi-run experiment designs. Do not post private traces or process names in issues without reviewing them.
