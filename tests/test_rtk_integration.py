"""Tests for RTK CLI integration module."""

from __future__ import annotations

import subprocess
import unittest
from unittest.mock import MagicMock, patch

from src.rtk_integration import (
    feed_discover_to_db,
    get_rtk_discover_opportunities,
    get_rtk_economics,
    get_rtk_savings_summary,
    is_rtk_installed,
)


class TestIsRtkInstalled(unittest.TestCase):
    def test_is_rtk_installed_true(self) -> None:
        with patch("src.rtk_integration.shutil.which", return_value="/usr/local/bin/rtk"):
            self.assertTrue(is_rtk_installed())

    def test_is_rtk_installed_false(self) -> None:
        with patch("src.rtk_integration.shutil.which", return_value=None):
            self.assertFalse(is_rtk_installed())


class TestGetRtkSavingsSummary(unittest.TestCase):
    def test_get_rtk_savings_summary_success(self) -> None:
        payload = {"total_commands": 42, "tokens_saved": 12345, "savings_percent": 72}
        mock_result = MagicMock(returncode=0)
        mock_result.stdout = '{"total_commands": 42, "tokens_saved": 12345, "savings_percent": 72}'
        with (
            patch("src.rtk_integration.shutil.which", return_value="/usr/local/bin/rtk"),
            patch("src.rtk_integration.subprocess.run", return_value=mock_result),
        ):
            result = get_rtk_savings_summary("/some/project")
        self.assertEqual(result, payload)

    def test_get_rtk_savings_summary_not_installed(self) -> None:
        with patch("src.rtk_integration.shutil.which", return_value=None):
            result = get_rtk_savings_summary("/some/project")
        self.assertIsNone(result)

    def test_get_rtk_savings_summary_command_fails(self) -> None:
        with (
            patch("src.rtk_integration.shutil.which", return_value="/usr/local/bin/rtk"),
            patch(
                "src.rtk_integration.subprocess.run",
                side_effect=subprocess.SubprocessError("failed"),
            ),
        ):
            result = get_rtk_savings_summary("/some/project")
        self.assertIsNone(result)

    def test_get_rtk_savings_summary_bad_json(self) -> None:
        mock_result = MagicMock(returncode=0)
        mock_result.stdout = "not valid json at all"
        with (
            patch("src.rtk_integration.shutil.which", return_value="/usr/local/bin/rtk"),
            patch("src.rtk_integration.subprocess.run", return_value=mock_result),
        ):
            result = get_rtk_savings_summary("/some/project")
        self.assertIsNone(result)


class TestGetRtkDiscoverOpportunities(unittest.TestCase):
    def test_get_rtk_discover_opportunities_success(self) -> None:
        payload = {"opportunities": ["use --quiet flag", "pipe to head"]}
        mock_result = MagicMock(returncode=0)
        mock_result.stdout = '{"opportunities": ["use --quiet flag", "pipe to head"]}'
        with (
            patch("src.rtk_integration.shutil.which", return_value="/usr/local/bin/rtk"),
            patch("src.rtk_integration.subprocess.run", return_value=mock_result),
        ):
            result = get_rtk_discover_opportunities("/some/project")
        self.assertEqual(result, payload)

    def test_get_rtk_discover_opportunities_timeout(self) -> None:
        with (
            patch("src.rtk_integration.shutil.which", return_value="/usr/local/bin/rtk"),
            patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="rtk", timeout=10),
            ),
        ):
            result = get_rtk_discover_opportunities("/some/project")
        self.assertIsNone(result)


class TestGetRtkEconomics(unittest.TestCase):
    def test_get_rtk_economics_success(self) -> None:
        gain_payload = {
            "total_commands": 100,
            "tokens_saved": 50000,
            "savings_percent": 65,
            "estimated_dollars_saved": 1.50,
        }
        cc_payload = {"daily_cost": 2.30, "total_cost": 45.00}

        gain_mock = MagicMock(returncode=0)
        gain_mock.stdout = (
            '{"total_commands": 100, "tokens_saved": 50000,'
            ' "savings_percent": 65, "estimated_dollars_saved": 1.50}'
        )
        cc_mock = MagicMock(returncode=0)
        cc_mock.stdout = '{"daily_cost": 2.30, "total_cost": 45.00}'

        with (
            patch("src.rtk_integration.shutil.which", return_value="/usr/local/bin/rtk"),
            patch("src.rtk_integration.subprocess.run", side_effect=[gain_mock, cc_mock]),
        ):
            result = get_rtk_economics("/some/project")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["gain"], gain_payload)
        self.assertEqual(result["cc_economics"], cc_payload)

    def test_get_rtk_economics_not_installed(self) -> None:
        with patch("src.rtk_integration.shutil.which", return_value=None):
            result = get_rtk_economics("/some/project")
        self.assertIsNone(result)

    def test_get_rtk_economics_gain_fails(self) -> None:
        with (
            patch("src.rtk_integration.shutil.which", return_value="/usr/local/bin/rtk"),
            patch(
                "src.rtk_integration.subprocess.run",
                side_effect=subprocess.SubprocessError("failed"),
            ),
        ):
            result = get_rtk_economics("/some/project")
        self.assertIsNone(result)

    def test_get_rtk_economics_cc_economics_not_available(self) -> None:
        gain_payload = {
            "total_commands": 50,
            "tokens_saved": 20000,
            "savings_percent": 55,
            "estimated_dollars_saved": 0.60,
        }
        gain_mock = MagicMock(returncode=0)
        gain_mock.stdout = (
            '{"total_commands": 50, "tokens_saved": 20000,'
            ' "savings_percent": 55, "estimated_dollars_saved": 0.60}'
        )

        def run_side_effect(*args, **_kwargs):
            cmd = args[0]
            if "cc-economics" in cmd:
                raise subprocess.SubprocessError("cc-economics not available")
            return gain_mock

        with (
            patch("src.rtk_integration.shutil.which", return_value="/usr/local/bin/rtk"),
            patch("src.rtk_integration.subprocess.run", side_effect=run_side_effect),
        ):
            result = get_rtk_economics("/some/project")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["gain"], gain_payload)
        self.assertIsNone(result["cc_economics"])


class TestFeedDiscoverToDb(unittest.TestCase):
    def test_feed_discover_to_db_success(self) -> None:
        """Entries with count >= 3 are recorded; entries below threshold are skipped."""
        discover_data = {
            "supported": [
                {"command": "ls", "count": 5, "savings_percent": 75},
                {"command": "git", "count": 10, "savings_percent": 80},
                {"command": "cat", "count": 2, "savings_percent": 65},  # below threshold
                {"command": "find", "count": 1, "savings_percent": 70},  # below threshold
            ]
        }
        db = MagicMock()
        with patch(
            "src.rtk_integration.get_rtk_discover_opportunities",
            return_value=discover_data,
        ):
            result = feed_discover_to_db("/some/project", db)

        self.assertEqual(result, 2)
        self.assertEqual(db.record.call_count, 2)

    def test_feed_discover_to_db_no_rtk(self) -> None:
        """Returns 0 and makes no db.record calls when RTK is not available."""
        db = MagicMock()
        with patch(
            "src.rtk_integration.get_rtk_discover_opportunities",
            return_value=None,
        ):
            result = feed_discover_to_db("/some/project", db)

        self.assertEqual(result, 0)
        db.record.assert_not_called()

    def test_feed_discover_to_db_empty_supported(self) -> None:
        """Returns 0 when supported list is empty."""
        db = MagicMock()
        with patch(
            "src.rtk_integration.get_rtk_discover_opportunities",
            return_value={"supported": []},
        ):
            result = feed_discover_to_db("/some/project", db)

        self.assertEqual(result, 0)
        db.record.assert_not_called()
