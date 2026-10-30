"""H4 maturity must precede M15 swing priority; synthetic candles only."""
from copy import deepcopy
import json
import unittest

from fx_system.swing_wave import build_wave, wave_inputs, METHOD
from fx_system.strategy_scenario_assessment import assess_strategy
from fx_system.scenario_conditions import condition_inputs
from fx_system.practical_review import review
from fx_system.strategy_report import report_records
from fx_system.strategy_report_export import build_strategy_report_export, restore_strategy_report_export
from fx_system.validate_strategy_snapshot import validate_strategy_snapshot
from test_swing_horizon import track, with_record
from test_strategy_strength import CLOCK, mature_track
from test_strategy_report_export import SOURCE


def prepared(direction='long', response=True):
    t=track(direction);stamp=t['reference_plan']['reference_close_timestamp']
    bars=[{'timestamp':stamp-(3-i)*14400,'open':98,'high':99,'low':97,'close':98}
          for i in range(3)]
    bars.append({'timestamp':stamp,'open':99,'high':101,'low':98,'close':100})
    if not response:
        bars[2].update(open=100,high=105,low=98,close=103)
    def mirror(b):return {**b,'open':200-b['open'],'close':200-b['close'],
                          'high':200-b['low'],'low':200-b['high']}
    if direction=='short':bars=[mirror(b) for b in bars]
    t['swing_wave_inputs']=wave_inputs({'h4':{'candles':bars}},t,CLOCK)
    t['trigger_status']='watch_pattern'
    m=[{'timestamp':CLOCK-(5-i)*900,'open':98,'high':99,'low':97,'close':98}
       for i in range(4)]
    m.append({'timestamp':CLOCK-900,'open':99,'high':101,'low':98,'close':100})
    if direction=='short':m=[mirror(b) for b in m]
    t['condition_inputs']=condition_inputs({'m15':{'candles':m}},t,CLOCK)
    return t


class SwingWaveTests(unittest.TestCase):
    def test_m15_break_during_h4_pullback_cannot_be_a_or_prioritized(self):
        for direction in ('long','short'):
            t=prepared(direction,False);before=deepcopy(t)
            r=assess_strategy('EURUSD','swing',t,CLOCK)
            self.assertEqual(r['scenario_conditions']['status'],'conditions_observed')
            self.assertEqual(r['grade'],'B')
            self.assertEqual(r['swing_wave']['status'],'pullback_in_progress')
            self.assertEqual(r['practical_review']['status'],'swing_wave_wait')
            self.assertEqual(report_records({'strategy_assessments':[r]}),[])
            self.assertEqual(t,before)

    def test_h4_close_response_then_m15_can_reach_a_for_both_directions(self):
        for direction in ('long','short'):
            r=assess_strategy('EURUSD','swing',prepared(direction),CLOCK)
            self.assertEqual(r['swing_wave']['response'],'close_breakout')
            self.assertEqual(r['grade'],'A')
            self.assertEqual(r['practical_review']['status'],'reaction_confirmed')
            self.assertEqual(report_records({'strategy_assessments':[r]}),[r])

    def test_h4_response_without_m15_confirmation_is_not_a(self):
        t=prepared();t['condition_inputs']={}
        r=assess_strategy('EURUSD','swing',t,CLOCK)
        self.assertEqual(r['swing_wave']['status'],'response_confirmed')
        self.assertEqual(r['grade'],'B')

    def test_h4_rejection_after_pullback_is_a_valid_alternative(self):
        for direction in ('long','short'):
            t=prepared(direction);bars=t['swing_wave_inputs']['bars']
            bullish=[{'open':100,'high':104,'low':97,'close':100},
                     {'open':102,'high':104,'low':98,'close':99},
                     {'open':99,'high':103,'low':98,'close':99},
                     {'open':99,'high':101,'low':97,'close':100}]
            if direction=='short':
                bullish=[{'open':200-b['open'],'close':200-b['close'],
                          'high':200-b['low'],'low':200-b['high']} for b in bullish]
            for bar, values in zip(bars,bullish):bar.update(values)
            r=assess_strategy('EURUSD','swing',t,CLOCK)
            self.assertEqual(r['swing_wave']['response'],'pullback_rejection')

    def test_stale_future_gapped_mismatched_and_unknown_quality_not_confirmed(self):
        base=assess_strategy('EURUSD','swing',prepared(),CLOCK)
        for change in ('stale','future','gap','plan','quality','malformed','ohlc','structure'):
            r=deepcopy(base);i=r['swing_wave_inputs']
            if change=='stale':r['evaluated_at']+=14400;i['evaluated_at']+=14400
            if change=='future':
                for b in i['bars']:b['timestamp']+=14400
            if change=='gap':i['bars'][0]['timestamp']-=14400
            if change=='plan':r['reference_plan']['reference_close']=101
            if change=='quality':i['quality_verified']=False
            if change=='malformed':r['swing_wave_inputs']=[]
            if change=='ohlc':i['bars'][-1]['low']=120
            if change=='structure':r['base_structure']='unconfirmed'
            self.assertEqual(build_wave(r)['status'],'unverified')

    def test_indicators_are_not_a_collective_agreement_rule(self):
        t=prepared();t['indicator_context']={'frames':{'base':{'observations':[
            {'indicator':'dinapoli_macd_preferred_stochastic','status':'provisional_reference',
             'macd_histogram_relation':'opposed','macd':{'histogram':-1},'preferred_stochastic':{}}]}}}
        r=assess_strategy('EURUSD','swing',t,CLOCK)
        self.assertEqual(r['swing_wave']['status'],'response_confirmed')
        self.assertTrue(any('MACD' in x for x in r['opposing_evidence']))
        self.assertEqual(r['grade'],'A')

    def test_new_export_restores_and_tampering_is_rejected(self):
        r=assess_strategy('EURUSD','swing',prepared(response=False),CLOCK);s=with_record(r)
        self.assertEqual(validate_strategy_snapshot(s),[])
        b=build_strategy_report_export(json.dumps(s).encode(),SOURCE)
        v=restore_strategy_report_export(b,SOURCE,b['snapshot_git_blob_sha'])
        self.assertEqual(len(v['scheduled_outlook']['strategy_assessments']),32)
        r['swing_wave']['status']='response_confirmed'
        self.assertIn('scheduled swing wave mismatch',validate_strategy_snapshot(s))

    def test_calendar_review_cannot_restore_a_from_m15_alone(self):
        r=assess_strategy('EURUSD','swing',prepared(response=False),CLOCK)
        r['grade']='A';review(r)
        self.assertEqual(r['grade'],'B')
        self.assertEqual(r['practical_review']['status'],'swing_wave_wait')

    def test_calendar_recheck_keeps_saved_swing_context_consistent(self):
        r=assess_strategy('EURUSD','swing',prepared(response=False),CLOCK)
        r['economic_calendar_context']={'events':[{'id':'synthetic-event','impact':'high',
            'time_precision':'minute','scheduled_at_utc':CLOCK+60}]}
        review(r)
        self.assertEqual(r['practical_review']['status'],'event_recheck')
        self.assertEqual(r['swing_context']['entry_status'],'event_recheck')
        self.assertEqual(validate_strategy_snapshot(with_record(r)),[])

    def test_legacy_v8_and_daytrade_keep_previous_review(self):
        r=assess_strategy('EURUSD','swing',prepared(),CLOCK)
        r['method_version']='contextual_scenario_review_v8_swing_horizon'
        r.pop('swing_wave');r.pop('swing_wave_inputs');r['grade']='A'
        review(r)
        self.assertEqual(r['grade'],'A')
        self.assertNotIn('swing_wave',r)
        d=assess_strategy('EURUSD','daytrade',mature_track(),CLOCK)
        self.assertNotIn('swing_wave',d)


if __name__=='__main__':unittest.main()
