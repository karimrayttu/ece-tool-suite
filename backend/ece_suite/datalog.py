"""Server-side session recorder.

An in-memory, thread-safe per-role buffer of timestamped records, fed by the live WS loops
while logging is active for that role. Exportable as CSV. Records accumulate on the server
so a long run survives the UI navigating between tabs (it keeps filling while that
instrument's stream is open).
"""

from __future__ import annotations

import csv
import io
import threading
import time


class Recorder:
    def __init__(self) -> None:
        self._data: dict[str, list[dict]] = {}
        self._active: set[str] = set()
        self._lock = threading.Lock()

    def start(self, role: str) -> None:
        with self._lock:
            self._active.add(role)
            self._data.setdefault(role, [])

    def stop(self, role: str) -> None:
        with self._lock:
            self._active.discard(role)

    def clear(self, role: str) -> None:
        with self._lock:
            self._data[role] = []

    def active(self, role: str) -> bool:
        return role in self._active

    def count(self, role: str) -> int:
        with self._lock:
            return len(self._data.get(role, []))

    def record(self, role: str, rec: dict) -> None:
        with self._lock:
            if role in self._active:
                rec = {"t": time.time(), **rec}
                self._data.setdefault(role, []).append(rec)

    def to_csv(self, role: str) -> str:
        with self._lock:
            recs = list(self._data.get(role, []))
        if not recs:
            return ""
        keys: list[str] = []
        for r in recs:
            for k in r:
                if k not in keys:
                    keys.append(k)
        out = io.StringIO()
        w = csv.DictWriter(out, fieldnames=keys)
        w.writeheader()
        for r in recs:
            w.writerow(r)
        return out.getvalue()
