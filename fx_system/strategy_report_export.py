"""Bounded private report plus lossless saved-assessment view for readers.

The original snapshot is never changed. A projection is useful only with the
matching source and original snapshot blob from the same private generation.
"""
import base64
from copy import deepcopy
import gzip
import hashlib
import json
import re
import zlib

from .strategy_report import render_strategy_report
from .validate_strategy_snapshot import validate_strategy_snapshot


SCHEMA = 'saved_strategy_report_v1'
MAX_EXPORT_BYTES = 900_000  # Below the contents reader's 1 MB boundary.
MAX_PAYLOAD_BYTES = 16 * 1024 * 1024
SOURCE_KEYS = ('source_repository', 'source_commit', 'run_id', 'evaluated_at')
SUMMARY_KEYS = ('pair', 'strategy', 'assessment', 'grade', 'direction')


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode()


def _source_valid(source):
    return (isinstance(source, dict) and set(source) == set(SOURCE_KEYS)
            and source.get('source_repository') == 'nyancoworks/fx-monitor'
            and isinstance(source.get('source_commit'), str)
            and re.fullmatch('[0-9a-f]{40}', source['source_commit']) is not None
            and type(source.get('run_id')) is int and source['run_id'] > 0
            and type(source.get('evaluated_at')) is int and source['evaluated_at'] > 0)


def _summaries(view):
    return [{key: record.get(key) for key in SUMMARY_KEYS}
            for record in view['scheduled_outlook']['strategy_assessments']]


def build_strategy_report_export(snapshot_bytes, source):
    """Produce a current-run unavailable receipt if optional rendering fails."""
    if not _source_valid(source):
        raise ValueError('strategy report export source invalid')
    blob = hashlib.sha1(b'blob '+str(len(snapshot_bytes)).encode()+b'\0'+snapshot_bytes).hexdigest()
    bundle = {'schema': SCHEMA, 'source': deepcopy(source), 'snapshot_git_blob_sha': blob,
              'snapshot_byte_length': len(snapshot_bytes), 'status': 'unavailable',
              'error': 'saved_strategy_report_unavailable', 'report_text': None,
              'review_context_text': None, 'assessment_summaries': [], 'payload_base64': None}
    try:
        snapshot = json.loads(snapshot_bytes)
        if snapshot.get('evaluated_at') != source['evaluated_at'] or validate_strategy_snapshot(snapshot):
            return bundle
        outlook = snapshot['scheduled_outlook']
        # Copy the original row assessments, not reconstructed canonical rows:
        # disagreement must fail the original validator before projection.
        view = {'evaluated_at': snapshot['evaluated_at'], 'scheduled_outlook': {
            key: deepcopy(outlook[key]) for key in ('evaluated_at', 'advisory_only',
                'canonical_assessment_field', 'strategy_assessment_count',
                'assessment_counts', 'strategy_assessments')}}
        projected = view['scheduled_outlook']
        projected['rows'] = [{key: deepcopy(row[key]) for key in ('pair', 'strategy_assessments')}
                             for row in outlook['rows']]
        projected['strategy_candidates'] = [{key: row[key] for key in ('pair', 'strategy')}
                                             for row in outlook.get('strategy_candidates', [])]
        raw = _json(view)
        if len(raw) > MAX_PAYLOAD_BYTES:
            return bundle
        saved = {**bundle, 'status': 'saved', 'error': None,
            'assessment_summaries': _summaries(view),
            'assessment_counts': deepcopy(projected['assessment_counts']),
            'selection_version': 2,
            'report_text': render_strategy_report(view), 'encoding': 'gzip_base64_json',
            'review_context_version': 2,
            'review_context_text': render_strategy_report(view, include_all_reviews=True,
                                                        complete_evidence=True),
            'payload_sha256': hashlib.sha256(raw).hexdigest(), 'payload_byte_length': len(raw),
            'payload_base64': base64.b64encode(gzip.compress(raw, mtime=0)).decode('ascii')}
        return saved if len(_json(saved)) <= MAX_EXPORT_BYTES else bundle
    except Exception:
        # Derived report failure must never suppress the original FX save.
        # No raw exception or private data enters a public stage log.
        return bundle


def restore_strategy_report_export(bundle, source, snapshot_blob_sha):
    """Verify envelope, bounded decompression, canonical32 and report equality.

    The original blob identity binds this view to saved private records; it is
    not an independent signature or a replacement for original market data.
    """
    try:
        if (not _source_valid(source) or not isinstance(bundle, dict)
                or bundle.get('schema') != SCHEMA or bundle.get('status') != 'saved'
                or bundle.get('source') != source
                or bundle.get('snapshot_git_blob_sha') != snapshot_blob_sha
                or not isinstance(snapshot_blob_sha, str)
                or re.fullmatch('[0-9a-f]{40}', snapshot_blob_sha) is None
                or bundle.get('encoding') != 'gzip_base64_json'
                or len(_json(bundle)) > MAX_EXPORT_BYTES):
            raise ValueError
        compressed = base64.b64decode(bundle['payload_base64'], validate=True)
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        raw = decoder.decompress(compressed, MAX_PAYLOAD_BYTES+1)
        if (len(raw) > MAX_PAYLOAD_BYTES or decoder.unconsumed_tail or not decoder.eof
                or decoder.unused_data or len(raw) != bundle.get('payload_byte_length')
                or hashlib.sha256(raw).hexdigest() != bundle.get('payload_sha256')):
            raise ValueError
        view = json.loads(raw)
        selection_version = bundle.get('selection_version', 1)
        if type(selection_version) is not int or selection_version not in (1, 2):
            raise ValueError
        if (view.get('evaluated_at') != source['evaluated_at'] or validate_strategy_snapshot(view)
                or bundle.get('assessment_summaries') != _summaries(view)
                or bundle.get('assessment_counts') != view['scheduled_outlook']['assessment_counts']
                or bundle.get('report_text') != render_strategy_report(
                    view, selection_version=selection_version)):
            raise ValueError
        # Legacy text truncated evidence to two entries even in all-review
        # mode. Keep its exact verification while version 2 retains every
        # saved reason/opposition for candidate comparison.
        context_version = bundle.get('review_context_version', 1)
        if (type(context_version) is not int or context_version not in (1, 2)
                or ('review_context_version' in bundle and 'review_context_text' not in bundle)):
            raise ValueError
        if ('review_context_text' in bundle and bundle['review_context_text'] !=
                render_strategy_report(view, include_all_reviews=True,
                                       complete_evidence=context_version == 2,
                                       selection_version=selection_version)):
            raise ValueError
        return view
    except Exception:
        raise ValueError('saved strategy report export invalid or unavailable') from None
