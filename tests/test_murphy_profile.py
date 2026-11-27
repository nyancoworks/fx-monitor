"""Synthetic regression fixtures for the saved Issue #124 reporting path."""
from copy import deepcopy
import json
import unittest

from fx_system.monitor_pairs import PAIR_KEYS
from fx_system.murphy_report import _card
from fx_system.murphy_profile import TIMEFRAMES, assess, capture, refresh, selected
from fx_system.scheduled_outlook import build_scheduled_outlook
from fx_system.standard_technicals import SECONDS, prepare
from fx_system.strategy_report_export import build_strategy_report_export, restore_strategy_report_export
from fx_system.task_report import build_delivery_report, build_task_report
from fx_system.validate_strategy_snapshot import validate_strategy_snapshot

CLOCK = 1_795_766_400
SOURCE = {'source_repository': 'nyancoworks/fx-monitor', 'source_commit': 'a' * 40,
          'evaluated_at': CLOCK, 'run_id': 1}


def inputs():
    raw = {}
    for tf, step in SECONDS.items():
        candles = []
        for i in range(100):
            close = 1.2 + i * .0002
            candles.append({'timestamp': CLOCK - (100-i)*step, 'open': close,
                            'close': close, 'high': close+.00005, 'low': close-.00005})
        raw[tf] = candles
    pair = {'murphy_profile_version': 1}
    quality = {'evaluated_at': CLOCK, 'timeframes': {tf: {'ok': True} for tf in raw}}
    prepare(pair, raw, raw, quality)
    return pair, quality


class MurphyProfileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pair, cls.quality = inputs()
        cls.outlook = build_scheduled_outlook(dict.fromkeys(PAIR_KEYS, cls.pair),
            dict.fromkeys(PAIR_KEYS, cls.quality), evaluated_at=CLOCK)

    def test_live_frames_omit_retired_sma(self):
        from fx_system.indicator_history import indicator_health

        frames = self.pair['standard_technical_frames']
        for frame in frames.values():
            self.assertNotIn('sma', frame)
            self.assertIn('macd', frame)
            self.assertIn('rci', frame)
        health = indicator_health(frames)
        self.assertTrue(all(item['sb_available'] and 'sma200_required' not in item
                            for item in health.values()))

    def test_full_saved_projection_and_delivery(self):
        outlook = self.outlook
        snapshot = {'scheduled_outlook': outlook, 'evaluated_at': CLOCK}
        self.assertEqual(validate_strategy_snapshot(snapshot), [])
        self.assertEqual(outlook['assessment_counts']['review'], 32)
        self.assertEqual(len(selected(outlook)), 6)
        bundle = build_strategy_report_export(json.dumps(snapshot).encode(), SOURCE)
        self.assertEqual(bundle['status'], 'saved')
        self.assertNotIn('research_digest', bundle)
        blob = bundle['snapshot_git_blob_sha']
        restored = restore_strategy_report_export(bundle, SOURCE, blob)
        self.assertEqual(restored['scheduled_outlook']['strategy_assessments'], outlook['strategy_assessments'])
        report = build_task_report(bundle, None, {'source': SOURCE, 'snapshot_git_blob_sha': blob,
            'status': 'assigned', 'target_scheduled_for': CLOCK + 600}, None, outlook=outlook)
        delivery = build_delivery_report(report, {'source': SOURCE, 'snapshot_git_blob_sha': blob,
                           'validation': {'passed': True}, 'pairs': dict.fromkeys(PAIR_KEYS)})
        self.assertEqual(delivery['status'], 'saved')
        self.assertEqual(delivery['report_text'], report['report_text'])
        for card in report['sections']['swing']:
            record = next(r for r in selected(outlook) if r['pair'] == card['pair'] and r['strategy'] == 'swing')
            self.assertIn(f"{record['price_plan']['stop']:.8f}".rstrip('0'), card['text'])
            self.assertIn('W1↑ D1↑ H4↑ H1↑ M15↑', card['text'])
            self.assertIn('通貨強弱未確認', card['text'])
            self.assertIn('取得・鮮度未確認', card['text'])

    def test_auxiliary_changes_cannot_change_decisions_or_ranking(self):
        def judgment(rows):
            return [{k: row[k] for k in ('direction','grade','assessment','ready_to_consider','price_plan')}
                    for row in rows]

        revised = deepcopy(self.outlook)
        for row in revised['strategy_assessments']:
            for item in row['murphy_inputs'].values():
                if 'macd' in item:
                    item['macd'] = [{'histogram': -500}, {'histogram': 300}]
                    item['rci'] = {'9': {'value': -100}, '26': {'value': 100}, '52': {'value': 0}}
            row['economic_calendar_context'] = {'status': 'partial'}
            refresh(row)
        self.assertEqual(judgment(revised['strategy_assessments']), judgment(self.outlook['strategy_assessments']))
        self.assertEqual([(r['pair'], r['strategy']) for r in selected(revised)],
                         [(r['pair'], r['strategy']) for r in selected(self.outlook)])

    def test_quality_does_not_require_all_timeframes(self):
        quality = deepcopy(self.quality)
        for tf in ('w1', 'h1', 'm5'):
            quality['timeframes'][tf]['ok'] = False
        observations = capture(self.pair, quality, CLOCK)
        swing = assess(PAIR_KEYS[0], 'swing', CLOCK, observations, {})
        daytrade = assess(PAIR_KEYS[0], 'daytrade', CLOCK, observations, {})
        self.assertEqual(set(TIMEFRAMES['swing']), {'w1', 'd1', 'h4', 'h1', 'm15'})
        self.assertEqual(swing['assessment'], 'review')
        self.assertTrue(swing['ready_to_consider'])
        self.assertEqual(daytrade['assessment'], 'evaluation_pending')

    def test_stop_reached_independent_of_timing_and_structure(self):
        record = deepcopy(self.outlook['strategy_assessments'][0])
        plan = record['price_plan']
        self.assertLess(plan['stop'], plan['entry'])
        self.assertLess(plan['entry'], plan['target'])
        record['murphy_inputs']['m5']['close'] = plan['stop']
        self.assertEqual(refresh(record)['price_plan']['status'], 'stopped')
        self.assertFalse(record['ready_to_consider'])
        self.assertEqual(record['direction'], 'long')

    def test_card_uses_saved_strength_and_calendar_details(self):
        row = deepcopy(self.outlook['strategy_assessments'][0])
        base, quote = row['pair'][:3], row['pair'][3:]
        row['currency_strength_context'] = {
            'status': 'available', 'lookback_h1_bars': 24, 'relation': 'aligned',
            'difference': .3, 'display_scores': {base: .2, quote: -.1},
            'display_changes': {base: .02, quote: -.01},
        }
        row['economic_calendar_context'] = {
            'observed_at_utc': CLOCK, 'events': [{'currency': base, 'title': '合成指標',
                'timing': 'upcoming', 'scheduled_at_utc': CLOCK + 3600, 'impact': 'high'}],
        }
        card = _card(row, None, {'changed_fields': ['grade']})['text']
        for value in ('+0.2000 ↑', '-0.1000 ↓', '差 +0.3000', '評価に変化',
                      '合成指標', 'JST', '急変動に注意'):
            self.assertIn(value, card)

    def test_strength_changes_comparison_only(self):
        outlook = deepcopy(self.outlook)
        pairs = [row for row in outlook['strategy_assessments'] if row['strategy'] == 'swing']
        expected = pairs[-1]
        expected['currency_strength_context']['comparison_priority'] = 0
        outcome = selected(outlook)
        self.assertEqual(outcome[0]['pair'], expected['pair'])
        self.assertEqual(expected['direction'], 'long')
        self.assertEqual(expected['assessment'], 'review')


if __name__ == '__main__':
    unittest.main()
