"""Read-only Japanese report of canonical saved assessments; no market fetches."""
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo
import math
from .validate_strategy_snapshot import validate_strategy_snapshot
from .price_reaction_observation import reaction_description
from .economic_calendar_report import calendar_lines
from .report_plan_comparison import saved_plan_comparison, comparison_explanations


def _ordered_reviews(outlook, *, selection_version=4):
    """All reviews; grade first, then headroom in matching contexts."""
    if type(selection_version) is not int or selection_version not in (1, 2, 3, 4):
        raise ValueError('unsupported saved report selection version')
    priority = {(c['pair'], c['strategy']): i for i, c in enumerate(outlook.get('strategy_candidates', []))}
    reviews = [r for r in outlook['strategy_assessments'] if r['assessment'] == 'review']
    def presentation_pending(record):
        if selection_version == 1:
            return 0
        conditions = record.get('scenario_conditions', {})
        return int(conditions.get('status') not in (
            'waiting', 'awaiting_breakout', 'awaiting_retest', 'conditions_observed')
            or record.get('expiry', {}).get('status') == 'withdrawn')
    def practicality(r):
        if selection_version<3:return 0
        return {'reaction_confirmed':0,'confirmation_wait':0,'planned_price_wait':0,'price_plan_recheck':1,'event_recheck':2}.get(r.get('practical_review',{}).get('status'),1)
    ordered = sorted(reviews, key=lambda r: (practicality(r), 'ABC'.index(r['grade']), presentation_pending(r),
                  priority.get((r['pair'], r['strategy']), len(priority))))
    groups = {}
    for index, record in enumerate(ordered):
        group, ratio, _ = saved_plan_comparison(record)
        if selection_version>=3 and group is not None: group=(practicality(record),group)
        if group is not None:
            groups.setdefault(group, []).append((index, record, ratio))
    # Preserve each context's existing slots. Larger RR cannot move a weak or
    # differently formed scenario into another context's earlier slot.
    for members in groups.values():
        ranked = sorted(members, key=lambda item: -item[2])
        for (index, _, _), (_, record, _) in zip(members, ranked):
            ordered[index] = record
    return ordered


def report_records(outlook, *, selection_version=4):
    """Up to three per strategy; do not change any saved assessment."""
    ordered = _ordered_reviews(outlook, selection_version=selection_version)
    if selection_version>=3:
        ordered=[r for r in ordered if 'practical_review' not in r or r['practical_review'].get('status') in ('reaction_confirmed','confirmation_wait','planned_price_wait')]
    return [r for strategy in ('swing','daytrade')
            for r in [x for x in ordered if x['strategy']==strategy][:3]]


def _number(value):
    return f'{value:.8f}'.rstrip('0').rstrip('.') if type(value) in (int, float) and math.isfinite(value) else '未算出'


def _clock(value):
    return datetime.fromtimestamp(value, ZoneInfo('Asia/Tokyo')).strftime('%Y-%m-%d %H:%M:%S JST') if type(value) is int else '未確認'


def _label(r):
    return f"{r['pair'][:3]}/{r['pair'][3:]} {'スイング' if r['strategy']=='swing' else 'デイトレード'}"


def render_strategy_report(snapshot, *, include_all_reviews=False, complete_evidence=False,
                           selection_version=4, comparison_explanation_version=1):
    if type(comparison_explanation_version) is not int or comparison_explanation_version not in (1, 2):
        raise ValueError('unsupported comparison explanation version')
    failures = validate_strategy_snapshot(snapshot)
    if failures:
        raise ValueError('; '.join(failures))
    outlook = snapshot['scheduled_outlook']; rows = outlook['strategy_assessments']
    comparison_notes = comparison_explanations(rows) if comparison_explanation_version == 2 else {}
    shown = ([r for strategy in ('swing', 'daytrade') for r in _ordered_reviews(
                outlook, selection_version=selection_version)
              if r['strategy'] == strategy] if include_all_reviews else report_records(
                  outlook, selection_version=selection_version))
    grades = Counter(r['grade'] for r in rows if r['assessment']=='review')
    omitted = Counter(r['grade'] for r in rows if r['assessment']=='review' and r not in shown)
    counts = outlook['assessment_counts']
    lines = [f"保存評価：{_clock(snapshot['evaluated_at'])}（保存値に基づく判断）",
             f"{len(rows)}戦略：検討{counts['review']}（A{grades['A']}/B{grades['B']}/C{grades['C']}）｜見送り{counts['skip']}｜評価保留{counts['evaluation_pending']}",
             ('A/B/Cはシナリオの優位性・完成度。同評価では具体的な待つ条件を示せる候補を先に掲載。条件の組み直し・再試し失敗・確認状況不明の候補も評価を維持する。同じ確認段階と反対根拠の候補間で保存価格の余地を比較する。'
              if selection_version in (2,3,4) else
              'A/B/Cはシナリオの優位性・完成度。同評価・同じ確認段階と反対根拠の候補間で保存価格の余地を比較し、比較条件が異なる候補の掲載枠は維持する。'),
             '参考RRは保存価格基準で、スプレッド・手数料・滑りを含まない。']
    if selection_version>=3:
        lines.append('優先掲載は価格計画と確認足が評価可能な監視候補。値幅不足・発表をまたぐ候補は再評価待ちとして保存し、掲載外を見送りとはしない。')
    if not shown: lines.append('掲載する検討候補なし。見送りと評価保留の内訳は上記。')
    for r in shown:
        plan = r.get('reference_plan', {}); levels = r.get('reference_levels', {})
        recent = r.get('trigger_price_review', {}); expiry = r.get('expiry', {})
        stamp=plan.get('reference_close_timestamp')
        seconds={'h4':14400,'h1':3600}[r['reference_timeframe']]
        base_closed=stamp+seconds if type(stamp) is int and 0<stamp+seconds<=snapshot['evaluated_at'] else None
        base_clock=f'{_clock(base_closed)}確定' if base_closed is not None else '確定時刻未確認'
        lines += ['', f"{_label(r)}｜{'買い方向' if r['direction']=='long' else '売り方向'}｜{r['grade']}",
                  '評価理由：'+r['grade_reason'],
                  '主根拠：'+'／'.join(r.get('reasons', []) if complete_evidence else r.get('reasons', [])[:2]),
                  '反対根拠：'+('／'.join(r.get('opposing_evidence', []) if complete_evidence else r.get('opposing_evidence', [])[:2]) or '保存評価では具体的な反対根拠の記載なし'),
                  '待ち条件：'+('／'.join(r.get('waiting_conditions', [])) or '未提供'),
                  '成立確認：'+('／'.join(r.get('formation_conditions', [])) or '未提供')+'。成立価格・成立後RRは未確定',
                  f"基準足{r['reference_timeframe'].upper()}保存終値：{_number(plan.get('reference_close'))}（{base_clock}）｜参考RR {_number(levels.get('reference_rr'))}",
                  f"構造無効化：{_number(levels.get('invalidation'))}｜構造目標：{_number(levels.get('structural_target'))}"]
        if selection_version>=3 and r.get('practical_review'):
            lines.append('実用上の位置づけ：'+r['practical_review']['summary'])
        if r.get('technical_context') and not include_all_reviews:
            lines.append('テクニカル要約：'+r['technical_context']['summary'])
        if r.get('swing_environment'):
            lines.append('スイング環境：'+r['swing_environment']['summary'])
        if selection_version>=4 and not include_all_reviews and r.get('decision_brief'):
            b=r['decision_brief']; boundary=b['before_cost_reward_equals_risk_boundary']
            if boundary is not None:
                interval=b['indicative_margin_interval']
                lines.append(f"価格余地の参考範囲：{_number(interval['lower'])}より上、{_number(interval['upper'])}より下（費用前・注文範囲ではない）。範囲外なら再評価")
            lines.append('成立時の確認：'+b['recheck'])
            lines.append('未確認：スプレッド・滑り・手数料を控除した余地。保存価格を現在値と扱わない')
        lines.append(saved_plan_comparison(r)[2])
        if comparison_explanation_version == 2:
            lines.append(comparison_notes[(r['pair'], r['strategy'])])
        condition_plan = r.get('scenario_conditions', {})
        if r.get('scenario_type') == 'range_reversal':
            rc = r['range_context']
            lines.append(f"レンジ候補（暫定）：下側帯 {rc['lower_zone']}｜上側帯 {rc['upper_zone']}。外縁への終値到達で撤回、中央は待機")
        strength=r.get('currency_strength_context', {})
        if strength.get('evaluated_at') == snapshot['evaluated_at'] and strength.get('summary'):
            lines.append('通貨強弱：'+strength['summary'])
        if selection_version>=4 and include_all_reviews:
            calendar=r.get('economic_calendar_context',{})
            lines.append('経済指標：状態='+str(calendar.get('status','unavailable'))+'、鮮度・網羅性未検証。発表予定・値・出典・creditの詳細は同世代の保存view economic_calendar_contextを参照。欠落を安全と扱わない。')
            for event in r.get('practical_review',{}).get('events',[]):
                lines.append('発表再評価：'+str(event.get('id'))+' '+_clock(event.get('scheduled_at_utc')))
        else:
            lines.extend(calendar_lines(r, _clock))
        if condition_plan.get('status') in ('waiting','awaiting_breakout','awaiting_retest','retest_failed','conditions_observed'):
            state = ('条件観測済み' if condition_plan['status']=='conditions_observed' else
                     '再試し失敗・再評価' if condition_plan['status']=='retest_failed' else
                     '突破後の再試し待ち' if condition_plan['status']=='awaiting_retest' else '条件待ち')
            lines.append(f"確認状況：{state}（{_clock(condition_plan.get('evaluated_candle_closed_at'))}確定足）")
            lines.append('条件の適用範囲：保存時の比較水準。新しい確定足では再評価。条件観測は約定・利益保証ではない')
        elif selection_version == 2:
            lines.append('確認状況：条件の組み直し・確認状況の再評価が必要。'+
                         (condition_plan.get('reason') or '具体的な成立条件は保存されていない'))
        pivot=plan.get('target_pivot')
        reaction = r.get('price_reaction_observation', {})
        if (reaction.get('status') in ('observed_reference', 'not_observed')
                and reaction.get('timeframe') == r['trigger_timeframe']
                and reaction.get('evaluated_at') == snapshot['evaluated_at']
                and type(reaction.get('closed_at')) is int
                and 0 < reaction['closed_at'] <= snapshot['evaluated_at']):
            lines.append(f"保存足の反応（{r['trigger_timeframe'].upper()}・{_clock(reaction['closed_at'])}確定）：" + reaction_description(reaction))
        if (isinstance(pivot,dict) and type(pivot.get('price')) in (int,float)
                and math.isfinite(pivot['price']) and pivot['price']>0
                and pivot.get('price')==levels.get('structural_target')
                and type(pivot.get('timestamp')) is int and 0<pivot['timestamp']<=snapshot['evaluated_at']):
            kind='高値' if r['direction']=='long' else '安値'
            lines.append(f"目標根拠：{r['reference_timeframe'].upper()}の確認済み{kind} {_number(pivot.get('price'))}（足開始 {_clock(pivot['timestamp'])}）。保存価格計画の構造目標（参考投影とは別）")
        elif levels.get('structural_target') is None:
            lines.append('目標根拠：構造目標は未算出。参考投影で代用しない')
        else:
            lines.append('目標根拠：保存評価に元の確定ピボット情報なし。根拠時刻を推定しない')
        if recent.get('status') == 'observed_reference':
            lines.append(f"確認足{r['trigger_timeframe'].upper()}保存終値：{_number(recent.get('saved_close'))}（{_clock(recent.get('closed_at'))}確定）｜別計算の参考RR {_number(recent.get('reference_rr'))}")
        else: lines.append('確認足保存終値の再計算：未確認。基準足RRを成立後RRに流用しない')
        projections = r.get('reference_projection', {}).get('targets', [])
        lines.append('通常Fib参考投影（構造目標と別）：'+('／'.join(f"{p['ratio']}倍 {_number(p.get('price'))}（投影RR {_number(p.get('reference_rr'))}）" for p in projections) or '未算出'))
        conditions = expiry.get('withdrawal_conditions', [])
        lines.append('撤回条件（検証済み保存確定足）：'+('／'.join(f"{'無効化' if c['condition']=='invalidation_crossed' else '構造目標到達'} {c['relation']} {_number(c.get('price'))}" for c in conditions) or '価格水準未算出。次の基準足で再評価'))
        lines.append('時間失効：未定義。期限は推定しない')
        if r.get('uncertainties'): lines.append('未確認：'+'／'.join(r['uncertainties']))
    lines += ['', f"非掲載の検討候補：{sum(omitted.values())}（A{omitted['A']}/B{omitted['B']}/C{omitted['C']}）。非掲載を見送りと扱わない。"]
    withdrawn = [r for r in rows if r.get('expiry', {}).get('status')=='withdrawn']
    reasons = {'saved_trigger_target_reached':'確認足保存終値が旧構造目標に到達',
               'saved_trigger_invalidation_crossed':'確認足保存終値が構造無効化を越境',
               'saved_base_invalidation_crossed':'基準足保存終値が構造無効化を越境',
               'confirmed_trigger_invalidation':'検証済み確認足で無効化を観測'}
    for r in withdrawn:
        lines.append(f"撤回：{_label(r)}｜{reasons.get(r['expiry'].get('observed_condition'), r['grade_reason'])}")
    lines.append('上記は保存されたシナリオの報告。現在価格・約定・損益・通知到達は未確認。')
    return '\n'.join(lines)
