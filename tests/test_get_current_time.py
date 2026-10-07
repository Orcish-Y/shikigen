"""Time tools must work with the packaged IANA database on Windows."""

import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo, reset_tzpath

from shikigen.tools.get_current_time import get_current_time


class CurrentTimeTests(unittest.TestCase):
  def test_packaged_timezone_works_without_system_database(self):
    reset_tzpath(())
    ZoneInfo.clear_cache()
    self.addCleanup(reset_tzpath)
    self.addCleanup(ZoneInfo.clear_cache)
    clock_before = datetime.now(ZoneInfo("Asia/Shanghai")).replace(microsecond=0)
    timestamp = datetime.strptime(get_current_time.invoke({}), "%Y-%m-%d %H:%M:%S")
    clock_after = datetime.now(ZoneInfo("Asia/Shanghai")).replace(microsecond=0)
    self.assertLessEqual(clock_before.replace(tzinfo=None), timestamp)
    self.assertLessEqual(timestamp, clock_after.replace(tzinfo=None))

  def test_current_time_uses_shanghai_timezone(self):
    expected_time = datetime(2026, 10, 7, 23, 59, 58)
    with patch("datetime.datetime", wraps=datetime) as clock:
      clock.now.return_value = expected_time
      self.assertEqual(get_current_time.invoke({}), "2026-10-07 23:59:58")
      clock.now.assert_called_once_with(ZoneInfo("Asia/Shanghai"))
