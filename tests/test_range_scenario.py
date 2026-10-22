"""Synthetic range behavior and canonical history integration, without network."""
from copy import deepcopy
import unittest
from fx_system.range_scenario import apply_range, validate_range
from fx_system.scenario_conditions import condition_inputs, validate_conditions
from fx_system.strategy_explanation import explain_strategy_track
from fx_system.strategy_scenario_assessment import assess_strategy

CLOCK = 1800000000


def sample(base='h1', short=False):
    seconds = {'h1': 3600, 'h4': 14400}[base]
    tf = 'm5' if base == 'h1' else 'm15'; trigger = 300 if tf == 'm5' else 900
    bars = [{'timestamp': CLOCK-(20-i)*seconds, 'open': 100, 'high': 104, 'low': 96, 'close': 100}
            for i in range(20)]
    for index, values in ((2, (105,111,99,105)), (10, (105,110,99,105)),
                          (6, (95,101,90,95)), (14, (95,101,91,95))):
        bars[index].update(zip(('open','high','low','close'), values))
    triggers = [{'timestamp': CLOCK-(5-i)*trigger, 'open': 100, 'high': 102, 'low': 98, 'close': 100}
                for i in range(5)]
    triggers[-1].update(open=106,high=109,low=102,close=104) if short else triggers[-1].update(open=94,high=98,low=92,close=96)
    track = {'base_timeframe': base, 'trigger_timeframe': tf, 'base_verified': True,
             'trigger_verified': True, 'direction': None, 'base_structure': 'mixed', 'state': 'waiting_structure'}
    return {base: {'candles': bars}, tf: {'candles': triggers}}, track


def assessed(data, track):
    apply_range(data, track, CLOCK)
    track['scenario_explanation'] = explain_strategy_track(track)
    track['condition_inputs'] = condition_inputs(data, track, CLOCK)
    return assess_strategy('EURUSD', 'daytrade' if track['base_timeframe']=='h1' else 'swing', track, CLOCK)


class RangeTests(unittest.TestCase):
    def test_edges_both_directions_and_timeframes(self):
        for base in ('h1','h4'):
            for short in (False, True):
                data,t = sample(base,short); before = deepcopy(data); r = assessed(data,t)
                self.assertEqual((r['direction'],r['assessment'],r['grade']), ('short' if short else 'long','review','B'))
                self.assertEqual(r['scenario_conditions']['route'], 'range_edge_rejection')
                self.assertEqual(r['scenario_conditions']['status'], 'conditions_observed')
                self.assertEqual(validate_conditions(r)+validate_range(r), [])
                self.assertIsNone(r['scenario_conditions']['formation_price'])
                self.assertEqual(r['execution_authority'], 'none'); self.assertEqual(data,before)

    def test_touch_without_directional_close_waits(self):
        data,t = sample(); data['m5']['candles'][-1].update(open=97,close=96)
        r = assessed(data,t)
        self.assertEqual(r['scenario_conditions']['status'], 'waiting')
        self.assertEqual(validate_conditions(r), [])

    def test_center_and_both_edges_do_not_invent_direction(self):
        for wide in (False, True):
            data,t = sample(); data['m5']['candles'][-1].update(open=100,close=100,low=92 if wide else 98,high=109 if wide else 102)
            r=assessed(data,t)
            self.assertIsNone(r['direction']); self.assertEqual(r['assessment'],'skip')
            self.assertEqual(r['range_context']['status'],'bounded')

    def test_closed_break_then_return_withdraws_but_wick_does_not(self):
        data,t=sample(); data['m5']['candles'][-2].update(high=113,close=112)
        r=assessed(data,t)
        self.assertEqual(r['range_context']['status'],'broken'); self.assertEqual(r['assessment'],'skip')
        data,t=sample(); data['m5']['candles'][-1]['low']=88
        self.assertEqual(assessed(data,t)['scenario_conditions']['status'],'conditions_observed')

    def test_mixed_structure_alone_not_a_range(self):
        data,t=sample(); data['h1']['candles'][10].update(open=112,close=112,high=115)
        r=assessed(data,t)
        self.assertNotIn('scenario_type',r); self.assertEqual(r['range_context']['status'],'unavailable')

    def test_directional_track_unchanged(self):
        data,t=sample(); t['direction']='long'; original=deepcopy(t)
        apply_range(data,t,CLOCK); self.assertEqual(t,original)

    def test_unverified_stale_future_and_gap_not_current_candidates(self):
        for kind in ('base','trigger','stale','future','gap'):
            data,t=sample()
            if kind in ('base','trigger'): t[kind+'_verified']=False
            elif kind in ('stale','future'):
                for b in data['m5']['candles']: b['timestamp']+=300 if kind=='future' else -300
            else: data['h1']['candles'][-5]['timestamp']-=3600
            r=assessed(data,t)
            self.assertNotIn('scenario_type',r,kind)

    def test_range_evidence_tampering_and_legacy(self):
        data,t=sample(); r=assessed(data,t)
        for path,value in (('lower_outer',89),('formed_at',CLOCK+3600),('direction','short'),('reaction_level',94)):
            changed=deepcopy(r); changed['range_context'][path]=value
            self.assertTrue(validate_range(changed),path)
        changed=deepcopy(r); changed['grade']='A'; self.assertTrue(validate_range(changed))
        self.assertEqual(validate_range({}),[])

    def test_canonical_32_report_and_history(self):
        from fx_system.scheduled_outlook import build_scheduled_outlook
        from fx_system.validate_strategy_snapshot import validate_strategy_snapshot
        from fx_system.strategy_report import render_strategy_report
        from diagnostics.monitoring_result_history import pack_generation, restore_generation
        data,t=sample(); r=assessed(data,t)
        outlook=build_scheduled_outlook({}, {}, evaluated_at=CLOCK)
        outlook['strategy_assessments']=[r if a['pair']=='EURUSD' and a['strategy']=='daytrade' else a for a in outlook['strategy_assessments']]
        next(a for a in outlook['rows'] if a['pair']=='EURUSD')['strategy_assessments']['daytrade']=r
        outlook['assessment_counts']={'review':1,'skip':0,'evaluation_pending':31}
        snap={'evaluated_at':CLOCK,'scheduled_outlook':outlook}
        self.assertEqual(validate_strategy_snapshot(snap),[])
        self.assertIn('レンジ候補（暫定）',render_strategy_report(snap))
        self.assertEqual(restore_generation(pack_generation(outlook['rows'],evaluated_at=CLOCK))['rows'],outlook['rows'])

    def test_real_outlook_pipeline_selects_one_range_slot(self):
        from fx_system.scheduled_outlook import build_scheduled_outlook
        from fx_system.validate_strategy_snapshot import validate_strategy_snapshot
        data,t=sample()
        q={'timeframes':{'h1':{'ok':True,'count':20},'m5':{'ok':True,'count':5,'age_minutes':0}}}
        data['decision_quality']={**deepcopy(q),'evaluated_at':CLOCK}
        data['technical']={'h1':{'status':'ok','structure':'mixed'}}
        o=build_scheduled_outlook({'EURUSD':data},{'EURUSD':q},evaluated_at=CLOCK)
        r=next(a for a in o['strategy_assessments'] if a['pair']=='EURUSD' and a['strategy']=='daytrade')
        self.assertEqual(r.get('scenario_type'),'range_reversal')
        self.assertEqual(r['scenario_conditions']['status'],'conditions_observed')
        self.assertEqual(len(o['strategy_assessments']),32)
        self.assertIn(('EURUSD','daytrade'),[(a['pair'],a['strategy']) for a in o['strategy_candidates']])
        self.assertEqual(validate_strategy_snapshot({'evaluated_at':CLOCK,'scheduled_outlook':o}),[])


if __name__=='__main__': unittest.main()
