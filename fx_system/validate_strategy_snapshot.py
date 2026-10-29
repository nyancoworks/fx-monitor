"""Validate saved independent assessments without evaluating prices or fetching data."""
from collections import Counter
from .monitor_pairs import PAIR_KEYS
from .scenario_conditions import validate_conditions
from .legacy_range import validate_range


def validate_strategy_snapshot(snapshot):
    """Return failures; pending/skip are valid outcomes, missing records are not."""
    failures = []
    outlook = snapshot.get('scheduled_outlook')
    if not isinstance(outlook, dict):
        return ['scheduled strategy outlook missing']
    clock = snapshot.get('evaluated_at')
    if type(clock) is not int or clock <= 0 or outlook.get('evaluated_at') != clock:
        failures.append('scheduled strategy clocks mismatch')
    if (outlook.get('advisory_only') is not True or
            outlook.get('canonical_assessment_field') != 'strategy_assessments'):
        failures.append('scheduled strategy advisory contract missing')
    expected = {(p, s) for p in PAIR_KEYS for s in ('swing', 'daytrade')}
    records = outlook.get('strategy_assessments')
    if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
        return failures + ['scheduled strategy records missing or invalid']
    keys = [(r.get('pair'), r.get('strategy')) for r in records]
    # Validate types before using identities as dictionary/set keys.
    if any(not isinstance(p, str) or not isinstance(s, str) for p, s in keys):
        return failures + ['scheduled strategy identity invalid']
    if len(keys) != len(expected) or set(keys) != expected:
        failures.append('scheduled strategy universe incomplete or duplicated')
    if outlook.get('strategy_assessment_count') != len(expected):
        failures.append('scheduled strategy total mismatch')
    counts = Counter()
    for r in records:
        from .swing_environment import METHOD, build_environment
        if r.get('method_version') == METHOD or 'swing_environment' in r:
            environment = build_environment(r)
            if environment != r.get('swing_environment'):
                failures.append('scheduled swing environment mismatch')
            if environment and environment['exclude_from_monitoring'] and r.get('assessment') != 'skip':
                failures.append('consolidating swing must remain outside monitoring')
        if 'technical_context' in r or r.get('indicator_context',{}).get('schema')=='contextual_indicator_context_v2':
            from .technical_context import build_technical_context
            if r['technical_context'] != build_technical_context(r):
                failures.append('scheduled technical context mismatch')
        failures.extend(validate_conditions(r))
        failures.extend(validate_range(r))
        state = r.get('assessment')
        if state not in ('review', 'skip', 'evaluation_pending'):
            failures.append('scheduled strategy state invalid')
        else:
            counts[state] += 1
        if state == 'review' and r.get('direction') not in ('long', 'short'):
            failures.append('scheduled strategy review direction invalid')
        if ((state == 'review' and r.get('grade') not in ('A', 'B', 'C')) or
                (state != 'review' and r.get('grade') is not None)):
            failures.append('scheduled strategy grade/state mismatch')
        if r.get('evaluated_at') != clock:
            failures.append('scheduled strategy record clock mismatch')
        strength=r.get('currency_strength_context')
        if strength is not None:
            from .strategy_strength import interpret
            if (not isinstance(strength,dict) or strength.get('evaluated_at') != clock
                    or strength.get('pair') != r.get('pair') or strength.get('strategy') != r.get('strategy')
                    or strength.get('status') not in ('available','unavailable')):
                failures.append('scheduled strategy strength identity mismatch')
            elif strength.get('status') == 'available' and interpret(
                    strength,r['pair'],r['strategy'],r.get('direction'),clock) != strength:
                failures.append('scheduled strategy strength context invalid')
            elif strength.get('status') == 'unavailable' and (
                    strength.get('relation') != 'unverified' or strength.get('comparison_priority') != 1):
                failures.append('unavailable strategy strength contains a preference')
        if 'practical_review' in r:
            from copy import deepcopy
            from .practical_review import review
            checked=review(deepcopy(r),monitor_wait=r['practical_review'].get('schema')!='saved_practical_review_v1')
            if (checked['practical_review']!=r['practical_review'] or checked['grade']!=r.get('grade')):
                failures.append('scheduled practical review mismatch')
        if 'decision_brief' in r:
            from .decision_brief import build_brief
            if r['decision_brief']!=build_brief(r):
                failures.append('scheduled decision brief mismatch')
        if r.get('execution_authority') != 'none' or 'entry_permission' in r:
            failures.append('scheduled strategy execution contract invalid')
        base, trigger = ('h4', 'm15') if r.get('strategy') == 'swing' else ('h1', 'm5')
        if r.get('reference_timeframe') != base or r.get('trigger_timeframe') != trigger:
            failures.append('scheduled strategy timeframe mismatch')
    if outlook.get('assessment_counts') != {s: counts[s] for s in ('review', 'skip', 'evaluation_pending')}:
        failures.append('scheduled strategy counts mismatch')
    rows = outlook.get('rows')
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        return failures + ['scheduled history rows invalid']
    names = [r.get('pair') for r in rows]
    if (any(not isinstance(p, str) for p in names) or
            len(names) != len(PAIR_KEYS) or set(names) != set(PAIR_KEYS)):
        return failures + ['scheduled history pair universe mismatch']
    canonical = dict(zip(keys, records))
    for row in rows:
        saved = row.get('strategy_assessments')
        if not isinstance(saved, dict) or set(saved) != {'swing', 'daytrade'}:
            failures.append('scheduled history strategy records missing')
            continue
        for strategy in ('swing', 'daytrade'):
            if saved[strategy] != canonical.get((row['pair'], strategy)):
                failures.append('scheduled history strategy differs from canonical assessment')
    return failures
