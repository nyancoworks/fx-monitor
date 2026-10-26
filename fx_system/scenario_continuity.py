"""Compare adjacent immutable assessments; never alter grading or rank candidates."""
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo
import json
from .strategy_report_export import restore_strategy_report_export
from .strategy_report import report_records

SCHEMA = 'saved_scenario_continuity_v1'
FIELDS = ('direction','grade','reference_levels','invalidation','waiting_conditions',
          'formation_conditions','scenario_conditions','opposing_evidence','reasons')
LABELS = {'direction':'方向','grade':'評価','reference_levels':'構造水準',
          'invalidation':'撤回水準','waiting_conditions':'待つ条件',
          'formation_conditions':'成立条件','scenario_conditions':'確認段階',
          'opposing_evidence':'反対根拠','reasons':'主根拠'}


def _brief(record):
    return {k:deepcopy(record.get(k)) for k in
            ('assessment','direction','grade','grade_reason','skip_reason','expiry',
             'reference_levels','invalidation','waiting_conditions','formation_conditions',
             'scenario_conditions','reasons','opposing_evidence')}


def compare_views(current, previous, *, current_selection_version=2, previous_selection_version=2):
    """Called only after both views are restored and bound to their saved blobs."""
    new = current['scheduled_outlook']['strategy_assessments']
    old = {(r['pair'],r['strategy']):r for r in previous['scheduled_outlook']['strategy_assessments']}
    selected_new = {(r['pair'],r['strategy']) for r in report_records(current['scheduled_outlook'],selection_version=current_selection_version)}
    selected_old = {(r['pair'],r['strategy']) for r in report_records(previous['scheduled_outlook'],selection_version=previous_selection_version)}
    rows=[]
    for record in new:
        key=(record['pair'],record['strategy']); prior=old[key]
        def evidence(value, field):
            item=value.get(field)
            if field=='scenario_conditions' and isinstance(item,dict):
                return {k:item.get(k) for k in ('status','route','conditions','reason')}
            return item
        changed=[k for k in FIELDS if evidence(prior,k)!=evidence(record,k)]
        was=prior.get('assessment')=='review'; active=record.get('assessment')=='review'
        pending=record.get('assessment')=='evaluation_pending'
        if pending: status='evaluation_pending'
        elif was and not active: status='no_longer_reviewed'
        elif active and not was: status='newly_reviewed'
        elif was and active:
            status='direction_changed' if 'direction' in changed else 'same_direction'
        else: status='not_reviewed'
        rows.append({'pair':key[0],'strategy':key[1],'status':status,
            'changed_fields':changed,'previous':_brief(prior),'current':_brief(record),
            'previous_default_listed':key in selected_old,'current_default_listed':key in selected_new})
    return rows


def render(rows, previous_clock, current_clock):
    def clock(value): return datetime.fromtimestamp(value,ZoneInfo('Asia/Tokyo')).strftime('%m/%d %H:%M')
    lines=[f'前回保存 {clock(previous_clock)} → 今回保存 {clock(current_clock)} JST。保存既定掲載の比較で、実際の通知掲載履歴とは別。']
    status_names={'evaluation_pending':'データ不足で評価保留','no_longer_reviewed':'今回は候補外',
                  'newly_reviewed':'今回候補へ','direction_changed':'方向変更','same_direction':'同方向の監視を継続'}
    for strategy,name in [('swing','スイング'),('daytrade','デイトレード')]:
        lines.append(name+'の経過：')
        for row in rows:
            if row['strategy']!=strategy or (row['previous']['assessment']!='review' and row['current']['assessment']!='review'): continue
            def desc(r):
                return ('買い' if r['direction']=='long' else '売り' if r['direction']=='short' else '方向なし')+'／'+str(r['grade'] or r['assessment'])
            text=f"{row['pair']}：{desc(row['previous'])} → {desc(row['current'])}。{status_names.get(row['status'],'監視対象外')}"
            if row['changed_fields']:text+='。更新：'+'・'.join(LABELS[k] for k in row['changed_fields'])
            if row['previous_default_listed'] and not row['current_default_listed']:
                text+='。保存既定掲載から外れた（撤回とは別）'
            current=row['current']
            if current.get('expiry',{}).get('status')=='withdrawn':
                text+='。今回保存は撤回状態：'+str(current['expiry'].get('reason') or current.get('skip_reason') or current.get('grade_reason') or '理由は今回評価を参照')
            elif row['status']=='no_longer_reviewed':
                text+='。今回理由：'+str(current.get('skip_reason') or current.get('grade_reason') or '今回評価を参照')
            lines.append(text)
    lines.append('同方向でも同一の固定シナリオが継続有効とは限らない。前回の水準を今回へ上書きせず、成立・撤回・目標は各保存時点で区別する。')
    return '\n'.join(lines)


def build_continuity(current_bundle, source, blob, previous_bundle=None, previous_source=None, previous_blob=None):
    result={'schema':SCHEMA,'source':deepcopy(source),'snapshot_git_blob_sha':blob,
            'status':'unavailable','reason':'adjacent_saved_comparison_unavailable','rows':[],'text':None}
    try:
        current=restore_strategy_report_export(current_bundle,source,blob)
        previous=restore_strategy_report_export(previous_bundle,previous_source,previous_blob)
        if (previous_source['source_repository']!=source['source_repository'] or
            previous_source['evaluated_at']>=source['evaluated_at'] or
            previous_source['run_id']==source['run_id']): return result
        rows=compare_views(current,previous,
            current_selection_version=current_bundle.get('selection_version',1),
            previous_selection_version=previous_bundle.get('selection_version',1))
        result.update(status='saved',reason=None,previous_source=deepcopy(previous_source),
            previous_snapshot_git_blob_sha=previous_blob,rows=rows,
            text=render(rows,previous_source['evaluated_at'],source['evaluated_at']))
        if len(json.dumps(result,ensure_ascii=False).encode())>512*1024:
            raise ValueError('bounded comparison exceeded')
        return result
    except Exception:
        return {**result,'status':'unavailable','reason':'adjacent_saved_comparison_unavailable','rows':[],'text':None}
