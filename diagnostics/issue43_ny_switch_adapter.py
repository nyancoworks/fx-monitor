"""Read-only preproduction D1 switch rehearsal. Does not grant trading permission."""
import datetime as dt
from fx_system.data_quality import evaluate_pair
from .issue43_ny_incremental import snapshot, UTC


def rehearse(data, archive, pair, as_of, *, ny_contract_adopted=False,
             publication_lag_seconds=0, closed_holidays=()):
    """Retain all existing intraday vetoes; replace only the *candidate* D1 check.

    Contract adoption is an explicit what-if input, not provider authentication.
    Legacy data and stored grades remain unchanged in either switch direction.
    """
    if type(ny_contract_adopted) is not bool:
        raise TypeError('explicit contract adoption flag required')
    frames, quality = evaluate_pair(data, int(as_of.timestamp()))
    ny = snapshot(archive,pair,as_of,publication_lag_seconds=publication_lag_seconds,
                  closed_holidays=closed_holidays)
    intraday = quality['intraday_monitoring_ready'] is True
    blockers = list(quality['intraday_monitoring_reasons'])
    if not ny['calendar_ready']:blockers.append('ny_d1_calendar_incomplete_or_not_publishable')
    if not ny_contract_adopted:blockers.append('ny17_custom_d1_contract_not_adopted')
    # Macro W1 remains insufficient independently from D1 quality.
    return {'pair':pair,'evaluated_at_utc':as_of.astimezone(UTC).isoformat(),
        'legacy_decision_data_ready':quality['ready'],
        'legacy_reasons':quality['reasons'], 'intraday_ready':intraday,
        'ny_d1_calendar_ready':ny['calendar_ready'], 'ny_d1_count':ny['d1_count'],
        'ny_w1_count':ny['w1_count'],'ny_w1_35_week_context_available':ny['w1_count']>=35,
        'switch_adopted_for_rehearsal':ny_contract_adopted,
        'candidate_decision_data_ready':intraday and ny['calendar_ready'] and ny_contract_adopted,
        'candidate_blockers':blockers,
        'rollback_decision_data_ready':quality['ready'],
        'stored_legacy_grade':data.get('setup',{}).get('v1_decision',{}).get('grade'),
        'provider_session_verified':False,'native_d1_equivalent_verified':False,
        'formal_decision_permission':False,'entry_permission':False}

