"""Append-only audit log.

Every safety-relevant action (instrument write, preset run, output-enable, provenance
promotion) is recorded here verbatim. The log is JSON-lines so it is greppable and
tail-able, and each record carries a monotonic sequence number.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any


class AuditLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._seq = 0

    def record(self, event: str, **fields: Any) -> dict:
        """Append one event. Returns the written record (incl. seq + ts)."""
        with self._lock:
            self._seq += 1
            rec = {"seq": self._seq, "ts": time.time(), "event": event, **fields}
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, default=str) + "\n")
            return rec
