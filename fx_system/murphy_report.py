"""Render Issue #124 cards using only same-generation saved evidence."""
from datetime import datetime, timedelta, timezone
import re

from .activate_time import swing_line
from .economic_calendar_report import _event_clock
from .murphy_profile import TIMEFRAMES, selected

JST = timezone(timedelta(hours=9))
LABELS = {'swing': 'スイング', 'daytrade': 'デイトレード'}
DIRECTIONS = {'long': '↑', 'short': '↓', None: '→'}
STATES = {'ready': '仕掛け条件観測済み・現在値を再確認', 'waiting': '条件待ち',
          'stopped': '見送り・停止水準到達', 'target_reached': '見送り・目標到達',
          'unavailable': '価格計画未確認'}


def _clock(value):
    return datetime.fromtimestamp(value, JST).strftime('%m/%d %H:%M JST')


def _number(value):
    return f'{value:.8f}'.rstrip('0').rstrip('.') if value is not None else '未確認'


def _strength(record):
    context = record['currency_strength_context']
    scores = context.get('display_scores')
    if context['status'] != 'available' or not scores:
        return '通貨強弱未確認'
    changes = context.get('display_changes', {})
    relation = {'aligned': '整合', 'opposed': '逆行', 'balanced': '均衡',
                'not_directional': '方向未確定'}[context['relation']]
    currencies = (record['pair'][:3], record['pair'][3:])
    scale = max(abs(scores[c]) for c in currencies)
    lines = []
    for currency in currencies:
        value, change = scores[currency], changes.get(currency)
        arrow = '？' if change is None else '↑' if change > 1e-8 else '↓' if change < -1e-8 else '→'
        size = round(4 * abs(value) / scale) if scale else 0
        left = size if value < 0 else 0
        right = size if value > 0 else 0
        gauge = '·' * (4-left) + '■' * left + '│' + '■' * right + '·' * (4-right)
        lines.append(f'{currency} {gauge} {value:+.4f} {arrow}')
    return ('／'.join(lines) + f'｜差 {context["difference"]:+.4f}｜{relation}'
            + f'（{context["lookback_h1_bars"]}時間、対数変化率の相対推定、'
              '各端は両通貨の絶対値の最大、矢印は比較可能な前の同期間）')


def _fundamentals(record):
    context = record.get('economic_calendar_context', {})
    pair = record['pair']
    currencies = (pair[:3], pair[3:])
    facts = context.get('policy_reference', {}).get('facts', [])
    policies, rates, dates = [], [], []
    for currency in currencies:
        candidates = [fact for fact in facts if fact['currency'] == currency]
        if not candidates:
            policies.append(f'{currency} ⚪ 不明・政策資料なし')
            continue
        fact = max(candidates, key=lambda item: (item['published_date'], item['observed_at_utc']))
        rate = fact['rate_text']
        decision = {'raised': '引上げ', 'lowered': '引下げ', 'held': '据置き',
                    'changed': '変更'}[fact['decision']]
        policies.append(f'{currency} ⚪ 不明・{fact["source_name"][:35]} '
                        f'{fact["instrument"][:40]} {rate[:32]}（{decision}、{fact["published_date"]}）')
        match = re.fullmatch(r'\s*(-?\d+(?:\.\d+)?)\s*%\s*', rate)
        if len(candidates) == 1 and match and fact.get('effective_date'):
            rates.append(float(match[1]))
            dates.append(fact['effective_date'])
    diff = f'保存公表値の差 {rates[0]-rates[1]:+.2f}ポイント（適用日 {dates[0]} / {dates[1]}）' if len(rates) == 2 else '比較可能な金利差は未確認'
    events = [event for event in context.get('events', []) if event.get('timing') in ('upcoming', 'uncertain')
              and event.get('provider_status') != 'cancelled']
    events.sort(key=lambda item: (item.get('impact') != 'high', item.get('scheduled_at_utc') or float('inf')))
    events_text = '／'.join(
        f'{event["currency"]} {str(event.get("title") or event.get("name") or "名称未確認")[:42]} '
        f'{_event_clock(event, _clock)}（{"重要" if event.get("impact") == "high" else "関連"}'
        f'{"・古い出典" if event.get("freshness") == "stale" else ""}）'
        for event in events[:2])
    risk = '⚠️ 重要指標の急変動に注意' if any(e.get('impact') == 'high' for e in events) else '急変動リスク未確認'
    observed = context.get('observed_at_utc')
    age = f'{_clock(observed)}取得、鮮度・網羅性未検証' if observed else '取得・鮮度未確認'
    return ('／'.join(policies) + f'｜{diff}｜テクニカルとの関係 不明\n'
            f'  {events_text or "関連する保存予定未確認"}｜{risk}｜{age}')


def _supplement(base):
    bars = base.get('macd', [])
    histograms = [bar['histogram'] for bar in bars]
    histogram = histograms[-1] if histograms else None
    arrow = ''
    if len(histograms) == 2 and None not in histograms:
        previous, current = histograms
        arrow = ' ↑' if current > previous else ' ↓' if current < previous else ' →'
    values = base.get('rci', {})
    return 'MACDヒストグラム '+_number(histogram)+arrow+'｜RCI '+ ' / '.join(
        f'{period} {_number(values.get(period, {}).get("value"))}' for period in ('9', '26', '52'))


def _card(record, time_context, previous):
    pair, strategy = record['pair'], record['strategy']
    direction, plan = record['direction'], record['price_plan']
    action = {'long': '🟢 買い', 'short': '🔴 売り', None: '⚪ 見送り'}[direction]
    label = STATES[plan['status']]
    heading = f'{pair[:3]}/{pair[3:]}｜{LABELS[strategy]}｜{action} {record["grade"] or ""}｜{label}'
    frame = record['murphy_inputs']
    base = frame[record['reference_timeframe']]
    price = _number(plan['current'])
    if plan['price_closed_at']:
        price += f'（{plan["price_timeframe"].upper()} {_clock(plan["price_closed_at"])}確定）'
    timing = ' '.join(tf.upper()+(
        DIRECTIONS[frame[tf].get('direction')] if frame[tf]['status'] == 'available' else '？')
        for tf in TIMEFRAMES[strategy])
    lines = [f'### {heading}', f'- **現在価格の参考** {price}']
    if plan['entry'] is not None:
        lines += [
            f'- **価格計画** 🛑 損切り {_number(plan["stop"])} → ▶ エントリー目安 {_number(plan["entry"])}'
            f' → 🎯 利確目安 {_number(plan["target"])}（リスク {_number(plan["risk_pips"])} pips'
            f'／リワード {_number(plan["reward_pips"])} pips、RR 1:{_number(plan["rr"])}・費用前）',
            f'- **条件** 基準 {_number(plan["trigger_level"])}。{record["entry_condition"]}。損切りは価格到達時',
        ]
    else:
        lines.append(f'- **条件** {record["entry_condition"]}')
    span = base.get('span', {})
    blue_side = {'above': '上', 'below': '下', 'inside': '一致'}.get(
        span.get('last', {}).get('blue_position'), '未確認')
    sb_phase = {'gradual_trend': '緩やかなトレンド', 'trend':'トレンド', 'expanding_trend':'拡大トレンド',
                'correction': '調整', 'range': 'もみ合い', 'transition':'移行'}.get(base.get('sb_phase'), '未確認')
    changes = [label for key, label in (
        ('direction', '方向'), ('grade', '評価'), ('price_plan', '価格計画'),
        ('reference_levels', '目標水準')) if key in previous.get('changed_fields', [])]
    change_text = '・'.join(changes)+'に変化' if changes else '同方向・同評価・同水準' if previous else '比較未確認'
    follow = previous.get('previous_condition_followthrough', {})
    levels = [label for name, label in (('invalidation_touch', '前回損切り'),
                                        ('target_touch', '前回利確目安'))
              if follow.get(name)]
    if levels:
        change_text += '／'+'・'.join(levels)+'への到達を保存足で観測'
    lines += [
        f'- **時間足** {timing}｜{record["reference_timeframe"].upper()} SB {sb_phase}、価格は青色スパンの{blue_side}。{record["grade_reason"]}',
        f'- **補助** {_supplement(base)}｜前回比 {change_text}',
        f'- **通貨強弱** {_strength(record)}',
        f'- **ファンダメンタルズ** {_fundamentals(record)}',
    ]
    event = span.get('signal_event')
    age = (f'{record["reference_timeframe"].upper()}のスパン信号変化から確定足{event["age_bars"]}本'
           if event else '主軸スパンの変化経過は未確認')
    timing_note = '／'+swing_line(time_context) if strategy == 'swing' else ''
    lines.append('- **時間分析** '+age+timing_note)
    return {'pair': pair, 'strategy': strategy, 'heading': heading,
            'excluded_target_reached': False, 'text': '\n'.join(lines)}


def render(outlook, *, include_all=False, strength=None, previous=None, target=None):
    counts = outlook['assessment_counts']
    title = _clock(target) if target else '保存評価'
    lines = [f'# FX監視候補｜{title}（{_clock(outlook["evaluated_at"])}保存）',
             f'32評価｜検討 {counts["review"]}、見送り {counts["skip"]}、評価保留 {counts["evaluation_pending"]}']
    if strength is not None:
        from .strength_export import render_strength_summary
        lines += ['## 通貨強弱ランキング', render_strength_summary(strength, outlook['evaluated_at']).splitlines()[0]]
        if strength.get('ranking'):
            lines.append('24時間の相対スコア（対数変化率単位） '+'｜'.join(
                f'{currency} {strength["scores"][currency]:+.4f}' for currency in strength['ranking']))
    sections = {strategy: [] for strategy in LABELS}
    rows = outlook['strategy_assessments'] if include_all else selected(outlook)
    for record in rows:
        key = (record['pair'], record['strategy'])
        time_context = outlook.get('activate_time_context', {}).get(key[0])
        sections[key[1]].append(_card(record, time_context, (previous or {}).get(key, {})))
    for strategy, label in LABELS.items():
        lines.append('## '+label+(' 全評価' if include_all else ' TOP3'))
        lines.extend(c['text'] for c in sections[strategy])
        if not sections[strategy]:
            lines.append('掲載候補なし')
    return '\n\n'.join(lines), sections


def task_report(report, strength, slot, continuity, outlook):
    source, blob = report['source'], report['snapshot_git_blob_sha']

    def same(candidate, status):
        return (isinstance(candidate, dict) and candidate.get('source') == source
                and candidate.get('snapshot_git_blob_sha') == blob and candidate.get('status') == status)

    target = slot['target_scheduled_for'] if same(slot, 'assigned') else None
    previous = {(row['pair'], row['strategy']): row for row in continuity['rows']} if same(continuity, 'saved') else {}
    scores = strength['currency_strength'] if same(strength, 'saved') else {}
    body, sections = render(outlook, strength=scores, previous=previous, target=target)
    return {'schema': 'saved_task_report_v1', 'source': source, 'snapshot_git_blob_sha': blob,
            'target_scheduled_for': target, 'assessment_counts': outlook['assessment_counts'],
            'status': 'saved', 'sections': sections, 'report_text': body}
