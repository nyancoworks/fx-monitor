"""Synthetic-only tests: no provider calls or private observations."""
import unittest
from fx_system.monitor_pairs import PAIR_KEYS
from fx_system.economic_calendar_context import enrich_outlook


def outlook():
    pairs = PAIR_KEYS
    return {"evaluated_at": 1000000, "strategy_assessments": [
        {"pair": pair, "strategy": strategy, "grade": "B", "direction": "long"}
        for pair in pairs for strategy in ("swing", "daytrade")]}


class CalendarContextTests(unittest.TestCase):
    def test_no_calendar_is_unavailable_and_grades_unchanged(self):
        before = outlook()
        after = enrich_outlook(before, None)
        self.assertEqual(len(after["strategy_assessments"]), 32)
        self.assertEqual(after["economic_calendar_context"]["status"], "unavailable")
        self.assertTrue(all(x["grade"] == "B" for x in after["strategy_assessments"]))
        self.assertNotIn("economic_calendar_context", before["strategy_assessments"][0])

    def test_future_actual_hidden_and_windows_differ(self):
        event = {"currency": "USD", "scheduled_at_utc": 1000000 + 2 * 86400,
                 "observed_at_utc": 1000000, "reference_only": True,
                 "actual": 4.0, "surprise": 1.0}
        result = enrich_outlook(outlook(), {"observed_at_utc": 1000000,
                                           "complete": True, "events": [event]})
        swing, daytrade = result["strategy_assessments"][:2]
        self.assertEqual(len(swing["economic_calendar_context"]["events"]), 1)
        self.assertEqual(len(daytrade["economic_calendar_context"]["events"]), 0)
        self.assertIsNone(swing["economic_calendar_context"]["events"][0]["actual"])

    def test_future_observation_not_used(self):
        event = {"currency": "USD", "scheduled_at_utc": 1000100,
                 "observed_at_utc": 1000001, "reference_only": True}
        result = enrich_outlook(outlook(), {"observed_at_utc": 1000000,
                                           "complete": False, "events": [event]})
        self.assertEqual(result["strategy_assessments"][0]["economic_calendar_context"]["events"], [])

    def test_release_observation_precedes_release(self):
        event = {"currency": "USD", "scheduled_at_utc": 999900,
                 "observed_at_utc": 999800, "reference_only": True,
                 "actual": 5.0, "actual_raw": "5%", "surprise": 2.0}
        result = enrich_outlook(outlook(), {"observed_at_utc": 1000000,
                                           "complete": True, "events": [event]})
        item = result["strategy_assessments"][0]["economic_calendar_context"]["events"][0]
        self.assertIsNone(item["actual"])
        self.assertIsNone(item["actual_raw"])
        self.assertEqual(item["status"], "release_unverified")

    def test_reject_duplicate(self):
        source = outlook()
        source["strategy_assessments"][2] = source["strategy_assessments"][0].copy()
        with self.assertRaises(ValueError):
            enrich_outlook(source, None)


if __name__ == "__main__":
    unittest.main()
