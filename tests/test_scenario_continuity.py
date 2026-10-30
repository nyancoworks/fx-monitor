from copy import deepcopy
import json
import unittest
from fx_system.scenario_continuity import compare_views, build_continuity, render
from fx_system.strategy_report_export import build_strategy_report_export
from test_strategy_report_export import snapshot, SOURCE


def view():
    r={'pair':'EURUSD','strategy':'swing','assessment':'review','direction':'long',
       'grade':'B','waiting_conditions':['synthetic wait'],'formation_conditions':[],
       'scenario_conditions':{'status':'waiting','observed_at':100},
       'reference_levels':{'target':105},'invalidation':{'price':95},
       'expiry':{'status':'not_defined'},'reasons':['synthetic structure'],
       'opposing_evidence':[]}
    return {'scheduled_outlook':{'strategy_assessments':[r], 'strategy_candidates':[]}}


class ContinuityTests(unittest.TestCase):
    def test_forecast_summary_retains_decisions_without_duplicate_observations(self):
        from fx_system.scenario_continuity import _brief
        record={'technical_outlook':{'evolution':{'momentum':'directional_building'},
            'forecast':{'direction':'long','phase':'continuation','primary_path':'synthetic path',
                'alternative_path':'synthetic alternative','support':['support'], 'cautions':['caution'],
                'background':{'large':'x'*100000},'timing':{'observations':'x'*100000},
                'evolution':{'momentum':'directional_building'}}},
            'wave_price_plan':{'thesis_invalidation':100,'first_obstacle':{'price':120}}}
        before=deepcopy(record);brief=_brief(record);f=brief['technical_outlook']['forecast']
        self.assertEqual(record,before)
        for key in ('background','timing','evolution'):self.assertNotIn(key,f)
        for key in ('direction','phase','primary_path','alternative_path','support','cautions'):
            self.assertEqual(f[key],record['technical_outlook']['forecast'][key])
        self.assertEqual(brief['technical_outlook']['evolution'],record['technical_outlook']['evolution'])
        self.assertEqual(brief['wave_price_plan'],record['wave_price_plan'])

    def test_clock_alone_does_not_change_scenario_and_inputs_are_immutable(self):
        old=view();new=deepcopy(old);new['scheduled_outlook']['strategy_assessments'][0]['scenario_conditions']['observed_at']=200
        before=deepcopy((old,new));row=compare_views(new,old)[0]
        self.assertEqual(row['status'],'same_direction');self.assertEqual(row['changed_fields'],[])
        self.assertEqual((old,new),before)

    def test_levels_direction_pending_and_candidate_exit_are_distinct(self):
        old=view()
        for fields,status,changes in [({'reference_levels':{'target':110}},'same_direction',['reference_levels']),
                                     ({'direction':'short'},'direction_changed',['direction']),
                                     ({'assessment':'evaluation_pending'},'evaluation_pending',[]),
                                     ({'assessment':'skip','skip_reason':'synthetic opposition'},'no_longer_reviewed',[])]:
            new=deepcopy(old);new['scheduled_outlook']['strategy_assessments'][0].update(fields)
            row=compare_views(new,old)[0];self.assertEqual(row['status'],status)
            for field in changes:self.assertIn(field,row['changed_fields'])
            if status=='no_longer_reviewed':
                self.assertIn('synthetic opposition',render([row],100,200))
                self.assertNotIn('今回保存は撤回状態',render([row],100,200))

    def test_listing_exit_is_not_withdrawal(self):
        old=view();new=deepcopy(old)
        prior=old['scheduled_outlook']['strategy_assessments'][0]
        # Keep same record but put three superior same-strategy records ahead.
        from unittest.mock import patch
        with patch('fx_system.scenario_continuity.report_records',side_effect=[[],[prior]]):
            row=compare_views(new,old)[0]
        self.assertEqual(row['status'],'same_direction')
        self.assertIn('掲載から外れた（撤回とは別）',render([row],100,200))

    def test_full_verified_exports_and_missing_tampered_future_prior(self):
        current=build_strategy_report_export(json.dumps(snapshot()).encode(),SOURCE)
        from unittest.mock import patch
        with patch('test_strategy_report_export.CLOCK',SOURCE['evaluated_at']-300), patch('synthetic_candles.CLOCK',SOURCE['evaluated_at']-300):
            older=snapshot()
        source={**SOURCE,'run_id':122,'evaluated_at':SOURCE['evaluated_at']-300}
        prior=build_strategy_report_export(json.dumps(older).encode(),source)
        result=build_continuity(current,SOURCE,current['snapshot_git_blob_sha'],prior,source,prior['snapshot_git_blob_sha'])
        self.assertEqual(result['status'],'saved');self.assertEqual(len(result['rows']),32)
        inputs=deepcopy((current,prior))
        checked=build_continuity(current,SOURCE,current['snapshot_git_blob_sha'],prior,source,prior['snapshot_git_blob_sha'],
                                 current_snapshot_bytes=json.dumps(snapshot()).encode())
        self.assertEqual(checked['followthrough_status'],'same_snapshot_saved_candles_checked')
        self.assertEqual(len(checked['rows']),32)
        self.assertTrue(all('previous_condition_followthrough' in r for r in checked['rows']))
        unbound=build_continuity(current,SOURCE,current['snapshot_git_blob_sha'],prior,source,prior['snapshot_git_blob_sha'],
                                current_snapshot_bytes=b'{}')
        self.assertEqual(unbound['status'],'saved')
        self.assertEqual(unbound['followthrough_status'],'snapshot_identity_unverified')
        self.assertEqual(unbound['rows'],result['rows'])
        self.assertEqual((current,prior),inputs)
        bad=deepcopy(prior);bad['payload_sha256']='0'*64
        for bundle,src,blob in [(None,None,None),(bad,source,prior['snapshot_git_blob_sha']),
                                (current,SOURCE,current['snapshot_git_blob_sha'])]:
            self.assertEqual(build_continuity(current,SOURCE,current['snapshot_git_blob_sha'],bundle,src,blob)['status'],'unavailable')

    def test_adjacent_comparison_is_saved_in_same_local_git_push(self):
        import tempfile
        import subprocess
        from pathlib import Path
        from unittest.mock import patch
        from fx_system.private_runtime import save_snapshot
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'state';root.mkdir();remote=Path(folder)/'remote.git'
            subprocess.run(['git','init','--bare',str(remote)],check=True,capture_output=True)
            def git(*args):
                return subprocess.run(['git','-C',str(root),*args],check=True,capture_output=True,text=True).stdout.strip()
            git('init','-b','main');git('remote','add','origin',str(remote))
            (root/'data').mkdir();(root/'data/latest.json').write_text('{"generated_at":1}')
            (root/'data/cache.json').write_text('{}')
            git('add','.');git('-c','user.name=test','-c','user.email=test@localhost','commit','-m','initial')
            git('push','origin','HEAD:main')
            for i in range(2):
                with patch('test_strategy_report_export.CLOCK',SOURCE['evaluated_at']+300*i), patch('synthetic_candles.CLOCK',SOURCE['evaluated_at']+300*i):
                    data=snapshot()
                data['generated_at']=2+i
                (root/'data/latest.json').write_text(json.dumps(data))
                save_snapshot(root,str(123+i),'a'*40)
                result=json.loads(git('show','HEAD:data/scenario-continuity.json'))
                self.assertEqual(result['status'],'unavailable' if i==0 else 'saved')
                if i==1:
                    self.assertEqual(len(result['rows']),32)
                    self.assertEqual(result['followthrough_status'],'same_snapshot_saved_candles_checked')
                    self.assertTrue(all('previous_condition_followthrough' in r for r in result['rows']))
                    self.assertEqual(result['previous_data_commit'],git('rev-parse','HEAD^'))
                self.assertEqual(git('rev-parse','HEAD'),git('ls-remote','origin','refs/heads/main').split()[0])
                self.assertEqual((root/'data/scenario-continuity.json').stat().st_mode&0o777,0o600)
