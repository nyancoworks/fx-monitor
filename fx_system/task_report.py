"""Small private, preselected report; no new trading decisions or market calls."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import re

HEADER = re.compile(r'^([A-Z]{3})/([A-Z]{3})｜(スイング|デイトレード)｜(.+)$')
JST = timezone(timedelta(hours=9))


def _first_sentence(value):
    return value.split('。', 1)[0] if value else None


def _brief_outlook(value):
    return '。'.join(value.split('。')[:2]) if value else None


def _main_conflict(value):
    if not value:
        return None
    parts = value.split('／')
    # The full saved assessment retains every indicator. Lead with an opposed
    # base timeframe when present; otherwise show the first stated caution.
    opposed = next((part for part in parts if 'H4の背景：' in part and '逆方向' in part), None)
    if opposed:
        higher = '、W1も逆方向' if any('W1上位SB背景' in part for part in parts) else ''
        return 'H4が逆方向' + higher
    return _first_sentence(parts[0])


def _price_path(width, levels):
    if not width:
        return levels
    if not levels or '／経路目標：' not in levels:
        return width + ('／'+levels if levels else '')
    pieces = width.split('｜')
    if len(pieces) < 3 or not pieces[1].startswith('手前の節目 ') or not pieces[2].startswith('波の目標 '):
        return width + '／' + levels
    near, objective = levels.split('／経路目標：', 1)
    first_distance = pieces[1].removeprefix('手前の節目 ').strip()
    wave_distance = pieces[2].removeprefix('波の目標 ').strip()
    first = ('最初の節目 '+near + ('（'+first_distance+'先）' if 'pips' in first_distance else '')
             if near != '未確認' else '最初の節目 未確認')
    wave = '波の目標 '+objective + ('（'+wave_distance+'先）' if 'pips' in wave_distance else '')
    caution = ''
    if any('手前の節目までの値幅が大局撤回幅以下' in item for item in pieces[3:]):
        caution = '｜手前余地に注意'
    elif any('波の目標までの値幅が大局撤回幅以下' in item for item in pieces[3:]):
        caution = '｜目標余地に注意'
    return pieces[0].strip()+' → '+first+' → '+wave+caution


def _plain_heading(heading):
    parts = heading.split('｜')
    if len(parts) != 4:
        return heading
    match = re.fullmatch(r'(買い|売り)([ABC])', parts[2])
    if not match:
        return heading
    state = {'条件待ち':'確認待ち', '局所条件観測済み':'反応確認'}.get(parts[3], parts[3])
    return parts[0]+'｜'+match[1]+match[2]+'・'+state


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
            condition = field('確認足 ')
            if condition:
                condition = condition.split('。', 1)[0].replace('｜待つ条件：', '｜')
                condition = condition.replace('次のいずれかの反応待ち：', '反応待ち：')
                condition = condition.replace('（全一致は不要）', '')
                condition = condition.replace('局所条件観測済み：', '観測：')
                condition = condition.replace('15分足の確定足で', '').replace('5分足の確定足で', '')
                condition = condition.replace('動きを観測', '').replace('MACDシグナル交差', 'MACD交差')
                condition = condition.replace('終値の', '').replace('を下抜けまたは下側維持', '下抜け・維持')
                condition = condition.replace('を上抜けまたは上側維持', '上抜け・維持')
            outlook = _brief_outlook(field('見通し：'))
            concern = _main_conflict(field('懸念：'))
            situation = (outlook or '方向の根拠は保存評価を参照') + ('。ただし '+concern if concern else '')
            parts = [('いま', situation), ('次に確認', condition),
                     ('価格',_price_path(field('残り値幅：'),field('途中障害：')))]
            evidence = field('根拠：') or ''
            changes = re.findall(r'(H[14])スパン：[^\n]*?確定足の変化：([^／\n]+)', evidence)
            if changes:
                parts[0] = ('いま', situation+'／'+ '／'.join(tf+' '+change for tf, change in changes))
            conflict = report.get('conflict_role_lines', {}).get(pair)
            if conflict and strategy == 'swing':
                parts.append(('方向競合', conflict))
            from .followthrough_summary import describe as describe_followthrough
            outcome = describe_followthrough(row)
            if outcome:
                parts.append(('前回経過', outcome))
            stop, invalidate = field('局所停止：'), field('大局撤回：')
            if stop or invalidate:
                parts.append(('見直す', (_first_sentence(stop) or '局所停止未確認')+
                              '／大局の撤回：'+(invalidate or '未確認')))
            candidate['text'] = '**'+_plain_heading(heading)+'**\n'+'\n'.join(
                '- **'+label+'** '+value for label,value in parts if value)
        sections[strategy].append(candidate)
    clock = datetime.fromtimestamp(source['evaluated_at'], JST)
    target_clock = out['target_scheduled_for']
    title = (datetime.fromtimestamp(target_clock,JST).strftime('%m/%d %H:%M')+' JST'
             if target_clock else '対象枠未確認')
    text = ['# FX判断｜'+title+'（保存評価 '+clock.strftime('%H:%M')+'）', '## 通貨強弱']
    if same(strength) and strength.get('status') == 'saved':
        from .strength_export import render_strength_summary
        text.append(render_strength_summary(strength['currency_strength'],source['evaluated_at']).splitlines()[0])
    else:
        text.append('通貨強弱のみ未確認。候補は同時刻の保存評価を掲載。')
    for strategy,label in (('swing','短期スイング TOP3'),('daytrade','デイトレ TOP3')):
        text.append('## '+label)
        text.extend(c['text'] for c in sections[strategy])
        if not sections[strategy]:
            text.append('保存レポートの優先掲載候補なし。全体の見送りを意味しません。')
    text.append('強弱は参考。価格は保存確定足、余地は大局撤回幅との比較（費用前）。反応観測は約定ではありません。')
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
