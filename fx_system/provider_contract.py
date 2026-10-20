"""Capture bounded timestamp/metadata evidence from an existing HTTP response."""
import datetime as dt
import hashlib
import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def observe_contract(payload, pair, interval, requested_at, received_at):
    meta=payload.get("meta") if isinstance(payload.get("meta"),dict) else {}
    values=payload.get("values") if isinstance(payload.get("values"),list) else []
    timezone=meta.get("exchange_timezone")
    known_timezone=None
    if isinstance(timezone,str) and len(timezone)<=64:
        try:known_timezone=ZoneInfo(timezone).key
        except (ZoneInfoNotFoundError,ValueError):pass
    labels=[];invalid=0
    for row in values[:5000]:
        label=row.get("datetime") if isinstance(row,dict) else None
        if not isinstance(label,str) or len(label)>32:
            invalid+=1;continue
        try:dt.datetime.fromisoformat(label)
        except ValueError:invalid+=1;continue
        labels.append(label)
    result={"provider":"Twelve Data","pair":pair.replace("/",""),
            "interval":interval,"requested_timezone":"UTC",
            "timezone_parameter_applies":interval in ("5min","1h"),
            "daily_timezone_requires_source_verification":interval in ("1day","1week"),
            "requested_at":requested_at,"received_at":received_at,
            "meta_present":isinstance(payload.get("meta"),dict),
            "exchange_timezone_key_present":"exchange_timezone" in meta,
            "exchange_timezone_reported":known_timezone,
            "exchange_timezone_value_is_null":"exchange_timezone" in meta and timezone is None,
            "meta_symbol_matches":meta.get("symbol")==pair,
            "meta_interval_matches":meta.get("interval")==interval,
            "labels_sample":labels[:3],"oldest_label":labels[-1] if labels else None,
            "rows_observed":len(values),"invalid_label_count":invalid,
            "provider_session_verified":False,"publication_policy_verified":False,
            "entry_permission":False}
    result["observation_sha256"]=hashlib.sha256(json.dumps(result,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    return result
