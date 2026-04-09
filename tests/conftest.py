"""Shared test configuration."""

import sys
from pathlib import Path

# Make scripts/ importable so tests can use `from verify_docs import ...`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
