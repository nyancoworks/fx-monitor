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


def _price_and_caution(value):
    if not value:
        return None, None
    for suffix, caution in (('｜手前余地に注意', '手前の節目までの距離は大局撤回までの距離以下'),
                            ('｜目標余地に注意', '波の目標までの距離は大局撤回までの距離以下')):
        if value.endswith(suffix):
            return value[:-len(suffix)], caution
    return value, None


def _plain_heading(heading, plan_wait=False, early_reaction=False):
    parts = heading.split('｜')
    if len(parts) != 4:
        return heading
    match = re.fullmatch(r'(買い|売り)([ABC])', parts[2])
    if not match:
        return heading
    if plan_wait:
        symbol, state = '⚪', '新しい価格計画待ち'
    elif early_reaction:
        symbol, state = '🟡', '初動のみ・H1トレンド待ち'
    else:
        symbol, state = {
            '条件待ち':('🟡', '足の確認待ち'),
            '局所条件観測済み':('🔵', '反応あり・再確認'),
        }.get(parts[3], ('', parts[3]))
    return (symbol+' ' if symbol else '')+parts[0]+'｜'+match[1]+'方向の監視候補（'+match[2]+'）｜'+state


def _swing_h4_context(record, clock):
    from .mt4_calendar import aggregate_h4, expected_h4, next_complete_start

    missing = '連続する確定4時間足を確認できず'
    trigger = record.get('standard_inputs', {}).get('trigger', {})
    direction = record.get('direction')
    if (direction not in ('long', 'short') or trigger.get('timeframe') != 'h1'
            or trigger.get('verified') is not True or trigger.get('evaluated_at') != clock):
        return missing
    try:
        bars = aggregate_h4(trigger.get('bars', [])[-16:])
        if len(bars) < 2:
            return missing
        previous, current = bars[-2:]
        if (current['timestamp'] != expected_h4(clock)
                or next_complete_start(previous['timestamp']) != current['timestamp']):
            return missing
        if current['high'] > previous['high'] and current['low'] > previous['low']:
            move, structure = 'long', '高値・安値を切り上げ'
        elif current['high'] < previous['high'] and current['low'] < previous['low']:
            move, structure = 'short', '高値・安値を切り下げ'
        else:
            move, structure = None, '高値・安値の更新方向が揃わず'
        relation = ('日足の想定方向と一致' if move == direction else
                    '日足の想定方向と逆行' if move else '方向確認待ち')
        closed = datetime.fromtimestamp(current['timestamp'] + 14400, JST)
        return f'{closed:%m/%d %H:%M} JST確定｜{structure}。{relation}'
    except (KeyError, TypeError, ValueError, OverflowError):
        return missing


def _build_task_report(report, strength, slot, continuity, swing_records=None):
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
            candidate['text'] = '**'+_plain_heading(heading, plan_wait=True)+'**\n前回目標到達 → 新しい価格計画待ち：'+str(target)
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
            situation = (outlook or '方向の根拠は保存評価を参照')
            if concern and concern not in situation:
                situation += '。ただし '+concern
            early_reaction = field('スイング初動：') if strategy == 'swing' else None
            if early_reaction:
                condition = '／'.join(filter(None, (condition, early_reaction)))
            parts = [('見る', condition)]
            if strategy == 'swing' and swing_records is not None:
                parts.append(('4時間足', _swing_h4_context(
                    swing_records.get(pair, {}), source['evaluated_at'])))
            evidence = field('根拠：') or ''
            changes = re.findall(r'(H[14])スパン：[^\n]*?確定足の変化：([^／\n]+)', evidence)
            if changes:
                situation += '／'+ '／'.join(tf+' '+change for tf, change in changes)
            conflict = report.get('conflict_role_lines', {}).get(pair)
            if conflict and strategy == 'swing':
                situation += '／方向競合：'+conflict
            from .followthrough_summary import describe as describe_followthrough
            outcome = describe_followthrough(row)
            if outcome:
                situation += '／前回：'+outcome
            stop, invalidate = field('局所停止：'), field('大局撤回：')
            price, caution = _price_and_caution(_price_path(field('残り値幅：'), field('途中障害：')))
            withdrawal = ('局所停止 '+(_first_sentence(stop) or '未確認')+
                          '／大局撤回 '+(invalidate or '未確認'))
            parts.extend([('価格の流れ', price),
                          ('理由と注意', situation+('。'+caution if caution else '')),
                          ('見直す水準', withdrawal)])
            candidate['text'] = '**'+_plain_heading(heading, early_reaction=bool(early_reaction))+'**\n'+'\n'.join(
                '- **'+label+'** '+value for label,value in parts if value)
        sections[strategy].append(candidate)
    clock = datetime.fromtimestamp(source['evaluated_at'], JST)
    target_clock = out['target_scheduled_for']
    title = (datetime.fromtimestamp(target_clock,JST).strftime('%m/%d %H:%M')+' JST'
             if target_clock else '対象枠未確認')
    text = ['# FX監視候補｜'+title+'（保存評価 '+clock.strftime('%H:%M')+'）',
            '## 通貨強弱']
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
    text.append('🟡 足の確認待ち／🔵 反応あり・再確認／⚪ 新しい価格計画待ち。A/B/Cはシナリオの完成度です。価格は保存確定足、余地は大局撤回幅との比較（費用前）。売買前に現在値と確定足を確認。反応観測は約定ではありません。')
    out.update(status='saved', sections=sections, report_text='\n\n'.join(text))
    return out


def build_task_report(report, strength, slot, continuity, swing_records=None, *, outlook=None):
    # This optional projection must not prevent saving the original judgment.
    try:
        if outlook and outlook.get('murphy_profile_version') == 1 and report.get('status') == 'saved':
            from .murphy_report import task_report
            result = task_report(report, strength, slot, continuity, outlook)
        else:
            result = _build_task_report(report, strength, slot, continuity, swing_records)
        if result['status'] == 'saved' and 'research_digest' in report:
            result['research_digest'] = deepcopy(report['research_digest'])
        return result
    except Exception:
        return {'schema':'saved_task_report_v1', 'source':deepcopy(report.get('source')),
                'snapshot_git_blob_sha':report.get('snapshot_git_blob_sha'),
                'status':'unavailable', 'report_text':None, 'sections':{}}


def build_delivery_report(task_report, diagnostic):
    """Keep the notification input small and bind it to validated storage."""
    source = task_report.get('source')
    blob = task_report.get('snapshot_git_blob_sha')
    target = task_report.get('target_scheduled_for')
    text = task_report.get('report_text')
    ready = (
        task_report.get('status') == 'saved'
        and type(target) is int and target > 0
        and isinstance(text, str) and bool(text.strip())
        and len(text.encode('utf-8')) <= 16_000
        and diagnostic.get('source') == source
        and diagnostic.get('snapshot_git_blob_sha') == blob
        and diagnostic.get('validation', {}).get('passed') is True
        and len(diagnostic.get('pairs', {})) == 16
    )
    return {'schema': 'saved_delivery_report_v1', 'source': source,
            'snapshot_git_blob_sha': blob, 'target_scheduled_for': target,
            'status': 'saved' if ready else 'unavailable',
            'report_text': text if ready else None}
