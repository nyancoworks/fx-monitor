"""Associate saved provider health by exact source ID, without network or gates."""
from .financecalendar_adapter import _instant



def source_health_index(payload, *, observed_at_utc, calendar_observed_at_utc):
    if (not isinstance(payload, dict) or type(observed_at_utc) is not int
            or not 0 < observed_at_utc <= calendar_observed_at_utc
            or not isinstance(payload.get('source_health_summary'), dict)
            or payload['source_health_summary'].get('reported') is not True
            or not isinstance(payload.get('source_health'), list)):
        return {}
    provider_clock = _instant(payload.get('time_utc'))
    generated = _instant(payload.get('snapshot', {}).get('generated_at')) if isinstance(payload.get('snapshot'), dict) else None
    if any(t is not None and t > observed_at_utc for t in (provider_clock, generated)):
        return {}
    index, duplicates = {}, set()
    for row in payload['source_health']:
        if not isinstance(row, dict) or not isinstance(row.get('source_id'), str) or not row['source_id']:
            continue
        source_id = row['source_id']
        if source_id in index or source_id in duplicates:
            index.pop(source_id, None)
            duplicates.add(source_id)
            continue
        status = row.get('status')
        checked, fetched = _instant(row.get('checked_at')), _instant(row.get('fetched_at'))
        if (not isinstance(status, str) or status not in ('success', 'degraded', 'failed', 'disabled')
                or any(t is not None and t > observed_at_utc for t in (checked, fetched))):
            duplicates.add(source_id)  # a later duplicate cannot repair ambiguous evidence
            continue
        index[source_id] = {
            'status': status, 'source_id': source_id,
            'mode': row['mode'] if isinstance(row.get('mode'), str) else None,
            'checked_at_utc': checked, 'fetched_at_utc': fetched,
            'observed_at_utc': observed_at_utc, 'snapshot_generated_at_utc': generated,
            'generation_match': 'unverified', 'current_freshness': 'unverified',
        }
    return index
