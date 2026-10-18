# Counter coverage and trace format

[Back to ReclaimLab](../README.md)

| Measurement | Linux | Windows |
| --- | --- | --- |
| Aggregate CPU active time | `/proc/stat`; idle, iowait and stolen time excluded | `GetSystemTimes`; idle subtracted from kernel+user |
| CPU iowait / stolen time | Counter deltas | Unavailable |
| Immediately available memory | `MemAvailable` from `/proc/meminfo`; unknown if absent | `GlobalMemoryStatusEx` physical available bytes |
| Commit utilisation | Unavailable in v0.2 | `GetPerformanceInfo` commit total / current commit limit |
| CPU/memory/I/O pressure | PSI `some total` deltas when available | Unavailable |
| Swap traffic | `pswpin` / `pswpout` deltas times page size | Unavailable; pagefile capacity is not treated as paging traffic |
| Device busy time | Maximum among recognised whole block devices in `/proc/diskstats` | Unavailable |
| CPU-related temperature | Recognised CPU/x86-package/SoC thermal-zone names when readable | Unavailable |
| Throttle counter | Available `core_throttle_count` maximum delta | Unavailable |
| Power source | Readable power-supply online/status fields | `GetSystemPowerStatus` |
| Optional processes | `/proc/PID/stat` CPU/start-time/RSS | Toolhelp snapshot, `GetProcessTimes`, RSS when access permits |

CPU counters are machine aggregates. A single saturated core on a many-core machine can be hidden by a low aggregate percentage. Process CPU is normalised to total logical-CPU capacity. Process collection is capped at 2,048 examined entries and five retained processes per record. Access failures, process exits and PID reuse can leave gaps; absence from the top list does not prove a process was uninvolved.

Linux guest time is already included in user/nice time and is not added twice. Stolen time is exposed separately and excluded from active CPU work. Disk busy time is not throughput or service latency, and can be misleading on parallel/stacked storage. The thermal counter is a maximum across readable per-core counters, not a sum of unique thermal incidents. A high temperature sensor alone cannot establish a CPU throttle event.

Container metrics can describe host capacity rather than a process's cgroup quota; detected container contexts carry a warning. Virtual machines, hot-plug hardware, heterogeneous CPUs and Windows processor-group behaviour on systems with more than 64 logical CPUs require additional care. The intended first target is small older laptops, not a server profiler.

Native capture is read-only and needs no elevation for normal accessible counters. Unavailable or denied counters are `null`, not zero. Windows versions older than the CI runners, including Windows 8.1, have not been tested. The APIs are longstanding, but interpreter and OS compatibility still need real-device verification. macOS has no live backend in v0.2.

## Schema 1 JSONL

A trace contains one header, increasing sample records, optional markers and an optional final footer. The loader enforces schema, finite numeric ranges, timing order, marker bounds, known metric names and bounded process/wake arrays. Limits: 128 MiB per file, 200,000 records and 1 MiB per line. Malformed/truncated JSON is rejected.

The header includes software/backend versions, OS/release, label/workload, requested interval, logical CPU count, physical memory, architecture and CPU model. A coarse compatibility hash excludes hostnames, serial numbers and network identity. It is not a unique device identifier.

Each sample stores elapsed endpoint `t`, observed `dt`, `collector_ms`, up to 512 `wake_lag_ms` values, a metric object and up to five process records. The heartbeat queue is limited to 2,048 entries; discarded observations are counted. Markers contain elapsed time and user text. Footers include duration, interruption/error state, recorder CPU seconds and dropped-observation count.

The default capture limit is one hour with native sampling no faster than 0.2 seconds. Reports cap chart geometry through bucket selection and render at most 200 episode rows and 1,000 marker controls. Imported content is treated as data and escaped in HTML; report text is still not guaranteed free of private details.

Primary implementation references: [Linux PSI](https://docs.kernel.org/accounting/psi.html), [Linux I/O statistics](https://docs.kernel.org/admin-guide/iostats.html), [Microsoft memory information](https://learn.microsoft.com/en-us/windows/win32/memory/memory-performance-information), [MEMORYSTATUSEX](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/ns-sysinfoapi-memorystatusex), [PERFORMANCE_INFORMATION](https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-performance_information).
