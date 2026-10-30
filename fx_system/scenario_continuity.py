"""Compare adjacent immutable assessments; never alter grading or rank candidates."""
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import hashlib
from .strategy_report_export import restore_strategy_report_export
from .strategy_report import report_records

SCHEMA = 'saved_scenario_continuity_v1'
FIELDS = ('direction','grade','reference_levels','invalidation','waiting_conditions',
          'formation_conditions','scenario_conditions','opposing_evidence','reasons','swing_context',
          'technical_outlook','wave_price_plan')
LABELS = {'direction':'方向','grade':'評価','reference_levels':'構造水準',
          'invalidation':'撤回水準','waiting_conditions':'待つ条件',
          'formation_conditions':'成立条件','scenario_conditions':'確認段階',
          'opposing_evidence':'反対根拠','reasons':'主根拠','swing_context':'スイング大局と仕掛け',
          'technical_outlook':'テクニカル見通し','wave_price_plan':'波の価格計画'}


def _brief(record):
    result = {k:deepcopy(record.get(k)) for k in
            ('assessment','direction','grade','grade_reason','skip_reason','expiry',
             'reference_levels','invalidation','waiting_conditions','formation_conditions',
             'scenario_conditions','reasons','opposing_evidence')}
    if 'swing_context' in record:
        result['swing_context'] = deepcopy(record['swing_context'])
    for field in ('technical_outlook','wave_price_plan'):
        if field in record:result[field]=deepcopy(record[field])
    return result


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
            if field=='swing_context' and isinstance(item,dict):
                return {k:item.get(k) for k in ('direction','structure_status','entry_status','entry_pause_reason')}
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
                label = '仕掛け計画停止：' if current.get('swing_context', {}).get('entry_status') == 'paused' else '今回保存は撤回状態：'
                text+='。'+label+str(current['expiry'].get('reason') or current.get('skip_reason') or current.get('grade_reason') or '理由は今回評価を参照')
            elif row['status']=='no_longer_reviewed':
                text+='。今回理由：'+str(current.get('skip_reason') or current.get('grade_reason') or '今回評価を参照')
            follow=row.get('previous_condition_followthrough',{})
            observation=follow.get('condition_observation')
            if observation:
                text+='。前回固定条件を保存間の確定足で観測（'+clock(observation['closed_at'])+'）'
                text+='。その終値の費用前価格余地は'+('あり' if observation['margin_sufficient_before_costs'] else '不足・不整合')
                if not observation['base_close_coverage_complete']:
                    text+='（基準足の撤回検証に未確認区間あり）'
            elif follow.get('status')=='frozen_condition_not_seen_in_whole_candles':
                text+='。前回固定条件は保存間の完全な確認足では未観測'
            elif follow.get('status')=='frozen_retest_failed':
                text+='。前回固定条件の再試しは終値で維持できず'
            elif follow and follow.get('status') not in ('not_monitorable_at_save','already_observed_at_save','close_based_withdrawal_observed'):
                text+='。前回固定条件の保存間検証は未確認'
            if follow.get('base_close_withdrawal'):
                text+='。前回固定水準の基準足終値による撤回条件を観測'
            if follow.get('trigger_close_withdrawal'):
                text+=('。前回の局所仕掛け停止・経路目標到達を観測（基準足の大局撤回とは別）'
                       if follow.get('trigger_withdrawal_scope')=='local_entry_only' else
                       '。前回M15仕掛け計画の停止条件を観測（H4大局の撤回とは別）'
                       if row['previous'].get('swing_context') else '。前回固定水準の確認足終値による撤回条件を観測')
            if follow.get('base_objective_observation'):
                text+='。前回の経路目標への到達を基準足で観測（約定・大局撤回ではない）'
            if current.get('swing_context'):
                text+='。大局：'+current['swing_context']['summary']
            lines.append(text)
    lines.append('同方向でも同一の固定シナリオが継続有効とは限らない。前回の水準を今回へ上書きせず、成立・撤回・目標は各保存時点で区別する。')
    return '\n'.join(lines)


def build_continuity(current_bundle, source, blob, previous_bundle=None, previous_source=None, previous_blob=None,
                     *, current_snapshot_bytes=None):
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
        if current_snapshot_bytes is not None:
            result['followthrough_status']='snapshot_identity_unverified'
            if (isinstance(current_snapshot_bytes,bytes)
                and hashlib.sha1(b'blob '+str(len(current_snapshot_bytes)).encode()+b'\0'+current_snapshot_bytes).hexdigest()==blob):
                snapshot=json.loads(current_snapshot_bytes)
                if snapshot.get('evaluated_at')==source['evaluated_at'] and isinstance(snapshot.get('pairs'),dict):
                    from .scenario_followthrough import observe_frozen_condition
                    old={(r['pair'],r['strategy']):r for r in previous['scheduled_outlook']['strategy_assessments']}
                    for row in rows:
                        try:
                            follow=observe_frozen_condition(old[row['pair'],row['strategy']],
                                snapshot['pairs'].get(row['pair'],{}),source['evaluated_at'])
                        except (ValueError,KeyError,TypeError,AttributeError,OverflowError):
                            follow={'status':'followup_input_invalid','condition_observation':None}
                        row['previous_condition_followthrough']=follow
                    result['followthrough_status']='same_snapshot_saved_candles_checked'
        result.update(status='saved',reason=None,previous_source=deepcopy(previous_source),
            previous_snapshot_git_blob_sha=previous_blob,rows=rows,
            text=render(rows,previous_source['evaluated_at'],source['evaluated_at']))
        if result.get('followthrough_status')=='same_snapshot_saved_candles_checked':
            result['text']+='\n前回固定条件の後続確認は、今回snapshotと同一blobの保存足のみを使用。評価時刻をまたぐ途中足・欠損・出所未確認は除外。現在のシナリオ有効性・約定・費用控除後の成績とは別。各行の被覆・除外時間を参照。'
        if len(json.dumps(result,ensure_ascii=False).encode())>512*1024:
            raise ValueError('bounded comparison exceeded')
        return result
    except Exception:
        return {**result,'status':'unavailable','reason':'adjacent_saved_comparison_unavailable','rows':[],'text':None}
