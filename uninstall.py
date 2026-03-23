#!/usr/bin/env python3
"""Uninstall autodidact. Wrapper for install.py --uninstall."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

if __name__ == "__main__":
    install_script = Path(__file__).resolve().parent / "install.py"
    sys.exit(subprocess.call([sys.executable, str(install_script), "--uninstall"]))
