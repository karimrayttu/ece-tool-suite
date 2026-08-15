"""Hand a path to the desktop: open a folder in the file manager, run an installed tool.

``os.startfile`` only exists on Windows, and attribute access raises ``AttributeError``
elsewhere rather than something a caller would think to catch. ``subprocess.Popen`` has the
same asymmetry with ``creationflags``, which is a ``ValueError`` off Windows. Both are wrapped
here so the callers can stay one line.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def open_path(target: str | Path) -> None:
    """Open a file or folder the way a double-click would. Raises OSError on failure."""
    target = str(target)
    if os.name == "nt":
        os.startfile(target)  # type: ignore[attr-defined]  # noqa: S606 - Windows only
    elif sys.platform == "darwin":
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen(["xdg-open", target])


def spawn_detached(argv: list[str], **kwargs) -> subprocess.Popen:
    """Launch a GUI tool that must outlive this request.

    Windows wants DETACHED_PROCESS so closing the sidecar does not take the tool with it;
    POSIX gets its own session for the same reason.
    """
    if os.name == "nt":
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | 0x08  # DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(argv, **kwargs)
