"""Synthetic-only economic calendar report tests."""
import unittest
from fx_system.economic_calendar_report import calendar_lines
from fx_system.economic_calendar_context import enrich_outlook
from fx_system.monitor_pairs import PAIR_KEYS


class CalendarReportTests(unittest.TestCase):
    def test_legacy_output_unchanged(self):
        self.assertEqual(calendar_lines({"grade": "B"}, str), [])

    def test_unavailable_is_explicit(self):
        lines = calendar_lines({"economic_calendar_context": {"status": "unavailable"}}, str)
        self.assertIn("検証済み情報なし", lines[0])

    def test_event_display_is_advisory(self):
        row = {"economic_calendar_context": {"status": "available", "events": [
            {"currency": "USD", "title": "Employment", "scheduled_at_utc": 100,
             "timing": "upcoming"}]}}
        lines = calendar_lines(row, str)
        self.assertIn("Employment", lines[0])
        self.assertIn("不変更", lines[-1])

    def test_source_attribution(self):
        row = {"economic_calendar_context": {"status": "available",
            "attribution_url": "https://www.financecalendar.com", "events": [
                {"currency": "USD", "title": "Employment",
                 "scheduled_at_utc": 100, "timing": "upcoming"}]}}
        lines = calendar_lines(row, str)
        self.assertTrue(any("https://www.financecalendar.com" in line for line in lines))

    def test_no_events_not_market_skip(self):
        lines = calendar_lines({"economic_calendar_context": {
            "status": "partial", "events": []}}, str)
        self.assertIn("完全性", lines[0])
        self.assertNotIn("見送り", lines[0])

    def test_empty_provider_result_keeps_attribution(self):
        lines = calendar_lines({"economic_calendar_context": {
            "status": "available", "events": [],
            "attribution_url": "https://www.financecalendar.com"}}, str)
        self.assertTrue(any("https://www.financecalendar.com" in line for line in lines))

    def test_grade_is_untouched(self):
        source = {"evaluated_at": 1000000, "strategy_assessments": [
            {"pair": pair, "strategy": strategy, "grade": "A", "direction": "long"}
            for pair in PAIR_KEYS for strategy in ("swing", "daytrade")]}
        result = enrich_outlook(source, {
            "observed_at_utc": 1000000, "complete": False, "events": []})
        for assessment in result["strategy_assessments"]:
            calendar_lines(assessment, str)
            self.assertEqual(assessment["grade"], "A")


if __name__ == "__main__":
    unittest.main()
