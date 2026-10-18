# Security and privacy

The application does not tune system settings, elevate privileges, run shell commands, install software, send telemetry or make network requests. It reads native counters and writes explicitly requested traces/reports. Package installation and your browser/MCP client have their own behaviour outside this application's control.

Default collection intentionally excludes hostnames, usernames, network addresses, serial numbers, command lines, window titles and browser history. Labels/workloads are user text. Optional process evidence includes names and PIDs and can reveal private activity; review before sharing. There is no claim that an arbitrary imported trace is anonymised.

Trace inputs are bounded and validated. Report JSON escapes HTML delimiters, DOM insertion uses textContent and a restrictive Content Security Policy disallows network connections. This is defence in depth, not a guarantee against every browser issue. Keep original traces private when appropriate.

No automatic fixes are applied. Diagnostic overlap rules and before/after intervals do not establish causality or hardware health. The tool does not replace security monitoring or driver/application-specific tracing.

For a vulnerability, request a private reporting channel without posting credentials, private logs or exploit-bearing personal data in a public issue. Use GitHub private reporting if enabled.
