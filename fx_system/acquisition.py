"""Cache recovery planning; no network calls or provider re-attribution."""
import datetime as dt
from email.utils import parsedate_to_datetime
from .core import aggregate
from .data_quality import evaluate_data
from .provenance import derived_source, key

def h1_recovery_needed(cached, provenance, now):
    frames,_=evaluate_data(cached,provenance,now)
    return len(frames["h1"])<35 or len(frames["h4"])<15

def request_plan(cached, provenance, now):
    recovery=h1_recovery_needed(cached,provenance,now)
    h1=("h1","1h",240)
    m5=("m5","5min",288)
    return [h1,m5] if recovery else [m5,h1]

def rebuild_verified_h1(h1, m5, provenance, now):
    frames,_=evaluate_data({"m5":m5},provenance,now)
    merged={b["timestamp"]:b for b in h1}
    sources=dict(provenance)
    for bar in aggregate(frames["m5"],300,3600):
        stamp=bar["timestamp"]
        source=derived_source(provenance,"m5",[stamp+i*300 for i in range(12)])
        if source!="Twelve Data":
            continue
        # A directly fetched, verified H1 must not be overwritten by a fallback.
        if stamp in merged and sources.get(key("h1",stamp))=="Twelve Data":
            continue
        merged[stamp]=bar
        sources[key("h1",stamp)]=source
    return sorted(merged.values(),key=lambda b:b["timestamp"])[-500:],sources

def retry_after_seconds(value, now):
    """Honor delta-seconds and HTTP dates; never shorten a provider cooldown."""
    try:
        seconds=int(value)
    except (TypeError,ValueError):
        try:
            date=parsedate_to_datetime(value)
            if date.tzinfo is None:
                date=date.replace(tzinfo=dt.timezone.utc)
            seconds=int(date.timestamp()-now)
        except (TypeError,ValueError,OverflowError):
            seconds=60
    return max(60,seconds)
