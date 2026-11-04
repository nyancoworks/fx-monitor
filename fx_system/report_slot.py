"""Producer-observed report-slot assignment, not a GitHub created_at claim."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import re

SCHEMA = 'saved_report_slot_v1'
REPOSITORY = 'nyancoworks/fx-monitor'


def build_slot(start, source, snapshot_blob):
    result = {'schema': SCHEMA, 'source': deepcopy(source),
              'snapshot_git_blob_sha': snapshot_blob, 'status': 'unavailable',
              'reason': 'start_evidence_unavailable', 'start': None,
              'target_scheduled_for': None}
    if (not isinstance(start, dict)
            or set(start) != {'observed_started_at','run_id','source_commit','repository','run_attempt','event'}):
        return result
    stamp = start.get('observed_started_at')
    if (type(stamp) is not int or stamp <= 0
            or type(source.get('evaluated_at')) is not int or stamp > source['evaluated_at']
            or start.get('run_id') != source.get('run_id')
            or type(source.get('run_id')) is not int or source['run_id'] <= 0
            or re.fullmatch('[0-9a-f]{40}', str(source.get('source_commit'))) is None
            or start.get('source_commit') != source.get('source_commit')
            or start.get('repository') != REPOSITORY
            or source.get('source_repository') != REPOSITORY
            or type(start.get('run_attempt')) is not int or start['run_attempt'] != 1
            or start.get('event') != 'workflow_dispatch'
            or re.fullmatch('[0-9a-f]{40}', str(snapshot_blob)) is None):
        return result
    if stamp % 3600 < 50*60:
        result['reason'] = 'outside_existing_collection_window'
        return result
    result.update(status='assigned', reason=None, start=deepcopy(start),
                  target_scheduled_for=(stamp//3600+1)*3600)
    target=result['target_scheduled_for']
    result['target_scheduled_for_utc']=datetime.fromtimestamp(target,timezone.utc).isoformat()
    result['target_scheduled_for_jst']=datetime.fromtimestamp(target,timezone(timedelta(hours=9))).isoformat()
    return result


def validate_slot(receipt, source, snapshot_blob, scheduled_for):
    if (not isinstance(receipt, dict) or type(scheduled_for) is not int
            or receipt.get('status') != 'assigned'
            or receipt != build_slot(receipt.get('start'), source, snapshot_blob)
            or receipt.get('target_scheduled_for') != scheduled_for):
        raise ValueError('report slot evidence mismatch')
    return True
