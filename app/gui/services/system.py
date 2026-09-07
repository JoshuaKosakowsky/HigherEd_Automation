"""Small operating-system integrations used by the GUI."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def open_path(path: Path) -> None:
    target = path.resolve()
    if sys.platform == "win32":
        os.startfile(target)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target)])
