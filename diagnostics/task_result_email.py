"""Prepare an exact recorded task result for private email; never send or fetch.

Callers pin the expected task/run/slot and persist a delivery reservation before
creating a draft or sending. This pure helper is not a scheduler or an outbox.
"""
from datetime import datetime, timezone
from email.utils import getaddresses
import hashlib
import html
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

MAX_RESULT_BYTES = 128 * 1024
URL_CITATION = re.compile(r'url([^]+)([^]+)')
WEB_URL = re.compile(r'https?://[^\s<>"\']+')


def _instant(value):
    if not isinstance(value, str):
        raise ValueError('invalid task result clock')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('invalid task result clock')
    return parsed.astimezone(timezone.utc)


def _safe_url(value):
    url = urlsplit(value)
    if (url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password
            or url.port not in (None, 80, 443) or any(ord(c) <= 32 for c in value)):
        raise ValueError('unresolved task source link')
    return value


def _expand_sources(source):
    def expand(match):
        label, url = match.groups()
        return label+' <'+_safe_url(url)+'>'
    text = URL_CITATION.sub(expand, source)
    if any(marker in text for marker in ('', '', '')):
        raise ValueError('unresolved task source citation')
    return text


def _html_body(text):
    parts = []; cursor = 0
    for match in WEB_URL.finditer(text):
        url = _safe_url(match.group())
        parts.extend((html.escape(text[cursor:match.start()]),
            '<a href="'+html.escape(url, quote=True)+'">'+html.escape(url)+'</a>'))
        cursor = match.end()
    parts.append(html.escape(text[cursor:]))
    # Preserve every line and Markdown character; do not re-summarize or execute
    # HTML embedded in a result. This is not a replica of ChatGPT's visual UI.
    return '<html><body><pre style="white-space:pre-wrap;overflow-wrap:anywhere;font-family:system-ui,sans-serif">'+''.join(parts)+'</pre></body></html>'


def prepare_task_result_email(task, *, expected_task_id, expected_run_id,
                              expected_scheduled_for, now, reserved_keys=()):
    """Validate one completed run and return private MIME plus content identity.

    reserved_keys must come from durable, atomically reserved delivery state.
    Reusing a run stays blocked even if its body changed. An unknown send outcome
    must be reconciled, never cleared here for an automatic retry.
    """
    try:
        if (not isinstance(task, dict) or task.get('id') != expected_task_id
                or any(not isinstance(v, str) or re.fullmatch(r'[A-Za-z0-9_-]{1,200}', v) is None
                       for v in (expected_task_id, expected_run_id))
                or not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None
                or not isinstance(reserved_keys, (tuple, list, set))
                or any(not isinstance(k, str) or re.fullmatch('[0-9a-f]{64}', k) is None for k in reserved_keys)):
            raise ValueError
        details = task['run_details']; run = details['last_run']; result = details['latest_result']
        if (run['recorded_status'] != 'completed' or run['id'] != expected_run_id
                or result['run_id'] != expected_run_id
                or result['content_truncated'] is not False
                or result['is_failure_message'] is not False
                or result['requires_user_action'] is not False
                or not isinstance(run.get('chat_ref'), dict)
                or not isinstance(run['chat_ref'].get('id'), str) or not run['chat_ref']['id']
                or run['chat_ref'] != result.get('chat_ref')):
            raise ValueError
        slot = _instant(expected_scheduled_for)
        start, created, end = map(_instant, (run['started_at'], result['created_at'], run['completed_at']))
        current = now.astimezone(timezone.utc)
        if (slot != _instant(run['scheduled_for']) or slot != _instant(result['scheduled_for'])
                or not start <= created <= end <= current or slot > current):
            raise ValueError
        if result.get('completed_at') is not None and not created <= _instant(result['completed_at']) <= end:
            raise ValueError
        source = result['content_text']
        if (not isinstance(source, str) or not source.strip()
                or len(source.encode('utf-8')) > MAX_RESULT_BYTES
                or any(ord(c) < 32 and c not in '\n\r\t' for c in source)):
            raise ValueError
        delivery_key = hashlib.sha256((expected_task_id+'\0'+expected_run_id).encode()).hexdigest()
        if delivery_key in reserved_keys:
            raise ValueError('task result already reserved')
        text = _expand_sources(source)
        rendered = _html_body(text)
    except (KeyError, TypeError, AttributeError, ValueError, OverflowError, UnicodeError):
        raise ValueError('task result is not eligible for email preparation') from None
    return {'schema': 'recorded_task_result_email_v1', 'task_id': expected_task_id,
        'run_id': expected_run_id, 'scheduled_for': expected_scheduled_for,
        'delivery_key': delivery_key, 'source_text': source,
        'source_result_sha256': hashlib.sha256(source.encode('utf-8')).hexdigest(),
        'email_text': text, 'prepared_at_utc': current.isoformat(),
        'subject': 'FX Monitor｜'+slot.astimezone(ZoneInfo('Asia/Tokyo')).strftime('%Y-%m-%d %H:%M JST')+' タスク結果',
        'payload': {'mime_type': 'multipart/alternative', 'parts': [
            {'mime_type': 'text/plain', 'charset': 'utf-8', 'body': {'content': text}},
            {'mime_type': 'text/html', 'charset': 'utf-8', 'body': {'content': rendered}}]},
        'regenerated_analysis': False, 'delivery_status': 'not_sent',
        'recipient': None}


def reconcile_task_result_email(prepared, messages, *, expected_recipient,
                                expected_subject, provider_message_id=None):
    """Inspect private Gmail full readbacks without sending or allowing retries.

    Search matches alone cannot bind a message to a run. Only an ID recorded from
    the send response, plus an exact sent-copy readback, verifies that operation.
    Even that is not evidence of recipient arrival or reading. Persist the send
    reservation independently; neither an empty search nor this result clears it.
    """
    try:
        source = prepared['source_text']
        task_id, run_id = prepared['task_id'], prepared['run_id']
        key = hashlib.sha256((task_id+'\0'+run_id).encode()).hexdigest()
        text = _expand_sources(source)
        bodies = {'text/plain': text, 'text/html': _html_body(text)}
        if (prepared['schema'] != 'recorded_task_result_email_v1'
                or prepared['delivery_key'] != key
                or prepared['source_result_sha256'] != hashlib.sha256(source.encode()).hexdigest()
                or prepared['email_text'] != text
                or prepared['payload'] != {'mime_type': 'multipart/alternative', 'parts': [
                    {'mime_type': kind, 'charset': 'utf-8', 'body': {'content': body}}
                    for kind, body in bodies.items()]}
                or not isinstance(expected_recipient, str)
                or getaddresses([expected_recipient]) != [('', expected_recipient)]
                or expected_recipient.count('@') != 1
                or any(c.isspace() for c in expected_recipient)
                or not isinstance(expected_subject, str) or not expected_subject.strip()
                or any(ord(c) < 32 for c in expected_subject+expected_recipient)
                or provider_message_id is not None and (
                    not isinstance(provider_message_id, str) or not provider_message_id)
                or not isinstance(messages, list) or len(messages) > 100):
            raise ValueError
        seen = set(); matching = []; inspected = []
        for message in messages:
            mid = message['id']
            if not isinstance(mid, str) or not mid or mid in seen:
                raise ValueError
            seen.add(mid); inspected.append(mid)
            payload = message['payload']; headers = {}
            for header in payload.get('headers', []):
                name = header['name'].lower()
                headers.setdefault(name, []).append(header['value'])
            labels = message['label_ids']
            if (not isinstance(labels, list) or 'SENT' not in labels or 'DRAFT' in labels
                    or headers.get('subject') != [expected_subject]
                    or len(headers.get('to', [])) != 1
                    or [addr for _, addr in getaddresses(headers['to'])] != [expected_recipient]
                    or payload.get('mime_type') != 'multipart/alternative'):
                continue
            parts = payload.get('parts', [])
            if (len(parts) != 2 or {p.get('mime_type') for p in parts} != set(bodies)
                    or any(p.get('filename') or p.get('parts')
                           or p.get('charset', 'utf-8').lower() not in ('utf-8', 'utf8')
                           or p.get('body', {}).get('content') != bodies[p['mime_type']]
                           for p in parts)):
                continue
            matching.append(mid)
    except (KeyError, TypeError, AttributeError, ValueError, UnicodeError):
        raise ValueError('invalid email reconciliation input') from None
    if provider_message_id is not None:
        status = ('provider_sent_copy_verified' if provider_message_id in matching
                  else 'provider_copy_mismatch' if provider_message_id in inspected
                  else 'outcome_unknown')
    else:
        status = ('multiple_matching_sent_copies' if len(matching) > 1
                  else 'matching_sent_copy_unbound' if matching else 'outcome_unknown')
    return {'schema': 'task_result_email_reconciliation_v1', 'delivery_key': key,
        'status': status, 'matching_message_ids': matching,
        'inspected_message_count': len(inspected),
        'provider_operation_verified': status == 'provider_sent_copy_verified',
        'recipient_arrival_verified': False, 'automatic_retry_allowed': False}
