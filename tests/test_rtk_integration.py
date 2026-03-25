"""Tests for RTK CLI integration module."""

from __future__ import annotations

import subprocess
import unittest
from unittest.mock import MagicMock, patch

from src.rtk_integration import (
    get_rtk_discover_opportunities,
    get_rtk_savings_summary,
    is_rtk_installed,
)


class TestIsRtkInstalled(unittest.TestCase):
    def test_is_rtk_installed_true(self) -> None:
        with patch("shutil.which", return_value="/usr/local/bin/rtk"):
            self.assertTrue(is_rtk_installed())

    def test_is_rtk_installed_false(self) -> None:
        with patch("shutil.which", return_value=None):
            self.assertFalse(is_rtk_installed())


class TestGetRtkSavingsSummary(unittest.TestCase):
    def test_get_rtk_savings_summary_success(self) -> None:
        payload = {"total_commands": 42, "tokens_saved": 12345, "savings_percent": 72}
        mock_result = MagicMock()
        mock_result.stdout = '{"total_commands": 42, "tokens_saved": 12345, "savings_percent": 72}'
        with (
            patch("shutil.which", return_value="/usr/local/bin/rtk"),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = get_rtk_savings_summary("/some/project")
        self.assertEqual(result, payload)

    def test_get_rtk_savings_summary_not_installed(self) -> None:
        with patch("shutil.which", return_value=None):
            result = get_rtk_savings_summary("/some/project")
        self.assertIsNone(result)

    def test_get_rtk_savings_summary_command_fails(self) -> None:
        with (
            patch("shutil.which", return_value="/usr/local/bin/rtk"),
            patch("subprocess.run", side_effect=subprocess.SubprocessError("failed")),
        ):
            result = get_rtk_savings_summary("/some/project")
        self.assertIsNone(result)

    def test_get_rtk_savings_summary_bad_json(self) -> None:
        mock_result = MagicMock()
        mock_result.stdout = "not valid json at all"
        with (
            patch("shutil.which", return_value="/usr/local/bin/rtk"),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = get_rtk_savings_summary("/some/project")
        self.assertIsNone(result)


class TestGetRtkDiscoverOpportunities(unittest.TestCase):
    def test_get_rtk_discover_opportunities_success(self) -> None:
        payload = {"opportunities": ["use --quiet flag", "pipe to head"]}
        mock_result = MagicMock()
        mock_result.stdout = '{"opportunities": ["use --quiet flag", "pipe to head"]}'
        with (
            patch("shutil.which", return_value="/usr/local/bin/rtk"),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = get_rtk_discover_opportunities("/some/project")
        self.assertEqual(result, payload)

    def test_get_rtk_discover_opportunities_timeout(self) -> None:
        with (
            patch("shutil.which", return_value="/usr/local/bin/rtk"),
            patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="rtk", timeout=10),
            ),
        ):
            result = get_rtk_discover_opportunities("/some/project")
        self.assertIsNone(result)
