"""RTK CLI integration for token savings detection and reporting.

Detects the `rtk` CLI tool and queries it for token savings summaries
and discovery opportunities. All functions degrade gracefully to None
on any failure — rtk is optional.
"""

from __future__ import annotations

import json
import shutil
import subprocess

# ── Detection ────────────────────────────────────────────────────────


def is_rtk_installed() -> bool:
    """Return True if the `rtk` CLI is available on PATH."""
    return shutil.which("rtk") is not None


# ── Queries ──────────────────────────────────────────────────────────


def get_rtk_savings_summary(project_path: str) -> dict[str, object] | None:
    """Return token savings summary for the project, or None on any failure.

    Runs: rtk gain --project --format json
    """
    if not is_rtk_installed():
        return None
    try:
        result = subprocess.run(
            ["rtk", "gain", "--project", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=project_path or None,
        )
        parsed: dict[str, object] = json.loads(result.stdout)
        return parsed
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        return None


def get_rtk_discover_opportunities(project_path: str) -> dict[str, object] | None:
    """Return discovery opportunities for the project, or None on any failure.

    Runs: rtk discover --format json --since 7
    """
    if not is_rtk_installed():
        return None
    try:
        result = subprocess.run(
            ["rtk", "discover", "--format", "json", "--since", "7"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=project_path or None,
        )
        parsed: dict[str, object] = json.loads(result.stdout)
        return parsed
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        return None


def get_rtk_economics(project_path: str) -> dict[str, object] | None:
    """Return token economics data (daily), or None on any failure.

    Runs: rtk gain --format json --daily
    Optionally also: rtk cc-economics --format json --daily

    Returns a combined dict:
        {"gain": <parsed gain data>, "cc_economics": <parsed cc-economics data or None>}
    """
    if not is_rtk_installed():
        return None
    try:
        gain_result = subprocess.run(
            ["rtk", "gain", "--format", "json", "--daily"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=project_path or None,
        )
        gain_data: dict[str, object] = json.loads(gain_result.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        return None

    cc_economics_data: dict[str, object] | None = None
    try:
        cc_result = subprocess.run(
            ["rtk", "cc-economics", "--format", "json", "--daily"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=project_path or None,
        )
        cc_economics_data = json.loads(cc_result.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        pass

    return {
        "gain": gain_data,
        "cc_economics": cc_economics_data,
    }
