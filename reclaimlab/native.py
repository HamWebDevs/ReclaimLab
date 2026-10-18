"""Native read-only collectors; no subprocesses, privileged APIs or dependencies."""
from __future__ import annotations
import os
from pathlib import Path
import platform
import re
import time


def read(path, limit=1024 * 1024):
    try:
        with Path(path).open(encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return None


def values(text):
    result = {}
    for line in (text or "").splitlines():
        fields = line.replace(":", " ").split()
        if len(fields) > 1:
            try:
                result[fields[0]] = int(fields[1])
            except ValueError:
                pass
    return result


def pressure(text):
    out = {}
    for line in (text or "").splitlines():
        parts = line.split()
        for field in parts[1:]:
            if field.startswith("total="):
                try:
                    out[parts[0]] = int(field.split("=")[1])
                except ValueError:
                    pass
    return out


def linux_cpu(text):
    for line in (text or "").splitlines():
        if line.startswith("cpu "):
            parts = [int(x) for x in line.split()[1:9]]
            if len(parts) < 5:
                raise ValueError("Incomplete /proc/stat CPU row")
            return {"total": sum(parts), "idle": parts[3], "iowait": parts[4], "steal": parts[7] if len(parts) > 7 else 0}
    raise ValueError("No aggregate CPU counters in /proc/stat")


def linux_process(text, ticks, page_size):
    # comm may contain spaces and parentheses; the final ')' closes it.
    first, last = text.find("("), text.rfind(")")
    if first < 0 or last < first:
        raise ValueError("Invalid process stat")
    fields = text[last + 1:].split()
    return {"name": text[first + 1:last][:128], "start": fields[19], "cpu_seconds": (int(fields[11]) + int(fields[12])) / ticks, "rss_bytes": max(0, int(fields[21])) * page_size}


class Linux:
    name = "linux-proc"

    def __init__(self, processes=False, proc="/proc", sys="/sys", page_size=None, ticks=None):
        self.proc, self.sys = Path(proc), Path(sys)
        self.processes = processes
        self.page_size = page_size or os.sysconf("SC_PAGE_SIZE")
        self.ticks = ticks or os.sysconf("SC_CLK_TCK")

    def snapshot(self):
        cpu = linux_cpu(read(self.proc / "stat"))
        memory = values(read(self.proc / "meminfo"))
        total = memory.get("MemTotal", 0) * 1024
        available = memory.get("MemAvailable")
        # Free+cache is not a substitute for MemAvailable on old kernels.
        vm = values(read(self.proc / "vmstat"))
        disks = {}
        for line in (read(self.proc / "diskstats") or "").splitlines():
            p = line.split()
            if len(p) < 14 or not re.fullmatch(r"(?:sd[a-z]+|vd[a-z]+|xvd[a-z]+|nvme\d+n\d+|mmcblk\d+)", p[2]):
                continue
            try:
                disks[p[2]] = {"read": int(p[5]) * 512, "write": int(p[9]) * 512, "busy_ms": int(p[12])}
            except ValueError:
                continue
        psi = {kind: pressure(read(self.proc / "pressure" / kind)) for kind in ("cpu", "memory", "io")}
        temperatures = []
        for path in sorted((self.sys / "class/thermal").glob("thermal_zone*/temp"))[:32]:
            typ = (read(path.parent / "type") or "").lower()
            raw = read(path)
            if raw and any(k in typ for k in ("cpu", "x86_pkg", "soc")):
                try:
                    c = int(raw) / 1000
                    if 0 <= c <= 130:
                        temperatures.append(c)
                except ValueError:
                    pass
        throttles = []
        for path in sorted((self.sys / "devices/system/cpu").glob("cpu*/thermal_throttle/core_throttle_count"))[:512]:
            try:
                throttles.append(int(read(path) or ""))
            except ValueError:
                pass
        power = "unknown"
        for supply in sorted((self.sys / "class/power_supply").glob("*"))[:16]:
            online = (read(supply / "online") or "").strip()
            if online == "1":
                power = "ac"
                break
            status = (read(supply / "status") or "").strip().lower()
            if status == "discharging":
                power = "battery"
            elif status in {"charging", "full"}:
                power = "ac"
        procs = {}
        if self.processes:
            for path in sorted(self.proc.glob("[0-9]*/stat"))[:2048]:
                try:
                    data = read(path, 16384)
                    if data:
                        procs[path.parent.name] = linux_process(data, self.ticks, self.page_size)
                except (ValueError, IndexError):
                    pass
        return {"clock": time.monotonic(), "cpu": cpu, "memory_total": total or None, "memory_available": available * 1024 if available is not None else None, "commit_pct": None, "swap_in": vm.get("pswpin", 0) * self.page_size if "pswpin" in vm else None, "swap_out": vm.get("pswpout", 0) * self.page_size if "pswpout" in vm else None, "psi": psi, "disks": disks, "temperature_c": max(temperatures) if temperatures else None, "throttle_count": max(throttles) if throttles else None, "power": power, "processes": procs}

    def description(self):
        cpuinfo = read(self.proc / "cpuinfo") or ""
        model = next((line.split(":", 1)[1].strip() for line in cpuinfo.splitlines() if line.startswith("model name") and ":" in line), platform.machine())
        cgroup = (read(self.proc / "self/cgroup") or "")
        return {"cpu_model": model[:160], "scope_warning": "Container/virtualisation counters may represent host capacity; do not infer a hardware upgrade from this trace." if Path('/.dockerenv').exists() or 'docker' in cgroup or 'kubepods' in cgroup else None}


class Windows:
    name = "windows-native"

    def __init__(self, processes=False):
        if os.name != "nt":
            raise OSError("Windows collector requires Windows")
        import ctypes as c
        from ctypes import wintypes as w
        self.c, self.w = c, w
        self.processes = processes
        self.kernel = c.WinDLL("kernel32", use_last_error=True)
        self.psapi = c.WinDLL("psapi", use_last_error=True)
        class Memory(c.Structure):
            _fields_ = [("length", w.DWORD), ("load", w.DWORD)] + [(name, c.c_ulonglong) for name in ("total", "available", "page_total", "page_available", "virtual_total", "virtual_available", "extended")]
        class Performance(c.Structure):
            _fields_ = [("cb", w.DWORD)] + [(name, c.c_size_t) for name in ("commit", "limit", "peak", "physical", "available", "cache", "kernel", "paged", "nonpaged", "page_size")] + [(name, w.DWORD) for name in ("handles", "processes", "threads")]
        class Power(c.Structure):
            _fields_ = [(name, w.BYTE) for name in ("ac", "flag", "percent", "reserved")] + [("life", w.DWORD), ("full_life", w.DWORD)]
        class Process(c.Structure):
            _fields_ = [("size", w.DWORD), ("usage", w.DWORD), ("pid", w.DWORD), ("heap", c.c_size_t), ("module", w.DWORD), ("threads", w.DWORD), ("parent", w.DWORD), ("priority", w.LONG), ("flags", w.DWORD), ("exe", w.WCHAR * 260)]
        class ProcessMemory(c.Structure):
            _fields_ = [("cb", w.DWORD), ("faults", w.DWORD)] + [(name, c.c_size_t) for name in ("peak_rss", "rss", "peak_paged", "paged", "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile")]
        self.Memory, self.Performance, self.Power = Memory, Performance, Power
        self.Process, self.ProcessMemory = Process, ProcessMemory
        for name, args, ret in (
            ("GetSystemTimes", [c.POINTER(w.FILETIME)] * 3, w.BOOL),
            ("GlobalMemoryStatusEx", [c.POINTER(Memory)], w.BOOL),
            ("GetSystemPowerStatus", [c.POINTER(Power)], w.BOOL),
            ("CreateToolhelp32Snapshot", [w.DWORD, w.DWORD], w.HANDLE),
            ("Process32FirstW", [w.HANDLE, c.POINTER(Process)], w.BOOL),
            ("Process32NextW", [w.HANDLE, c.POINTER(Process)], w.BOOL),
            ("OpenProcess", [w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            ("CloseHandle", [w.HANDLE], w.BOOL),
            ("GetProcessTimes", [w.HANDLE] + [c.POINTER(w.FILETIME)] * 4, w.BOOL),
        ):
            f = getattr(self.kernel, name)
            f.argtypes, f.restype = args, ret
        self.psapi.GetPerformanceInfo.argtypes = [c.POINTER(Performance), w.DWORD]
        self.psapi.GetPerformanceInfo.restype = w.BOOL
        self.psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, c.POINTER(ProcessMemory), w.DWORD]
        self.psapi.GetProcessMemoryInfo.restype = w.BOOL

    @staticmethod
    def ft(value):
        return (value.dwHighDateTime << 32) | value.dwLowDateTime

    def process_snapshot(self):
        c, w = self.c, self.w
        result = {}
        handle = self.kernel.CreateToolhelp32Snapshot(2, 0)
        if handle in {None, c.c_void_p(-1).value}:
            return result
        try:
            entry = self.Process()
            entry.size = c.sizeof(entry)
            more = self.kernel.Process32FirstW(handle, c.byref(entry))
            count = 0
            while more and count < 2048:
                count += 1
                ph = self.kernel.OpenProcess(0x1000, False, entry.pid)
                if ph:
                    try:
                        created, ended, kernel, user = (w.FILETIME() for _ in range(4))
                        if self.kernel.GetProcessTimes(ph, c.byref(created), c.byref(ended), c.byref(kernel), c.byref(user)):
                            mem = self.ProcessMemory()
                            mem.cb = c.sizeof(mem)
                            rss = int(mem.rss) if self.psapi.GetProcessMemoryInfo(ph, c.byref(mem), c.sizeof(mem)) else None
                            result[str(entry.pid)] = {"name": entry.exe[:128], "start": str(self.ft(created)), "cpu_seconds": (self.ft(kernel) + self.ft(user)) / 1e7, "rss_bytes": rss}
                    finally:
                        self.kernel.CloseHandle(ph)
                more = self.kernel.Process32NextW(handle, c.byref(entry))
        finally:
            self.kernel.CloseHandle(handle)
        return result

    def snapshot(self):
        c, w = self.c, self.w
        idle, kernel, user = (w.FILETIME() for _ in range(3))
        if not self.kernel.GetSystemTimes(c.byref(idle), c.byref(kernel), c.byref(user)):
            raise OSError(c.get_last_error(), "GetSystemTimes failed")
        mem = self.Memory()
        mem.length = c.sizeof(mem)
        if not self.kernel.GlobalMemoryStatusEx(c.byref(mem)):
            raise OSError(c.get_last_error(), "GlobalMemoryStatusEx failed")
        perf = self.Performance()
        perf.cb = c.sizeof(perf)
        commit = 100 * perf.commit / perf.limit if self.psapi.GetPerformanceInfo(c.byref(perf), c.sizeof(perf)) and perf.limit else None
        power = self.Power()
        supply = "unknown"
        if self.kernel.GetSystemPowerStatus(c.byref(power)):
            supply = "ac" if power.ac == 1 else "battery" if power.ac == 0 else "unknown"
        return {"clock": time.monotonic(), "cpu": {"total": self.ft(kernel) + self.ft(user), "idle": self.ft(idle), "iowait": None}, "memory_total": int(mem.total), "memory_available": int(mem.available), "commit_pct": commit, "swap_in": None, "swap_out": None, "psi": {}, "disks": {}, "temperature_c": None, "throttle_count": None, "power": supply, "processes": self.process_snapshot() if self.processes else {}}

    def description(self):
        return {"cpu_model": platform.processor()[:160] or platform.machine(), "scope_warning": None}


def collector(processes=False):
    if platform.system() == "Linux":
        return Linux(processes)
    if platform.system() == "Windows":
        return Windows(processes)
    raise OSError("Live capture supports Linux and Windows; analysis, comparison and offline reports work on this platform.")


def delta(current, previous, cpus=1):
    seconds = current["clock"] - previous["clock"]
    if seconds <= 0:
        raise ValueError("Collector clock did not advance")
    def difference(a, b):
        if a is None or b is None or a < b:
            return None
        return a - b
    total = difference(current["cpu"]["total"], previous["cpu"]["total"])
    idle = difference(current["cpu"]["idle"], previous["cpu"]["idle"])
    wait = difference(current["cpu"].get("iowait"), previous["cpu"].get("iowait"))
    steal = difference(current["cpu"].get("steal"), previous["cpu"].get("steal"))
    busy = max(0, min(100, 100 * (total - idle - (wait or 0) - (steal or 0)) / total)) if total and idle is not None else None
    metrics = {"cpu_pct": busy, "steal_pct": 100 * steal / total if total and steal is not None else None, "iowait_pct": 100 * wait / total if total and wait is not None else None, "memory_available_pct": 100 * current["memory_available"] / current["memory_total"] if current.get("memory_total") and current.get("memory_available") is not None else None, "commit_pct": current.get("commit_pct"), "temperature_c": current.get("temperature_c"), "power": current.get("power", "unknown")}
    for kind, key in (("cpu", "cpu_pressure_pct"), ("memory", "memory_pressure_pct"), ("io", "io_pressure_pct")):
        a, b = current.get("psi", {}).get(kind, {}), previous.get("psi", {}).get(kind, {})
        amount = difference(a.get("some"), b.get("some"))
        metrics[key] = max(0, min(100, amount / (seconds * 10000))) if amount is not None else None
    for direction in ("in", "out"):
        amount = difference(current.get("swap_" + direction), previous.get("swap_" + direction))
        metrics["swap_" + direction + "_Bps"] = amount / seconds if amount is not None else None
    busy_values = []
    for name, disk in current.get("disks", {}).items():
        old = previous.get("disks", {}).get(name)
        if old:
            amount = difference(disk["busy_ms"], old["busy_ms"])
            if amount is not None:
                busy_values.append(min(100, amount / (seconds * 10)))
    metrics["disk_busy_pct"] = max(busy_values) if busy_values else None
    metrics["throttle_events"] = difference(current.get("throttle_count"), previous.get("throttle_count"))
    procs = []
    for pid, process in current.get("processes", {}).items():
        old = previous.get("processes", {}).get(pid)
        if old and old["start"] == process["start"]:
            amount = difference(process["cpu_seconds"], old["cpu_seconds"])
            if amount is not None:
                procs.append({"pid": int(pid), "name": process["name"], "cpu_pct": min(100, amount * 100 / (seconds * max(1, cpus))), "rss_bytes": process.get("rss_bytes")})
    return metrics, sorted(procs, key=lambda p: (-p["cpu_pct"], -(p["rss_bytes"] or 0)))[:5]
