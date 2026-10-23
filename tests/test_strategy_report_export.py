"""Synthetic snapshots and a local bare Git remote only."""
import base64
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fx_system.private_runtime import save_snapshot
from fx_system.scheduled_outlook import build_scheduled_outlook
from fx_system.strategy_report import render_strategy_report
from fx_system.strategy_report_export import build_strategy_report_export, restore_strategy_report_export
from fx_system.validate_strategy_snapshot import validate_strategy_snapshot
from test_range_scenario import sample, CLOCK


SOURCE = {'source_repository': 'nyancoworks/fx-monitor', 'source_commit': 'a'*40,
          'run_id': 123, 'evaluated_at': CLOCK}


def snapshot():
    data, _ = sample()
    quality = {'timeframes': {'h1': {'ok': True, 'count': 20},
                             'm5': {'ok': True, 'count': 5, 'age_minutes': 0}}}
    data['decision_quality'] = {**deepcopy(quality), 'evaluated_at': CLOCK}
    data['technical'] = {'h1': {'status': 'ok', 'structure': 'mixed'}}
    calendar = {'observed_at_utc': CLOCK, 'complete': True,
        'attribution_url': 'https://example.invalid/synthetic', 'events': [
            {'currency': 'USD', 'scheduled_at_utc': CLOCK+3600, 'observed_at_utc': CLOCK,
             'reference_only': True, 'title': 'Synthetic calendar reference', 'actual': 99}]}
    outlook = build_scheduled_outlook({'EURUSD': data}, {'EURUSD': quality},
                                     evaluated_at=CLOCK, economic_calendar=calendar)
    return {'generated_at': 2, 'evaluated_at': CLOCK, 'scheduled_outlook': outlook,
            'pairs': {'synthetic': {'raw_unrelated_price_input': 'not part of report view'}}}


class StrategyReportExportTests(unittest.TestCase):
    def test_lossless_32_and_original_row_identity_with_readable_private_report(self):
        saved = snapshot(); original = deepcopy(saved); raw = json.dumps(saved).encode()
        bundle = build_strategy_report_export(raw, SOURCE)
        self.assertEqual(bundle['status'], 'saved')
        expected_blob = hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        self.assertEqual(bundle['snapshot_git_blob_sha'], expected_blob)
        restored = restore_strategy_report_export(bundle, SOURCE, expected_blob)
        self.assertEqual(validate_strategy_snapshot(restored), [])
        self.assertEqual(restored['scheduled_outlook']['strategy_assessments'],
                         saved['scheduled_outlook']['strategy_assessments'])
        for old, new in zip(saved['scheduled_outlook']['rows'], restored['scheduled_outlook']['rows']):
            self.assertEqual(old['strategy_assessments'], new['strategy_assessments'])
        self.assertEqual(len(bundle['assessment_summaries']), 32)
        self.assertEqual(bundle['assessment_counts'], saved['scheduled_outlook']['assessment_counts'])
        self.assertIn('32戦略', bundle['report_text'])
        self.assertIn('Synthetic calendar reference', bundle['report_text'])
        self.assertEqual(bundle['report_text'], render_strategy_report(saved))
        self.assertEqual(bundle['review_context_version'], 2)
        self.assertEqual(bundle['review_context_text'], render_strategy_report(
            saved, include_all_reviews=True, complete_evidence=True))
        self.assertNotIn('raw_unrelated_price_input', json.dumps(restored))
        self.assertLess(len(json.dumps(bundle).encode()), 900000)
        self.assertEqual(saved, original)
        self.assertEqual(bundle, build_strategy_report_export(raw, SOURCE))

    def test_original_row_mismatch_or_missing_32_cannot_be_healed_by_projection(self):
        for index in range(2):
            broken = snapshot()
            if index == 0:
                broken['scheduled_outlook']['rows'][0]['strategy_assessments']['swing']['grade_reason'] = 'disagreement'
            else:
                broken['scheduled_outlook']['strategy_assessments'].pop()
            bundle = build_strategy_report_export(json.dumps(broken).encode(), SOURCE)
            self.assertEqual(bundle['status'], 'unavailable')
            self.assertIsNone(bundle['payload_base64']); self.assertIsNone(bundle['report_text'])

    def test_legacy_review_without_valid_direction_is_not_rendered_as_sell(self):
        for direction in (None, '', 'sideways', False, ['long']):
            with self.subTest(direction=direction):
                saved = snapshot()
                record = next(r for r in saved['scheduled_outlook']['strategy_assessments']
                              if r['assessment'] == 'review')
                # Older supported records can omit these optional contexts;
                # core direction validity must not depend on their validators.
                for key in ('scenario_conditions', 'range_context', 'scenario_type',
                            'currency_strength_context'):
                    record.pop(key, None)
                record['direction'] = direction
                row = next(r for r in saved['scheduled_outlook']['rows'] if r['pair'] == record['pair'])
                row['strategy_assessments'][record['strategy']] = deepcopy(record)
                before = deepcopy(saved)
                self.assertIn('scheduled strategy review direction invalid', validate_strategy_snapshot(saved))
                with self.assertRaises(ValueError):
                    render_strategy_report(saved)
                bundle = build_strategy_report_export(json.dumps(saved).encode(), SOURCE)
                self.assertEqual(bundle['status'], 'unavailable')
                self.assertIsNone(bundle['report_text'])
                self.assertEqual(saved, before)

    def test_legacy_buy_and_sell_reviews_remain_readable(self):
        for direction in ('long', 'short'):
            saved = snapshot()
            record = next(r for r in saved['scheduled_outlook']['strategy_assessments']
                          if r['assessment'] == 'review')
            for key in ('scenario_conditions', 'range_context', 'scenario_type',
                        'currency_strength_context'):
                record.pop(key, None)
            record['direction'] = direction
            row = next(r for r in saved['scheduled_outlook']['rows'] if r['pair'] == record['pair'])
            row['strategy_assessments'][record['strategy']] = deepcopy(record)
            self.assertEqual(validate_strategy_snapshot(saved), [])
            bundle = build_strategy_report_export(json.dumps(saved).encode(), SOURCE)
            self.assertEqual(bundle['status'], 'saved')
            self.assertIn('買い方向' if direction == 'long' else '売り方向', bundle['report_text'])
            restore_strategy_report_export(bundle, SOURCE, bundle['snapshot_git_blob_sha'])

    def test_unavailable_current_run_does_not_reuse_prior_report(self):
        for raw in (b'{}', b'{invalid', json.dumps({'evaluated_at': CLOCK-1}).encode()):
            bundle = build_strategy_report_export(raw, SOURCE)
            self.assertEqual(bundle['status'], 'unavailable')
            self.assertEqual(bundle['source'], SOURCE)
            self.assertEqual(bundle['assessment_summaries'], [])
            with self.assertRaises(ValueError):
                restore_strategy_report_export(bundle, SOURCE, bundle['snapshot_git_blob_sha'])
        with patch('fx_system.strategy_report_export.render_strategy_report', side_effect=RuntimeError('synthetic')):
            self.assertEqual(build_strategy_report_export(json.dumps(snapshot()).encode(), SOURCE)['status'], 'unavailable')

    def test_both_encoded_and_decoded_size_limits_are_enforced(self):
        raw = json.dumps(snapshot()).encode()
        for name in ('MAX_EXPORT_BYTES', 'MAX_PAYLOAD_BYTES'):
            with patch('fx_system.strategy_report_export.'+name, 20):
                self.assertEqual(build_strategy_report_export(raw, SOURCE)['status'], 'unavailable')
        bundle = build_strategy_report_export(raw, SOURCE)
        with patch('fx_system.strategy_report_export.MAX_PAYLOAD_BYTES', 20):
            with self.assertRaises(ValueError):
                restore_strategy_report_export(bundle, SOURCE, bundle['snapshot_git_blob_sha'])

    def test_wrong_source_blob_clock_and_readable_report_tampering_are_rejected(self):
        bundle = build_strategy_report_export(json.dumps(snapshot()).encode(), SOURCE)
        for change in ({'source': {**SOURCE, 'run_id': 124}}, {'snapshot_git_blob_sha': 'b'*40},
                       {'report_text': 'changed'}, {'review_context_text': 'changed'}, {'assessment_summaries': []},
                       {'assessment_counts': {'review': 32}}, {'payload_sha256': '0'*64},
                       {'payload_byte_length': 1}, {'payload_base64': '%%%'}):
            with self.assertRaises(ValueError):
                restore_strategy_report_export({**bundle, **change}, SOURCE, bundle['snapshot_git_blob_sha'])
        for change in ({'run_id': True}, {'source_commit': 'bad'}, {'source_repository': 'other/repo'}):
            with self.assertRaises(ValueError):
                build_strategy_report_export(b'{}', {**SOURCE, **change})

    def test_truncated_gzip_and_concatenated_members_are_rejected(self):
        bundle = build_strategy_report_export(json.dumps(snapshot()).encode(), SOURCE)
        packed = base64.b64decode(bundle['payload_base64'])
        for value in (packed[:-1], packed+gzip.compress(b'{}'), packed+b'trailing'):
            bad = {**bundle, 'payload_base64': base64.b64encode(value).decode()}
            with self.assertRaises(ValueError):
                restore_strategy_report_export(bad, SOURCE, bundle['snapshot_git_blob_sha'])

    def test_all_review_context_is_available_without_expanding_default_report(self):
        from fx_system.monitor_pairs import PAIR_KEYS
        from fx_system.strategy_report import report_records, _label
        from collections import Counter
        data, _ = sample()
        quality = {'timeframes': {'h1': {'ok': True, 'count': 20},
                                 'm5': {'ok': True, 'count': 5, 'age_minutes': 0}}}
        data['decision_quality'] = {**deepcopy(quality), 'evaluated_at': CLOCK}
        data['technical'] = {'h1': {'status': 'ok', 'structure': 'mixed'}}
        outlook = build_scheduled_outlook({p: deepcopy(data) for p in PAIR_KEYS},
                                          {p: deepcopy(quality) for p in PAIR_KEYS}, evaluated_at=CLOCK)
        saved = {'evaluated_at': CLOCK, 'scheduled_outlook': outlook}; before = deepcopy(saved)
        bundle = build_strategy_report_export(json.dumps(saved).encode(), SOURCE)
        reviews = [r for r in outlook['strategy_assessments'] if r['assessment'] == 'review']
        shown = report_records(outlook)
        self.assertGreater(len(reviews), len(shown))
        self.assertTrue(all(count <= 3 for count in Counter(r['strategy'] for r in shown).values()))
        for record in reviews:
            self.assertIn(_label(record)+'｜', bundle['review_context_text'])
        for record in [r for r in reviews if r not in shown]:
            self.assertNotIn(_label(record)+'｜', bundle['report_text'])
        self.assertIn('非掲載の検討候補：0', bundle['review_context_text'])
        restore_strategy_report_export(bundle, SOURCE, bundle['snapshot_git_blob_sha'])
        legacy = deepcopy(bundle); legacy.pop('review_context_text'); legacy.pop('review_context_version')
        self.assertEqual(restore_strategy_report_export(legacy, SOURCE, bundle['snapshot_git_blob_sha']),
                         restore_strategy_report_export(bundle, SOURCE, bundle['snapshot_git_blob_sha']))
        self.assertEqual(saved, before)

    def test_complete_comparison_keeps_late_evidence_for_shown_and_omitted_reviews(self):
        from fx_system.monitor_pairs import PAIR_KEYS
        from fx_system.strategy_report import report_records, _label
        data, _ = sample()
        quality = {'timeframes': {'h1': {'ok': True, 'count': 20},
                                 'm5': {'ok': True, 'count': 5, 'age_minutes': 0}}}
        data['decision_quality'] = {**deepcopy(quality), 'evaluated_at': CLOCK}
        data['technical'] = {'h1': {'status': 'ok', 'structure': 'mixed'}}
        outlook = build_scheduled_outlook({p: deepcopy(data) for p in PAIR_KEYS},
                                          {p: deepcopy(quality) for p in PAIR_KEYS}, evaluated_at=CLOCK)
        reviews = [r for r in outlook['strategy_assessments'] if r['assessment'] == 'review']
        for index, record in enumerate(reviews):
            record['reasons'] = [f'synthetic reason {index}/{n}' for n in range(4)]
            record['opposing_evidence'] = [f'synthetic opposition {index}/{n}' for n in range(4)]
            row = next(r for r in outlook['rows'] if r['pair'] == record['pair'])
            row['strategy_assessments'][record['strategy']] = deepcopy(record)
        saved = {'evaluated_at': CLOCK, 'scheduled_outlook': outlook}; before = deepcopy(saved)
        bundle = build_strategy_report_export(json.dumps(saved).encode(), SOURCE)
        self.assertEqual(bundle['status'], 'saved')
        shown = report_records(outlook)
        self.assertTrue(shown and len(reviews) > len(shown))
        for record in reviews:
            block = bundle['review_context_text'].split(_label(record)+'｜', 1)[1].split('\n\n', 1)[0]
            for evidence in record['reasons'] + record['opposing_evidence']:
                self.assertIn(evidence, block)
            for evidence in record['reasons'][2:] + record['opposing_evidence'][2:]:
                self.assertNotIn(evidence, bundle['report_text'])
        self.assertEqual(saved, before)
        self.assertEqual(restore_strategy_report_export(bundle, SOURCE, bundle['snapshot_git_blob_sha'])
                         ['scheduled_outlook']['strategy_assessments'], outlook['strategy_assessments'])

    def test_legacy_partial_context_restores_without_claiming_complete_evidence(self):
        saved = snapshot()
        bundle = build_strategy_report_export(json.dumps(saved).encode(), SOURCE)
        legacy = deepcopy(bundle); legacy.pop('review_context_version')
        legacy['review_context_text'] = render_strategy_report(saved, include_all_reviews=True)
        restore_strategy_report_export(legacy, SOURCE, bundle['snapshot_git_blob_sha'])
        for version in (True, 0, 3, '2'):
            with self.assertRaises(ValueError):
                restore_strategy_report_export({**bundle, 'review_context_version': version},
                                               SOURCE, bundle['snapshot_git_blob_sha'])
        missing = deepcopy(bundle); missing.pop('review_context_text')
        with self.assertRaises(ValueError):
            restore_strategy_report_export(missing, SOURCE, bundle['snapshot_git_blob_sha'])

    def test_private_atomic_save_shares_push_with_original_and_failed_projection_advances(self):
        with tempfile.TemporaryDirectory() as folder:
            remote = Path(folder)/'remote.git'; root = Path(folder)/'checkout'
            subprocess.run(['git', 'init', '--bare', str(remote)], check=True, capture_output=True)
            root.mkdir()
            def git(*args):
                return subprocess.run(['git', '-C', str(root), *args], check=True,
                                      capture_output=True, text=True).stdout.strip()
            git('init', '-b', 'main'); git('remote', 'add', 'origin', str(remote))
            (root/'data').mkdir(); (root/'data/latest.json').write_text('{"generated_at":1}')
            git('add', '.'); git('-c', 'user.name=synthetic', '-c', 'user.email=synthetic@localhost', 'commit', '-m', 'initial')
            git('push', 'origin', 'HEAD:main'); first = git('rev-parse', 'HEAD')
            raw = json.dumps(snapshot()).encode(); (root/'data/latest.json').write_bytes(raw)
            (root/'data/cache.json').write_text('{}')
            save_snapshot(root, '123', 'a'*40)
            self.assertEqual(git('rev-list', '--count', first+'..HEAD'), '1')
            original_commit = git('rev-parse', 'HEAD')
            bundle = json.loads(git('show', 'HEAD:data/strategy-report.json'))
            source = json.loads(git('show', 'HEAD:data/source.json'))
            sha = git('rev-parse', 'HEAD:data/latest.json')
            restore_strategy_report_export(bundle, source, sha)
            self.assertEqual((root/'data/latest.json').read_bytes(), raw)
            remote_bundle = subprocess.run(['git', '--git-dir', str(remote), 'show', 'main:data/strategy-report.json'],
                                           check=True, capture_output=True, text=True).stdout
            self.assertEqual(json.loads(remote_bundle), bundle)
            self.assertEqual((root/'data/strategy-report.json').stat().st_mode & 0o777, 0o600)
            (root/'data/latest.json').write_text(json.dumps({'generated_at': 3, 'evaluated_at': CLOCK}))
            save_snapshot(root, '124', 'a'*40)
            later = json.loads(git('show', 'HEAD:data/strategy-report.json'))
            self.assertEqual(later['source']['run_id'], 124)
            self.assertEqual(later['status'], 'unavailable'); self.assertIsNone(later['report_text'])
            self.assertEqual(git('show', original_commit+':data/latest.json'), raw.decode())

    def test_symlink_projection_cannot_write_outside_private_root(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'private'; (root/'data').mkdir(parents=True)
            outside = Path(folder)/'untouched'; outside.write_text('original')
            (root/'data/strategy-report.json').symlink_to(outside)
            (root/'data/latest.json').write_text(json.dumps(snapshot()))
            with patch('fx_system.private_runtime.git', return_value='{"generated_at":1}'):
                with self.assertRaises(ValueError):
                    save_snapshot(root, '123', 'a'*40)
            self.assertEqual(outside.read_text(), 'original')


if __name__ == '__main__':
    unittest.main()
