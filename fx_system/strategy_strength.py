"""Same-clock contextual currency strength, never an independent indicator vote.

Reuse the display's equal-edge least-squares fit on available connected pairs.
Omit the assessed pair itself: its own price change is not corroboration.
Compare adjacent windows only on identical input-pair sets.
"""
from copy import deepcopy
import math
from .core import expected_closed_timestamp
from .data_quality import evaluate_pair
from .monitor_pairs import PAIR_KEYS
from .strength import CURRENCIES, _fit

SCHEMA = 'strategy_currency_strength_v1'
WINDOWS = {'swing': 24, 'daytrade': 6}
EPSILON = 1e-10  # Floating arithmetic tolerance, not an economic significance threshold.


def _component(contributions, pair):
    reached = {pair[:3]}
    while True:
        added = {c for p in contributions if p[:3] in reached or p[3:] in reached
                 for c in (p[:3], p[3:])}
        if added <= reached: break
        reached |= added
    if pair[3:] not in reached: return {}, ()
    selected = {p: v for p, v in contributions.items() if p[:3] in reached and p[3:] in reached}
    return selected, tuple(c for c in CURRENCIES if c in reached)


def _comparison(contributions, pair):
    selected, currencies = _component(contributions, pair)
    if not selected: return None
    scores = _fit(selected, currencies)
    return {'difference': scores[pair[:3]]-scores[pair[3:]],
            'currencies': list(currencies), 'pairs': sorted(selected),
            'fit_rmse_log_pct': math.sqrt(sum((v['_return']-scores[p[:3]]+scores[p[3:]])**2
                                            for p, v in selected.items())/len(selected))}


def build_contexts(pairs, evaluated_at):
    frames = {}
    for pair in PAIR_KEYS:
        data = pairs.get(pair)
        if not isinstance(data, dict): continue
        try:
            evidence = data.get('decision_data', {})
            h1 = evidence.get('raw', {}).get('h1', [])
            closed = [b for b in h1 if not (type(b.get('timestamp')) is int
                      and b['timestamp']+3600 > evaluated_at)]
            verified, _ = evaluate_pair({'decision_data': {'raw': {'h1': closed},
                'provenance': evidence.get('provenance', {})}}, evaluated_at)
            provenance = evidence.get('provenance', {})
            frames[pair] = {b['timestamp']: b['close'] for b in verified['h1']
                            if provenance.get('h1:'+str(b['timestamp'])) == 'Twelve Data'}
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            continue
    end = expected_closed_timestamp('h1', evaluated_at)
    result = {pair: {} for pair in PAIR_KEYS}
    for strategy, hours in WINDOWS.items():
        start = end-hours*3600
        current = {}; previous = {}; excluded = {}
        for pair in PAIR_KEYS:
            rows = frames.get(pair, {})
            for destination, a, b in ((current, start, end),
                                      (previous, start-hours*3600, start)):
                expected = range(a, b+1, 3600)
                if all(t in rows for t in expected):
                    change = 100*(math.log(rows[b])-math.log(rows[a]))
                    if math.isfinite(change): destination[pair] = {'_return': change}
            if pair not in current: excluded[pair] = 'verified_contiguous_H1_window_unavailable'
        for pair in PAIR_KEYS:
            # Always exclude the scenario's own edge, including from prior-window comparison.
            other = {p: v for p, v in current.items() if p != pair}
            fit = _comparison(other, pair)
            context = {'schema': SCHEMA, 'evaluated_at': evaluated_at,
                'pair': pair, 'strategy': strategy, 'lookback_h1_bars': hours,
                'start_closed_at': start+3600, 'end_closed_at': end+3600,
                'status': 'available' if fit else 'unavailable',
                'reason': None if fit else 'other_pairs_do_not_connect_both_currencies',
                'difference': fit['difference'] if fit else None,
                'contributing_pairs': fit['pairs'] if fit else [],
                'component_currencies': fit['currencies'] if fit else [],
                'fit_rmse_log_pct': fit['fit_rmse_log_pct'] if fit else None,
                'excluded_pairs': dict(excluded), 'own_pair_excluded': True,
                'source': 'verified_Twelve_Data_H1', 'price_derived_not_independent_vote': True,
                'window_policy': 'provisional_not_profitability_validated',
                'comparison': {'status': 'unavailable', 'reason': 'comparable_previous_window_unavailable'}}
            common = {p for p in other if p in previous}
            now_fit = _comparison({p: current[p] for p in sorted(common)}, pair)
            old_fit = _comparison({p: previous[p] for p in sorted(common)}, pair)
            if now_fit and old_fit:
                context['comparison'] = {'status': 'available',
                    'current_difference': now_fit['difference'],
                    'previous_difference': old_fit['difference'],
                    'change': now_fit['difference']-old_fit['difference'],
                    'contributing_pairs': now_fit['pairs'],
                    'previous_start_closed_at': start-hours*3600+3600,
                    'previous_end_closed_at': start+3600,
                    'same_pair_set': now_fit['pairs'] == old_fit['pairs']}
            result[pair][strategy] = context
    return result


def interpret(context, pair, strategy, direction, clock):
    """Validate internally generated context before changing any explanation."""
    unavailable = {'schema': SCHEMA, 'status': 'unavailable', 'relation': 'unverified',
        'evaluated_at': clock, 'pair': pair, 'strategy': strategy, 'comparison_priority': 1,
        'summary': '通貨強弱は未確認。価格構造・反応からの評価を継続する'}
    if (not isinstance(context, dict) or type(clock) is not int or clock <= 0
            or pair not in PAIR_KEYS or strategy not in WINDOWS): return unavailable
    hours = WINDOWS[strategy]; end = expected_closed_timestamp('h1', clock)+3600
    diff = context.get('difference'); edges = context.get('contributing_pairs', [])
    if (context.get('schema') != SCHEMA or context.get('evaluated_at') != clock
            or context.get('pair') != pair or context.get('strategy') != strategy
            or context.get('lookback_h1_bars') != hours or context.get('end_closed_at') != end
            or context.get('start_closed_at') != end-hours*3600
            or context.get('status') != 'available' or context.get('own_pair_excluded') is not True
            or context.get('source') != 'verified_Twelve_Data_H1'
            or not isinstance(edges, list) or pair in edges or len(edges) < 2
            or any(p not in PAIR_KEYS for p in edges) or len(set(edges)) != len(edges)
            or type(diff) not in (int, float) or not math.isfinite(diff)):
        return {**unavailable, 'reason': context.get('reason', 'context_identity_or_window_unverified')}
    value = deepcopy(context)
    sign = 1 if direction == 'long' else -1 if direction == 'short' else 0
    signed = sign*diff
    relation = ('not_directional' if not sign else 'aligned' if signed > EPSILON
                else 'opposed' if signed < -EPSILON else 'balanced')
    change = value.get('comparison', {})
    comparable = (isinstance(change, dict) and change.get('status') == 'available'
        and change.get('same_pair_set') is True
        and isinstance(change.get('contributing_pairs'), list)
        and pair not in change['contributing_pairs']
        and set(change['contributing_pairs']) <= set(edges)
        and len(set(change['contributing_pairs'])) >= 2
        and change.get('previous_end_closed_at') == value['start_closed_at']
        and change.get('previous_start_closed_at') == value['start_closed_at']-hours*3600
        and all(type(change.get(k)) in (int, float) and math.isfinite(change[k])
                for k in ('change','current_difference','previous_difference'))
        and abs(change['change']-change['current_difference']+change['previous_difference']) <= EPSILON)
    movement = ('unverified' if not comparable or not sign else
                'improving' if sign*change['change'] > EPSILON else
                'weakening' if sign*change['change'] < -EPSILON else 'unchanged')
    if not comparable: value['comparison'] = {'status': 'unavailable', 'reason': 'comparison_unverified'}
    description = {'aligned': '売買方向と整合', 'opposed': '売買方向と逆行',
                   'balanced': '方向差がほぼない', 'not_directional': '方向未確定のため採否に使わない'}[relation]
    transition = {'improving': '前の同期間より売買方向へ改善', 'weakening': '前の同期間より売買方向への強弱差が悪化',
                  'unchanged': '前の同期間と同程度', 'unverified': '前の同期間との変化は未確認'}[movement]
    value.update(relation=relation, movement=movement,
                 comparison_priority=0 if relation == 'aligned' else 2 if relation == 'opposed' else 1,
                 summary=f'{hours}時間の通貨強弱は{description}。{transition}。同じ価格由来の参考で独立票ではない')
    return value
