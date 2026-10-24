"""Synthetic-only economic calendar report tests."""
import unittest
from copy import deepcopy
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

    def test_versioned_value_evidence_distinguishes_forecast_from_prior(self):
        event = dict(currency='USD', title='Synthetic release', scheduled_at_utc=100,
                     timing='past_release_window', actual_raw='1.2', consensus_raw=None,
                     prior_raw='1.1', period='Synthetic month', unit='% m/m')
        row = {'economic_calendar_context': {'status': 'available',
               'value_evidence_version': 1, 'events': [event]}}
        original = deepcopy(row)
        text = '\n'.join(calendar_lines(row, str))
        self.assertIn('値の対象：Synthetic month｜単位：% m/m', text)
        self.assertIn('予想との差：未評価（予想が未記録）', text)
        self.assertIn('前回値は予想値とは別', text)
        self.assertEqual(row, original)

    def test_nonblank_values_and_provider_flag_do_not_verify_comparison(self):
        row = {'economic_calendar_context': {'status': 'available',
               'value_evidence_version': 1, 'events': [dict(currency='USD',
               scheduled_at_utc=100, actual_raw='0', consensus_raw='0', prior_raw='0',
               numeric_comparison_verified=True)]}}
        text = '\n'.join(calendar_lines(row, str))
        self.assertIn('同じ期間・単位の比較根拠が未検証', text)
        self.assertIn('値の対象：未記録｜単位：未記録', text)
        self.assertIn('改定の有無は未確認', text)
        event = row['economic_calendar_context']['events'][0]
        event.update(actual_raw=' ', consensus_raw='\t')
        self.assertIn('実績・予想が未記録', '\n'.join(calendar_lines(row, str)))

    def test_absent_unknown_or_boolean_version_keeps_legacy_rendering(self):
        event = dict(currency='USD', scheduled_at_utc=100, actual_raw='synthetic',
                     consensus_raw=None, prior_raw=None)
        row = {'economic_calendar_context': {'status': 'available', 'events': [event]}}
        legacy = calendar_lines(row, str)
        self.assertFalse(any('値の対象' in line for line in legacy))
        for version in (None, 3, True, '1'):
            row['economic_calendar_context']['value_evidence_version'] = version
            self.assertEqual(calendar_lines(row, str), legacy)

    def test_recent_acquisition_does_not_override_stale_or_degraded_evidence(self):
        row = {'evaluated_at': 1000, 'economic_calendar_context': {
            'status': 'partial', 'observed_at_utc': 940, 'acquisition_age_seconds': 0,
            'value_evidence_version': 2, 'events': [dict(currency='USD',
                scheduled_at_utc=500, freshness='stale', actual_raw='0',
                consensus_raw=None, prior_raw='1',
                source_health={'status':'degraded','observed_at_utc':940})]}}
        original = deepcopy(row)
        text = '\n'.join(calendar_lines(row, str))
        self.assertIn('保存取得から60秒', text)
        self.assertIn('内容の最新性を保証しない', text)
        self.assertIn('古い保存情報', text)
        self.assertIn('取得状態が劣化', text)
        self.assertIn('予想値は未記録。前回値から補完しない', text)
        self.assertIn('予定時刻と実際の公表時刻は別', text)
        self.assertEqual(row, original)
        row['economic_calendar_context']['observed_at_utc'] = 1001
        self.assertIn('経過時間は未確認', '\n'.join(calendar_lines(row, str)))

    def test_nonblank_forecast_does_not_establish_pre_release_vintage(self):
        row = {'economic_calendar_context': {'status': 'available',
               'value_evidence_version': 2, 'events': [dict(currency='USD',
               scheduled_at_utc=100, actual_raw='0', consensus_raw='0', prior_raw='0',
               period='Synthetic month', unit='Synthetic unit',
               numeric_comparison_verified=True)]}}
        text = '\n'.join(calendar_lines(row, str))
        self.assertIn('同じ期間・単位の比較根拠が未検証', text)
        self.assertIn('発表前の市場予想として確認できた時刻・出典は未検証', text)
        self.assertIn('初報・改定履歴は未検証', text)


if __name__ == "__main__":
    unittest.main()
