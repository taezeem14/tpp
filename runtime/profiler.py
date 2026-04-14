from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass
class ProfileEntry:
    count: int = 0
    total_ms: float = 0.0


class RuntimeProfiler:
    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self.entries: dict[str, ProfileEntry] = {}

    @contextmanager
    def measure(self, label: str):
        if not self.enabled:
            yield
            return

        start = time.perf_counter()
        try:
            yield
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            entry = self.entries.setdefault(label, ProfileEntry())
            entry.count += 1
            entry.total_ms += duration_ms

    def report(self) -> str:
        if not self.enabled:
            return "Profiler disabled"
        if not self.entries:
            return "No profiling data"

        lines = ["Runtime profiling summary:"]
        for label, entry in sorted(self.entries.items(), key=lambda kv: kv[1].total_ms, reverse=True):
            avg = entry.total_ms / max(1, entry.count)
            lines.append(f"- {label}: calls={entry.count}, total={entry.total_ms:.2f}ms, avg={avg:.2f}ms")
        return "\n".join(lines)
