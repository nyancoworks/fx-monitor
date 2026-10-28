"""Concrete, versioned discretionary conditions from saved completed candles.

These are provisional scenario interpretations, not a profitability model or
an execution gate. Existing grades and the raw reference-pattern observation
are deliberately unchanged. A condition observation is never a fill price.
"""
from copy import deepcopy
import math


SECONDS = {'m15': 900, 'm5': 300}
LABELS = {'m15': '15分足', 'm5': '5分足', 'h4': '4時間足', 'h1': '1時間足'}


def _dict(value):
    return value if isinstance(value, dict) else {}


def _price(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _fmt(value):
    return f'{value:.8f}'.rstrip('0').rstrip('.')


def condition_inputs(data, track, evaluated_at):
    """Retain only a validated local window, with no API or diagnostic dependency.

    The oldest three bars can anchor a breakout before its test bar; the final
    bar can then test a retest. Gaps outside this local window do not veto it.
    """
    tf = track.get('trigger_timeframe'); seconds = SECONDS.get(tf)
    result = {'status': 'unavailable', 'timeframe': tf, 'evaluated_at': evaluated_at}
    if (track.get('base_verified') is not True or track.get('trigger_verified') is not True
            or track.get('direction') not in ('long', 'short') or seconds is None
            or type(evaluated_at) is not int or evaluated_at <= 0):
        return {**result, 'reason': '当該戦略の方向・確認足品質を確認できない'}
    bars = _dict(_dict(data).get(tf)).get('candles')
    if not isinstance(bars, list) or len(bars) < 5:
        return {**result, 'reason': '条件を具体化する直近5本の確定足が不足'}
    window = bars[-5:]
    for bar in window:
        if not isinstance(bar, dict):
            return {**result, 'reason': '確認足の形式が不正'}
        stamp = bar.get('timestamp'); values = [bar.get(k) for k in ('open', 'high', 'low', 'close')]
        if (type(stamp) is not int or stamp <= 0 or stamp % seconds
                or not all(_price(v) for v in values)):
            return {**result, 'reason': '確認足の価格・時計が不正'}
        o, h, l, c = values
        if not l <= min(o, c) <= max(o, c) <= h:
            return {**result, 'reason': '確認足のOHLCが不整合'}
    if any(b['timestamp'] - a['timestamp'] != seconds for a, b in zip(window, window[1:])):
        return {**result, 'reason': '直近5本に欠損・重複・時計の不連続がある'}
    closed_at = window[-1]['timestamp'] + seconds
    if not 0 <= evaluated_at - closed_at < seconds:
        return {**result, 'reason': '直近確認足が古い、または未確定'}
    base_stamp = _dict(track.get('reference_plan')).get('reference_close_timestamp')
    base_seconds = {'h4': 14400, 'h1': 3600}.get(track.get('base_timeframe'))
    if type(base_stamp) is int and base_seconds and closed_at < base_stamp + base_seconds:
        return {**result, 'reason': '確認足が基準足の確定より古い'}
    return {**result, 'status': 'verified', 'direction': track['direction'],
            'closed_at': closed_at, 'bars': [{k: b[k] for k in ('timestamp', 'open', 'high', 'low', 'close')}
                                          for b in window]}


def describe_conditions(record, inputs):
    """Select a price-action route by existing phase and actual pullback context.

    A transition asks for breakout then retest, a pullback asks for a rejection
    at its local extreme, and a continuing trend asks for a close breakout.
    This is not an indicator vote or a shared all-indicator AND rule.
    """
    result = {'schema': 'scenario_conditions_v1', 'evaluated_at': record.get('evaluated_at'),
              'timeframe': record.get('trigger_timeframe'), 'direction': record.get('direction'),
              'status': 'unavailable', 'route': None, 'conditions': [], 'observed_at': None,
              'observed_close': None, 'formation_price': None, 'formation_rr': None,
              'advisory_only': True, 'profitability_validated': False,
              'basis': 'contextual_saved_price_action_v1',
              'scope': 'scenario_confirmation_conditions_not_order_or_fill'}
    def unavailable(reason, status='unavailable'):
        return {**result, 'status': status, 'reason': reason, 'summary': reason}
    if _dict(record.get('expiry')).get('status') == 'withdrawn':
        return unavailable('旧シナリオは撤回済み。新しい構造・目標・無効化水準で組み直す', 'withdrawn')
    if record.get('assessment') != 'review':
        return unavailable('方向や主要データを評価できないため条件を提示できない'
                           if record.get('assessment') == 'evaluation_pending' else
                           '有効なシナリオがないため新しい価格構造を待つ', 'not_applicable')
    tf = record.get('trigger_timeframe'); seconds = SECONDS.get(tf)
    i = _dict(inputs); clock = record.get('evaluated_at')
    if (i.get('status') != 'verified' or i.get('timeframe') != tf or i.get('evaluated_at') != clock
            or i.get('direction') != record.get('direction')):
        return unavailable(i.get('reason', '条件計算に必要な同時刻の確認足が未提供'))
    # Revalidate retained inputs on read; do not trust a status label alone.
    checked = condition_inputs({tf: {'candles': i.get('bars')}}, {
        'base_verified': True, 'trigger_verified': True, 'direction': record.get('direction'),
        'trigger_timeframe': tf}, clock)
    if checked.get('status') != 'verified' or checked.get('closed_at') != i.get('closed_at'):
        return unavailable('条件入力の価格・確定時計を再照合できない')
    bars = checked['bars']; last = bars[-1]; previous = bars[-2]
    long = record['direction'] == 'long'
    levels = _dict(record.get('reference_levels'))
    stop, target = levels.get('invalidation'), levels.get('structural_target')
    if not (_price(stop) and _price(target) and
            (stop < last['close'] < target if long else target < last['close'] < stop)):
        return unavailable('無効化・構造目標が不足、または確認足価格との前後関係が不整合')
    boundary_key = 'high' if long else 'low'
    support_key = 'low' if long else 'high'
    above = '上回る' if long else '下回る'
    close_side = '高く' if long else '安く'
    local_pullback = ((previous['close'] < previous['open'] and previous['close'] < bars[-3]['close'])
                      if long else
                      (previous['close'] > previous['open'] and previous['close'] > bars[-3]['close']))
    phase = record.get('market_phase')
    context = ('既存評価で押し戻り待ち' if phase == 'pullback_wait' else
               '直前確定足が構造方向へ逆行' if local_pullback else
               '既存評価で構造とトレンド背景が競合' if phase == 'transition_context' else
               '基準足の方向構造を軸に継続反応を確認')
    conditions = []; observed = False; breakout_at = None
    if phase == 'pullback_wait' or local_pullback:
        route = 'pullback_rejection'
        anchor_bars = bars[-3:-1]
        level = (min if long else max)(b[support_key] for b in anchor_bars)
        # A wick alone is insufficient; reclaim and directional body describe
        # the actual rejection, not a new cross-indicator gate.
        touch = last['low'] <= level if long else last['high'] >= level
        reclaimed = last['close'] > level if long else last['close'] < level
        body = last['close'] > last['open'] if long else last['close'] < last['open']
        observed = touch and reclaimed and body
        text = (f"{LABELS[tf]}で直前2本の{'安値' if long else '高値'}{_fmt(level)}を試し、"
                f"終値が同水準を{above}、始値より{close_side}引ける{'反発' if long else '反落'}を確認する")
        conditions = [{'kind': 'touch_reclaim_directional_close', 'level': level,
                       'touch_relation': '<=' if long else '>=',
                       'close_relation': '>' if long else '<',
                       'body_relation': 'close>open' if long else 'close<open'}]
    elif phase == 'transition_context':
        route = 'breakout_retest'
        # Test two chronological stages against a level known before breakout.
        old_anchors = bars[:-2]
        old_level = (max if long else min)(b[boundary_key] for b in old_anchors)
        prior_break = previous['close'] > old_level if long else previous['close'] < old_level
        if prior_break:
            level = old_level; anchor_bars = old_anchors
            held = ((last['low'] <= level < last['close']) if long else
                    (last['high'] >= level > last['close']))
            observed = held
            breakout_at = previous['timestamp'] + seconds
            failed = last['close'] <= level if long else last['close'] >= level
            stage = 'conditions_observed' if held else 'retest_failed' if failed else 'awaiting_retest'
        else:
            anchor_bars = bars[-4:-1]
            level = (max if long else min)(b[boundary_key] for b in anchor_bars)
            current_break = last['close'] > level if long else last['close'] < level
            breakout_at = last['timestamp'] + seconds if current_break else None
            stage = 'awaiting_retest' if current_break else 'awaiting_breakout'
        text = (f"{LABELS[tf]}終値が直前3本の{'高値' if long else '安値'}{_fmt(level)}を{above}、"
                f"その後の別の確定足で同水準を再度試して終値が{'上側' if long else '下側'}を保つことを確認する")
        conditions = [{'kind': 'close_breakout', 'level': level, 'relation': '>' if long else '<'},
                      {'kind': 'later_retest_hold', 'level': level, 'after_breakout': True,
                       'touch_relation': '<=' if long else '>=', 'close_relation': '>' if long else '<'}]
    else:
        route = 'continuation_breakout'
        anchor_bars = bars[-4:-1]
        level = (max if long else min)(b[boundary_key] for b in anchor_bars)
        observed = last['close'] > level if long else last['close'] < level
        text = f"{LABELS[tf]}終値が直前3本の{'高値' if long else '安値'}{_fmt(level)}を{above}ことを確認する"
        conditions = [{'kind': 'close_breakout', 'level': level, 'relation': '>' if long else '<'}]
    if not (stop < level < target if long else target < level < stop):
        return unavailable('反応の確認水準が構造目標または無効化の外側。条件を作り替えず価格構造を再評価する')
    status = ('conditions_observed' if observed else stage if route == 'breakout_retest' else 'waiting')
    observed_at = checked['closed_at'] if observed else None
    result.update(status=status, route=route, reason=context, summary=text, conditions=conditions,
                  level=level, level_basis='local_saved_extreme_not_confirmed_structural_pivot',
                  anchor_started_at=anchor_bars[0]['timestamp'],
                  anchor_closed_at=anchor_bars[-1]['timestamp'] + seconds,
                  evaluated_candle_closed_at=checked['closed_at'],
                  breakout_observed_at=breakout_at,
                  observed_at=observed_at, observed_close=last['close'] if observed else None,
                  evidence={'test_open': last['open'], 'test_high': last['high'],
                            'test_low': last['low'], 'test_close': last['close'],
                            'test_closed_at': checked['closed_at'],
                            'breakout_close': (previous['close'] if breakout_at == previous['timestamp']+seconds else
                                               last['close'] if breakout_at else None)},
                  withdrawal_conditions=deepcopy(_dict(record.get('expiry')).get('withdrawal_conditions', [])),
                  recheck='保存時の局所水準。新しい確定足では構造・反応・比較水準を再評価する。固定の注文価格や期限ではない',
                  limitations=['条件観測後も主要な反対根拠と目標までの余地を再評価する',
                               '観測終値は約定価格ではない。成立後RR・利益確率は未検証'])
    if status == 'retest_failed':
        result['summary'] = (f"{LABELS[tf]}の再試しで{_fmt(level)}の{'上側' if long else '下側'}を"
                             '終値で維持できず。旧突破条件の継続確認とせず、新しい価格構造・反応を再評価する')
    return result


def validate_conditions(record):
    """Check saved condition evidence without putting raw bars into history."""
    if 'scenario_conditions' not in record:
        return []
    plan = record['scenario_conditions']
    if not isinstance(plan, dict):
        return ['scenario condition record invalid']
    if (plan.get('schema') != 'scenario_conditions_v1'
            or plan.get('evaluated_at') != record.get('evaluated_at')
            or plan.get('timeframe') != record.get('trigger_timeframe')
            or plan.get('direction') != record.get('direction')
            or plan.get('advisory_only') is not True or plan.get('profitability_validated') is not False
            or plan.get('formation_price') is not None or plan.get('formation_rr') is not None):
        return ['scenario condition contract mismatch']
    defined = ('waiting', 'awaiting_breakout', 'awaiting_retest', 'retest_failed', 'conditions_observed')
    if plan.get('status') in defined:
        if record.get('assessment') != 'review' or _dict(record.get('expiry')).get('status') == 'withdrawn':
            return ['inactive scenario contains confirmation conditions']
        ev = _dict(plan.get('evidence')); level = plan.get('level'); clock = record.get('evaluated_at')
        seconds = SECONDS.get(record.get('trigger_timeframe')); closed = ev.get('test_closed_at')
        o,h,l,c = [ev.get('test_'+k) for k in ('open','high','low','close')]
        anchor_start, anchor_end = plan.get('anchor_started_at'), plan.get('anchor_closed_at')
        if (not all(_price(v) for v in (level,o,h,l,c)) or not l<=min(o,c)<=max(o,c)<=h
                or not seconds or type(clock) is not int or type(closed) is not int
                or closed % seconds or not 0<=clock-closed<seconds
                or plan.get('evaluated_candle_closed_at') != closed
                or type(anchor_start) is not int or type(anchor_end) is not int
                or anchor_start % seconds or anchor_end % seconds
                or not 0<anchor_start<anchor_end<=closed-seconds):
            return ['scenario condition evidence invalid']
        long = record.get('direction') == 'long'; route = plan.get('route')
        levels = _dict(record.get('reference_levels'))
        stop, target = levels.get('invalidation'), levels.get('structural_target')
        if not (_price(stop) and _price(target) and
                (stop<min(level,c)<=max(level,c)<target if long else target<min(level,c)<=max(level,c)<stop)):
            return ['scenario condition levels outside structural plan']
        breakout_at = plan.get('breakout_observed_at')
        if route == 'continuation_breakout':
            observed = c>level if long else c<level
            expected = 'conditions_observed' if observed else 'waiting'
        elif route in ('pullback_rejection', 'range_edge_rejection'):
            if route == 'range_edge_rejection':
                rc = _dict(record.get('range_context'))
                if (record.get('scenario_type') != 'range_reversal' or rc.get('status') != 'bounded'
                        or rc.get('direction') != record.get('direction')
                        or rc.get('reaction_level') != level or rc.get('formed_at') != anchor_end):
                    return ['scenario range condition context mismatch']
            observed = l<=level<c and c>o if long else h>=level>c and c<o
            expected = 'conditions_observed' if observed else 'waiting'
        elif route == 'breakout_retest':
            breakout_close = ev.get('breakout_close')
            if breakout_at is None:
                observed = False; expected = 'awaiting_breakout'
                if (c>level if long else c<level):
                    return ['scenario breakout observation missing']
            else:
                if (type(breakout_at) is not int or breakout_at % seconds
                        or breakout_at not in (closed-seconds, closed) or anchor_end>breakout_at-seconds
                        or not _price(breakout_close)
                        or not (breakout_close>level if long else breakout_close<level)):
                    return ['scenario retest chronology invalid']
                observed = breakout_at<closed and (l<=level<c if long else h>=level>c)
                failed = breakout_at<closed and (c<=level if long else c>=level)
                expected = 'conditions_observed' if observed else 'retest_failed' if failed else 'awaiting_retest'
        else:
            return ['scenario condition route invalid']
        if (plan['status'] != expected or plan.get('observed_at') != (closed if observed else None)
                or plan.get('observed_close') != (c if observed else None)
                or any(item.get('level') != level for item in plan.get('conditions', [])
                       if isinstance(item, dict)) or not plan.get('conditions')):
            return ['scenario conditions differ from saved reaction evidence']
    elif plan.get('status') not in ('unavailable', 'withdrawn', 'not_applicable'):
        return ['scenario condition status invalid']
    elif (plan.get('conditions') != [] or plan.get('observed_at') is not None
          or plan.get('observed_close') is not None):
        return ['unavailable scenario contains an observation']
    return []
