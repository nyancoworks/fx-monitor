"""Synthetic task results only; no mailbox, automation or market access."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import unittest

from diagnostics.task_result_email import prepare_task_result_email, MAX_RESULT_BYTES

NOW = datetime(2026, 1, 2, 3, 5, tzinfo=timezone.utc)
SLOT = '2026-01-02T03:00:00Z'


def task():
    ref = {'type': 'chatgpt', 'id': 'synthetic-chat'}
    return {'id': 'synthetic-task', 'run_details': {
        'last_run': {'id': 'synthetic-run', 'recorded_status': 'completed',
            'scheduled_for': SLOT, 'started_at': '2026-01-02T02:59:00Z',
            'completed_at': '2026-01-02T03:01:00Z', 'chat_ref': ref},
        'latest_result': {'run_id': 'synthetic-run', 'scheduled_for': SLOT,
            'created_at': '2026-01-02T03:00:59Z', 'completed_at': '2026-01-02T03:01:00Z',
            'chat_ref': deepcopy(ref), 'content_truncated': False, 'is_failure_message': False,
            'requires_user_action': False,
            'content_text': '# 合成結果\n\n**条件**を待つ。\n出典：urlSynthetic sourcehttps://example.com/source?a=1&b=2\n'}}}


def prepare(value, **kwargs):
    return prepare_task_result_email(value, expected_task_id='synthetic-task',
        expected_run_id='synthetic-run', expected_scheduled_for=SLOT, now=NOW, **kwargs)


class TaskResultEmailTests(unittest.TestCase):
    def test_full_text_source_identity_links_and_input_preservation(self):
        value = task(); before = deepcopy(value); result = prepare(value)
        source = value['run_details']['latest_result']['content_text']
        self.assertEqual(result['source_text'], source)
        self.assertEqual(result['source_result_sha256'], hashlib.sha256(source.encode()).hexdigest())
        self.assertEqual(result['email_text'], '# 合成結果\n\n**条件**を待つ。\n出典：Synthetic source <https://example.com/source?a=1&b=2>\n')
        self.assertEqual(result['payload']['parts'][0]['body']['content'], result['email_text'])
        html = result['payload']['parts'][1]['body']['content']
        self.assertIn('href="https://example.com/source?a=1&amp;b=2"', html)
        self.assertIn('2026-01-02 12:00 JST', result['subject'])
        self.assertIsNone(result['recipient']); self.assertEqual(result['delivery_status'], 'not_sent')
        self.assertEqual(value, before)

    def test_stale_mixed_truncated_failure_and_future_results_rejected(self):
        changes = [lambda t: t.update(id='other-task'),
            lambda t: t['run_details']['last_run'].update(recorded_status='in_progress'),
            lambda t: t['run_details']['latest_result'].update(run_id='old-run'),
            lambda t: t['run_details']['latest_result'].update(content_truncated=True),
            lambda t: t['run_details']['latest_result'].update(is_failure_message=True),
            lambda t: t['run_details']['latest_result'].update(requires_user_action=True),
            lambda t: t['run_details']['latest_result'].update(created_at='2026-01-01T03:00:00Z'),
            lambda t: t['run_details']['last_run'].update(completed_at='2026-01-03T03:00:00Z'),
            lambda t: t['run_details']['latest_result'].update(scheduled_for='2026-01-01T03:00:00Z'),
            lambda t: t['run_details']['latest_result'].update(chat_ref={'type': 'chatgpt', 'id': 'other-chat'}),
            lambda t: t['run_details']['latest_result'].update(created_at='2026-01-02T03:00:59')]
        for change in changes:
            with self.subTest(change=changes.index(change)):
                value = task(); change(value)
                with self.assertRaises(ValueError): prepare(value)

    def test_same_run_cannot_be_reprepared_from_reserved_state_even_if_body_changed(self):
        value = task(); first = prepare(value)
        value['run_details']['latest_result']['content_text'] = '合成の更新された本文'
        self.assertEqual(prepare(value)['delivery_key'], first['delivery_key'])
        with self.assertRaises(ValueError): prepare(value, reserved_keys=[first['delivery_key']])

    def test_html_is_escaped_and_unknown_citations_not_silently_dropped(self):
        value = task(); value['run_details']['latest_result']['content_text'] += '<script>synthetic()</script>'
        html = prepare(value)['payload']['parts'][1]['body']['content']
        self.assertIn('&lt;script&gt;', html); self.assertNotIn('<script>', html)
        for text in ('未解決 citesynthetic-ref', 'urlSourcejavascript:synthetic()',
                     'urlSourcehttps://user:pass@example.com/', ' ', 'x'*(MAX_RESULT_BYTES+1)):
            value['run_details']['latest_result']['content_text'] = text
            with self.assertRaises(ValueError): prepare(value)


if __name__ == '__main__':
    unittest.main()
