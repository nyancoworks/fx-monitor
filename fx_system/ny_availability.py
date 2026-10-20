"""Audit observed availability, never a provider publication-SLA attestation."""
import datetime as dt
from diagnostics.issue43_ny_incremental import validate_state, UTC


def observed_availability(checkpoint, pair, now):
    archive=checkpoint["archive"]
    validate_state(archive)
    receipts={}
    for receipt in checkpoint["receipts"]:
        if receipt.get("pair")!=pair:continue
        identity=(receipt.get("source_sha256"),receipt.get("available_at_utc"))
        receipts[identity]=receipt
    reasons=[];covered=set();latest_receipt=None
    for event in archive["events"]:
        if event["pair"]!=pair:continue
        stamp=event.get("received_as_of_utc")
        identity=(event.get("source_sha256"),stamp)
        if identity not in receipts:
            reasons.append("NY source event has no matching receipt")
            continue
        try:
            received=dt.datetime.fromisoformat(stamp)
            if received.tzinfo is None or received.utcoffset()!=dt.timedelta(0):
                raise ValueError("aware UTC receipt required")
            received_at=received.timestamp()
            if received_at>now:raise ValueError("receipt later than evaluation")
            if any(change["timestamp"]+3600>received_at for change in event["changes"]):
                raise ValueError("H1 not closed at receipt")
        except (ValueError,TypeError,OverflowError,KeyError):
            reasons.append("NY source event availability invalid")
            continue
        latest_receipt=max(latest_receipt or received_at,received_at)
        covered.update(str(change["timestamp"]) for change in event["changes"])
    missing=set(archive["pairs"].get(pair,{}))-covered
    if missing:reasons.append("NY H1 lacks observed availability evidence")
    if not covered:reasons.append("NY observed source history empty")
    return {"policy":"observed_receipts_only_not_provider_sla",
            "observed_available":not reasons,"covered_h1":len(covered),
            "missing_h1":len(missing),"latest_received_at":latest_receipt,
            "reasons":list(dict.fromkeys(reasons)),
            "provider_session_verified":False,"publication_policy_verified":False}
