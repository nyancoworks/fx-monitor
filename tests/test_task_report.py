import unittest
from copy import deepcopy
from fx_system.task_report import build_task_report


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
