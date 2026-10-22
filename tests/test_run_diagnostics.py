"""Synthetic failure evidence, confidentiality and bounded private persistence."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fx_system.run_diagnostics import build_diagnostics, LIMIT
from fx_system.private_runtime import save_snapshot

SOURCE = {'source_repository': 'nyancoworks/fx-monitor', 'source_commit': 'a'*40,
          'run_id': 123, 'evaluated_at': 600}


def snapshot():
    return {'generated_at': 500, 'evaluated_at': 600,
        'pairs': {'EURUSD': {
            'decision_data': {'raw': {'m5': [{'timestamp': 300, 'open': 123.456,
                'high': 125, 'low': 120, 'close': 124}]}, 'provenance': {'m5:300': 'Yahoo'}},
            'decision_quality': {'ready': False, 'intraday_monitoring_ready': False,
                                 'reasons': ['m5: source unavailable']},
            'acquisition': {'m5': {'status': 'failed', 'attempted': True}}}},
        'quality': {'EURUSD': {'provider_errors': {'m5': 'synthetic primary error'}}}}


class RunDiagnosticsTests(unittest.TestCase):
    def test_failed_validation_and_provider_evidence_survive_without_raw_prices(self):
        data = snapshot(); before = json.dumps(data)
        raw = json.dumps(data).encode()
        saved = build_diagnostics(raw, SOURCE, returncode=1,
            validation_log='SNAPSHOT_VALIDATION {"passed":false,"failures":["EURUSD: NOT_READY"]}\n')
        report = json.loads(saved)
        self.assertEqual(report['validation']['outcome'], 'failure')
        self.assertFalse(report['validation']['passed'])
        self.assertEqual(report['validation']['failures'], ['EURUSD: NOT_READY'])
        self.assertEqual(report['pairs']['EURUSD']['sources']['m5']['latest_source'], 'Yahoo')
        self.assertEqual(report['pairs']['EURUSD']['primary_errors']['m5'], 'synthetic primary error')
        self.assertNotIn(b'123.456', saved)
        self.assertEqual(json.dumps(data), before)

    def test_missing_invalid_or_ambiguous_report_never_becomes_passed(self):
        raw = json.dumps(snapshot()).encode()
        cases = [('', None), ('SNAPSHOT_VALIDATION nope', 1),
                 ('SNAPSHOT_VALIDATION {"passed":true,"failures":[]}', 1),
                 ('SNAPSHOT_VALIDATION {"passed":true,"failures":[]}', False),
                 ('SNAPSHOT_VALIDATION {}\nSNAPSHOT_VALIDATION {}', 0)]
        for log, rc in cases:
            report = json.loads(build_diagnostics(raw, SOURCE, returncode=rc, validation_log=log))
            self.assertIsNone(report['validation']['passed'])
            self.assertNotEqual(report['validation']['report_status'], 'available')
        with self.assertRaises(ValueError):
            build_diagnostics(raw, {**SOURCE, 'evaluated_at': 601})

    def test_configured_credentials_are_redacted_including_escaped_text(self):
        for secret in ('synthetic-quote"and-newline\nsecret', 'long-synthetic-secret'*100):
            data = snapshot(); data['quality']['EURUSD']['provider_errors']['m5'] = secret
            saved = build_diagnostics(json.dumps(data).encode(), SOURCE,
                                      env={'SYNTHETIC_TOKEN': secret})
            report = json.loads(saved)
            self.assertEqual(report['pairs']['EURUSD']['primary_errors']['m5'], '[REDACTED]')

    def test_large_failure_report_is_bounded_without_hiding_failed_status(self):
        data = snapshot()
        for i in range(16):
            from fx_system.monitor_pairs import PAIR_KEYS
            data['pairs'][PAIR_KEYS[i]] = {**data['pairs']['EURUSD'],
                'decision_quality': {'reasons': ['x'*512]*32}}
        log = 'SNAPSHOT_VALIDATION '+json.dumps({'passed': False, 'failures': ['y'*512]*200})
        saved = build_diagnostics(json.dumps(data).encode(), SOURCE, returncode=1, validation_log=log)
        report = json.loads(saved)
        self.assertLessEqual(len(saved), LIMIT)
        self.assertTrue(report['truncated'])
        self.assertFalse(report['validation']['passed'])
        self.assertEqual(report['validation']['failure_count'], 200)

    def test_diagnostic_and_validation_log_symlinks_cannot_escape_private_checkout(self):
        from test_strength_export import sample
        for target_kind in ('diagnostic', 'validation_log'):
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)/'checkout'; (root/'data').mkdir(parents=True)
                outside = Path(folder)/'untouched'; outside.write_text('original')
                (root/'data/latest.json').write_text(json.dumps(sample()))
                if target_kind == 'diagnostic':
                    (root/'data/run-diagnostics.json').symlink_to(outside)
                else:
                    (root/'.private-run/123').mkdir(parents=True)
                    (root/'.private-run/123/validate.log').symlink_to(outside)
                with patch('fx_system.private_runtime.git', return_value='{"generated_at":1}'):
                    with self.assertRaises(ValueError): save_snapshot(root, '123', 'a'*40)
                self.assertEqual(outside.read_text(), 'original')


if __name__ == '__main__': unittest.main()
