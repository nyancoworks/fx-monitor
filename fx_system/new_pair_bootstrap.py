"""Explicit opt-in, once-per-pair H1 bootstrap planning; no network/adoption."""
PAIRS = frozenset(('CADJPY', 'CHFJPY'))
MARKER = '_new_pair_h1_bootstrap_attempted_at'

def due(pair, cached, enabled=False):
    return enabled is True and pair in PAIRS and MARKER not in cached

def plan(pair, cached, existing, enabled=False):
    if not due(pair, cached, enabled):
        return existing
    # Replace the existing H1 slot. Never add another timeframe or retry slot.
    return [(tf, interval, 5000 if tf == 'h1' else size)
            for tf, interval, size in existing]

def mark_attempt(cached, now):
    if type(now) is not int or now <= 0:
        raise ValueError('valid attempt clock required')
    if MARKER in cached:
        raise ValueError('bootstrap already attempted; manual review required')
    cached[MARKER] = now
