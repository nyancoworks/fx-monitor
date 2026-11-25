import unittest
from copy import deepcopy
from fx_system.task_report import build_delivery_report, build_task_report


def inputs():
    source={'evaluated_at':1794549600,'source_repository':'nyancoworks/fx-monitor',
            'source_commit':'a'*40,'run_id':1}
    identity={'source':source,'snapshot_git_blob_sha':'b'*40,'status':'saved'}
    blocks=[]
    for strategy in ('スイング','デイトレード'):
        for pair in ('EUR/USD','GBP/USD','NZD/USD'):
            blocks.append(pair+'｜'+strategy+'｜売りB｜条件待ち\n確認足 M15｜次のいずれか\n局所停止：M15終値2以上\n大局撤回：H4終値3以上\n途中障害：0.9／経路目標：0.8\n残り値幅：保存終値1\n見通し：調整中\n懸念：勢い未確認\n経済指標：大きな補助資料')
    report={**identity,'report_text':'\n\n'.join(blocks),'assessment_counts':{'review':32}}
    return report, {}, {**identity,'status':'assigned','target_scheduled_for':1794549600}, {**identity,'rows':[]}


class TaskReportTests(unittest.TestCase):
    def test_delivery_omits_ledger_and_requires_matching_validation(self):
        task = build_task_report(*inputs())
        task['research_followup'] = 'x' * 300_000
        diag = {**{k: task[k] for k in ('source', 'snapshot_git_blob_sha')},
                'validation': {'passed': True}, 'pairs': dict.fromkeys(range(16))}
        result = build_delivery_report(task, diag)
        self.assertEqual(result['status'], 'saved')
        self.assertEqual(result['report_text'], task['report_text'])
        self.assertNotIn('research_followup', result)
        for changed in ({'snapshot_git_blob_sha': 'c' * 40},
                        {'validation': {'passed': False}}, {'pairs': {}}):
            rejected = build_delivery_report(task, {**diag, **changed})
            self.assertEqual(rejected['status'], 'unavailable')
            self.assertIsNone(rejected['report_text'])

    def test_price_path_keeps_nearest_obstacle_caution_in_compact_format(self):
        r,s,slot,c=inputs()
        r['report_text']=r['report_text'].replace(
            '残り値幅：保存終値1',
            '残り値幅：保存M15終値 1.00（11/19 10:45 JST）｜手前の節目 0.4 pips｜波の目標 72.3 pips｜手前の節目までの値幅が大局撤回幅以下（参考）')
        out=build_task_report(r,s,slot,c)
        line=next(x for x in out['report_text'].splitlines() if x.startswith('- **価格の流れ**'))
        self.assertIn('保存M15終値 1.00（11/19 10:45 JST） → 最初の節目 0.9（0.4 pips先） → 波の目標 0.8（72.3 pips先）',line)
        self.assertNotIn('手前余地に注意',line)
        self.assertIn('手前の節目が近い',out['sections']['swing'][0]['text'])
        self.assertNotIn('／0.9／経路目標：',line)

    def test_both_top3_survive_missing_supplementary_checks(self):
        r,s,slot,c=inputs()
        r['report_text']=r['report_text'].replace('見通し：調整中', '見通し：調整中\n根拠：H1スパン：価格は青色の上。確定足の変化：遅行と過去足：下→上')
        out=build_task_report(r,s,slot,{})
        for strategy in ('swing','daytrade'):
            self.assertEqual([x['pair'] for x in out['sections'][strategy]],['EURUSD','GBPUSD','NZDUSD'])
        self.assertNotIn('大きな補助資料',out['report_text'])
        self.assertIn('H1 遅行と過去足：下→上',out['report_text'])
        self.assertIn('通貨強弱のみ未確認',out['report_text'])
        self.assertNotIn('掲載保留',out['report_text'])
        self.assertEqual(out['source'],r['source'])

    def test_only_confirmed_same_target_is_excluded_without_reordering(self):
        r,s,slot,c=inputs()
        row={'pair':'EURUSD','strategy':'swing','previous':{'direction':'short'},
             'current':{'direction':'short','reference_levels':{'scenario_target':.8}},
             'previous_condition_followthrough':{'original_target':.8,
               'trigger_close_withdrawal':{'condition':'path_objective_reached'}}}
        c['rows']=[row]
        out=build_task_report(r,s,slot,c)
        self.assertTrue(out['sections']['swing'][0]['excluded_target_reached'])
        self.assertFalse(out['sections']['daytrade'][0]['excluded_target_reached'])
        self.assertEqual(out['sections']['swing'][1]['pair'],'GBPUSD')
        for change in ('target','source','touch_only'):
            changed=deepcopy(c)
            if change=='target':changed['rows'][0]['current']['reference_levels']['scenario_target']=.7
            elif change=='source':changed['source']['run_id']=2
            else:changed['rows'][0]['previous_condition_followthrough']={'original_target':.8,'target_touch':{'high':.8}}
            self.assertFalse(build_task_report(r,s,slot,changed)['sections']['swing'][0]['excluded_target_reached'])

    def test_missing_report_does_not_claim_saved(self):
        r,s,slot,c=inputs();r['source']['evaluated_at']='invalid'
        self.assertEqual(build_task_report(r,s,slot,c)['status'],'unavailable')
        r,s,slot,c=inputs();r['status']='unavailable'
        self.assertEqual(build_task_report(r,s,slot,c)['status'],'unavailable')

    def test_condensed_display_keeps_opposed_h4_and_exact_levels(self):
        r,s,slot,c=inputs()
        r['report_text']=r['report_text'].replace(
            '懸念：勢い未確認',
            '懸念：RCI9は短期逆行。調整進行を確認／H4の背景：買い方向。H1のセットアップと逆方向／W1上位SB背景が予測方向と競合。伸びに注意／MACDが混在')
        original=r['report_text']
        out=build_task_report(r,s,slot,c)
        self.assertIn('EUR/USD｜売り方向の監視候補（B）｜足の確認待ち',out['report_text'])
        self.assertIn('H4が逆方向、W1も逆方向',out['report_text'])
        self.assertIn('局所停止 M15終値2以上／大局撤回 H4終値3以上',out['report_text'])
        self.assertEqual(out['report_text'].count('- **価格の流れ**'), 6)
        self.assertEqual(out['report_text'].count('- **見直す水準**'), 6)
        self.assertNotIn('- **見直す**',out['report_text'])
        self.assertNotIn('調整進行を確認',out['report_text'])
        self.assertEqual(r['report_text'],original)

    def test_observed_reaction_does_not_read_as_trade_permission(self):
        r,s,slot,c=inputs()
        r['report_text']=r['report_text'].replace('条件待ち','局所条件観測済み')
        out=build_task_report(r,s,slot,c)
        self.assertIn('反応あり・再確認',out['report_text'])
        self.assertIn('🔵 EUR/USD',out['report_text'])
        self.assertIn('売買前に現在値と確定足を確認',out['report_text'])
        self.assertNotIn('買い推奨',out['report_text'])

    def test_no_duplicate_preface_keeps_price_caution_and_order(self):
        r,s,slot,c=inputs()
        r['report_text']=r['report_text'].replace(
            '残り値幅：保存終値1',
            '残り値幅：保存M15終値 1.00｜手前の節目 0.4 pips｜波の目標 72.3 pips｜手前の節目までの値幅が大局撤回幅以下（参考）')
        out=build_task_report(r,s,slot,c)
        self.assertNotIn('## まず見る',out['report_text'])
        self.assertEqual(out['report_text'].count('🟡 EUR/USD'),2)
        self.assertIn('手前の節目が近い',out['sections']['swing'][0]['text'])
        self.assertLess(out['report_text'].index('## 通貨強弱'),out['report_text'].index('## 短期スイング TOP3'))
        self.assertEqual(len(out['sections']['swing']),3)

    def test_reached_target_is_shown_as_plan_wait_in_candidate(self):
        r,s,slot,c=inputs()
        c['rows']=[{'pair':'EURUSD','strategy':'swing',
                    'previous':{'direction':'short'},
                    'current':{'direction':'short','reference_levels':{'scenario_target':.8}},
                    'previous_condition_followthrough':{
                        'original_target':.8,
                        'trigger_close_withdrawal':{'condition':'path_objective_reached'}}}]
        out=build_task_report(r,s,slot,c)
        self.assertIn('**⚪ EUR/USD',out['sections']['swing'][0]['text'])
        self.assertIn('🟡 足の確認待ち／🔵 反応あり・再確認／⚪ 新しい価格計画待ち',out['report_text'])

    def test_repeated_macd_caution_is_not_printed_twice(self):
        r,s,slot,c=inputs()
        r['report_text']=r['report_text'].replace('見通し：調整中\n懸念：勢い未確認',
            '見通し：方向側MACDの変化が混在。\n懸念：方向側MACDの変化が混在')
        out=build_task_report(r,s,slot,c)
        self.assertEqual(out['sections']['swing'][0]['text'].count('方向側MACDの変化が混在'),1)
