"""Capture stdout to a log file so scheduled runs can drop the console window.

Task Scheduler shows a console window whenever the action is a .cmd or python.exe,
because both are console-subsystem programs. pythonw.exe has no console, which
fixes the popup but also throws away everything printed. This tees output to a
file so the scheduled path stays debuggable without a visible window.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path


class _Tee:
    def __init__(self, stream, fh):
        self._stream, self._fh = stream, fh

    def write(self, data: str) -> int:
        if self._stream is not None:
            try:
                self._stream.write(data)
            except Exception:
                pass
        self._fh.write(data)
        self._fh.flush()
        return len(data)

    def flush(self) -> None:
        for s in (self._stream, self._fh):
            try:
                if s is not None:
                    s.flush()
            except Exception:
                pass


def tee(path: Path, *, header: str = "", max_bytes: int = 2_000_000) -> None:
    """Send stdout and stderr to `path` as well as the console, if there is one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > max_bytes:
        path.replace(path.with_suffix(path.suffix + ".1"))
    fh = path.open("a", encoding="utf-8", errors="replace")
    fh.write(f"\n===== {datetime.now(UTC).isoformat(timespec='seconds')} "
             f"{header} =====\n")
    sys.stdout = _Tee(sys.stdout, fh)
    sys.stderr = _Tee(sys.stderr, fh)
