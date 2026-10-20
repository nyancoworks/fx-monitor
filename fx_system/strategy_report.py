"""Read-only Japanese report of canonical saved assessments; no market fetches."""
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo
import math
from .validate_strategy_snapshot import validate_strategy_snapshot
from .price_reaction_observation import reaction_description


def report_records(outlook):
    """Presentation order only: grade, then existing candidate order."""
    priority = {(c['pair'], c['strategy']): i for i, c in enumerate(outlook.get('strategy_candidates', []))}
    reviews = [r for r in outlook['strategy_assessments'] if r['assessment'] == 'review']
    return sorted(reviews, key=lambda r: ('ABC'.index(r['grade']),
                  priority.get((r['pair'], r['strategy']), len(priority))))[:3]


def _number(value):
    return f'{value:.8f}'.rstrip('0').rstrip('.') if type(value) in (int, float) and math.isfinite(value) else '未算出'


def _clock(value):
    return datetime.fromtimestamp(value, ZoneInfo('Asia/Tokyo')).strftime('%Y-%m-%d %H:%M:%S JST') if type(value) is int else '未確認'


def _label(r):
    return f"{r['pair'][:3]}/{r['pair'][3:]} {'スイング' if r['strategy']=='swing' else 'デイトレード'}"


def render_strategy_report(snapshot):
    failures = validate_strategy_snapshot(snapshot)
    if failures:
        raise ValueError('; '.join(failures))
    outlook = snapshot['scheduled_outlook']; rows = outlook['strategy_assessments']
    shown = report_records(outlook); grades = Counter(r['grade'] for r in rows if r['assessment']=='review')
    omitted = Counter(r['grade'] for r in rows if r['assessment']=='review' and r not in shown)
    counts = outlook['assessment_counts']
    lines = [f"保存評価：{_clock(snapshot['evaluated_at'])}（保存値に基づく判断）",
             f"{len(rows)}戦略：検討{counts['review']}（A{grades['A']}/B{grades['B']}/C{grades['C']}）｜見送り{counts['skip']}｜評価保留{counts['evaluation_pending']}",
             'A/B/Cはシナリオの優位性・完成度。掲載順は評価と保存済み候補順による。',
             '参考RRは保存価格基準で、スプレッド・手数料・滑りを含まない。']
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
                  '主根拠：'+'／'.join(r.get('reasons', [])[:2]),
                  '反対根拠：'+('／'.join(r.get('opposing_evidence', [])[:2]) or '保存評価では具体的な反対根拠の記載なし'),
                  '待ち条件：'+('／'.join(r.get('waiting_conditions', [])) or '未提供'),
                  '成立確認：'+('／'.join(r.get('formation_conditions', [])) or '未提供')+'。成立価格・成立後RRは未確定',
                  f"基準足{r['reference_timeframe'].upper()}保存終値：{_number(plan.get('reference_close'))}（{base_clock}）｜参考RR {_number(levels.get('reference_rr'))}",
                  f"構造無効化：{_number(levels.get('invalidation'))}｜構造目標：{_number(levels.get('structural_target'))}"]
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
