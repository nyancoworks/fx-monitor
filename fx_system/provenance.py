"""Per-candle provenance helpers; no provider selection or trading decisions."""
def key(timeframe, timestamp):
    return f"{timeframe}:{int(timestamp)}"

def record(provenance, timeframe, bars, provider, *, only_new=False):
    """Attach a source to observed completed bars, preserving existing origin."""
    result=dict(provenance or {})
    for bar in bars:
        k=key(timeframe,bar["timestamp"])
        if not only_new or k not in result:
            result[k]=provider
    return result

def derived_source(provenance, timeframe, timestamps):
    """Return one source only if every constituent candle has the same known origin."""
    sources=[(provenance or {}).get(key(timeframe,t)) for t in timestamps]
    if not sources or any(s is None for s in sources):
        return "unknown"
    return sources[0] if len(set(sources))==1 else "mixed"

def reconcile_existing(cached, timeframe):
    """Legacy caches cannot be retroactively attributed to a provider."""
    provenance=dict(cached.get("bar_provenance") or {})
    for bar in cached.get(timeframe,[]):
        provenance.setdefault(key(timeframe,bar["timestamp"]),"unknown")
    return provenance


def assess_feed_consistency(provenance, frames):
    """Fail closed unless all stored M5/H1/D1 bars have one verified provider."""
    sources={provenance.get(key(tf, bar['timestamp']), 'unknown')
             for tf in ('m5', 'h1', 'd1') for bar in frames.get(tf, [])}
    return {'mixed_source_warning': len(sources)>1,
            'execution_feed_consistent': bool(sources) and sources=={'Twelve Data'}}
