"""Small private, preselected report; no new trading decisions or market calls."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import re

HEADER = re.compile(r'^([A-Z]{3})/([A-Z]{3})｜(スイング|デイトレード)｜(.+)$')
JST = timezone(timedelta(hours=9))


def _build_task_report(report, strength, slot, continuity):
    source = report['source']
    blob = report['snapshot_git_blob_sha']
    out = {'schema':'saved_task_report_v1', 'source':deepcopy(source),
           'snapshot_git_blob_sha':blob, 'status':'unavailable',
           'target_scheduled_for':None, 'assessment_counts':report.get('assessment_counts', {}),
           'sections':{}, 'report_text':None}
    def same(value):
        return isinstance(value, dict) and value.get('source') == source and value.get('snapshot_git_blob_sha') == blob
    if report.get('status') != 'saved' or not isinstance(report.get('report_text'), str):
        return out
    if same(slot) and slot.get('status') == 'assigned':
        out['target_scheduled_for'] = slot['target_scheduled_for']
    previous = {}
    if same(continuity) and continuity.get('status') == 'saved':
        previous = {(r['pair'], r['strategy']):r for r in continuity.get('rows', [])}
    sections = {'swing':[], 'daytrade':[]}
    blocks = []
    for line in report['report_text'].splitlines():
        match = HEADER.match(line)
        if match:
            blocks.append((match, line, []))
        elif blocks:
            blocks[-1][2].append(line)
    for match, heading, lines in blocks:
        pair = match[1]+match[2]
        strategy = 'swing' if match[3] == 'スイング' else 'daytrade'
        if len(sections[strategy]) >= 3:
            continue
        def field(prefix):
            return next((line[len(prefix):] for line in lines if line.startswith(prefix)), None)
        row = previous.get((pair, strategy), {})
        follow = row.get('previous_condition_followthrough', {})
        current, old = row.get('current', {}), row.get('previous', {})
        target = current.get('reference_levels', {}).get('scenario_target')
        reached = bool(follow.get('base_objective_observation')) or any(
            (follow.get(k) or {}).get('condition') in ('path_objective_reached','structural_target_reached')
            for k in ('trigger_close_withdrawal','base_close_withdrawal'))
        excluded = (strategy == 'swing' and reached and target is not None
                    and follow.get('original_target') == target
                    and current.get('direction') == old.get('direction')
                    and current.get('direction') in ('long','short'))
        candidate = {'pair':pair, 'strategy':strategy, 'heading':heading,
                     'excluded_target_reached':excluded}
        if excluded:
            candidate['text'] = heading+'\n前回目標到達 → 新しい価格計画待ち：'+str(target)
        else:
            parts = [('次に見る',field('確認足 ')), ('値幅',field('残り値幅：')),
                     ('水準',field('途中障害：')), ('根拠',field('見通し：')),
                     ('懸念',field('懸念：'))]
            evidence = field('根拠：') or ''
            changes = re.findall(r'(H[14])スパン：[^\n]*?確定足の変化：([^／\n]+)', evidence)
            if changes:
                parts.append(('変化', '／'.join(tf+' '+change for tf,change in changes)))
            conflict = report.get('conflict_role_lines', {}).get(pair)
            if conflict and strategy == 'swing':
                parts.append(('方向競合', conflict))
            from .followthrough_summary import describe as describe_followthrough
            outcome = describe_followthrough(row)
            if outcome:
                parts.append(('前回経過', outcome))
            stop, invalidate = field('局所停止：'), field('大局撤回：')
            if stop or invalidate:
                parts.append(('見直し', (stop or '局所停止未確認')+'／大局撤回：'+(invalidate or '未確認')))
            candidate['text'] = '**'+heading+'**\n'+'\n'.join(
                '- **'+label+'** '+value for label,value in parts if value)
        sections[strategy].append(candidate)
    clock = datetime.fromtimestamp(source['evaluated_at'], JST)
    target_clock = out['target_scheduled_for']
    title = (datetime.fromtimestamp(target_clock,JST).strftime('%m/%d %H:%M')+' JST'
             if target_clock else '対象枠未確認')
    text = ['# FX判断｜'+title+'（保存評価 '+clock.strftime('%H:%M')+'）', '## 通貨強弱']
    if same(strength) and strength.get('status') == 'saved':
        from .strength_export import render_strength_summary
        text.append(render_strength_summary(strength['currency_strength'],source['evaluated_at']))
    else:
        text.append('通貨強弱のみ未確認。候補は同時刻の保存評価を掲載。')
    for strategy,label in (('swing','短期スイング TOP3'),('daytrade','デイトレ TOP3')):
        text.append('## '+label)
        text.extend(c['text'] for c in sections[strategy])
        if not sections[strategy]:
            text.append('保存レポートの優先掲載候補なし。全体の見送りを意味しません。')
    text.append('価格は保存確定足の値です。局所条件観測は約定ではありません。')
    out.update(status='saved', sections=sections, report_text='\n\n'.join(text))
    return out


def build_task_report(report, strength, slot, continuity):
    # This optional projection must not prevent saving the original judgment.
    try:
        return _build_task_report(report, strength, slot, continuity)
    except Exception:
        return {'schema':'saved_task_report_v1', 'source':deepcopy(report.get('source')),
                'snapshot_git_blob_sha':report.get('snapshot_git_blob_sha'),
                'status':'unavailable', 'report_text':None, 'sections':{}}
