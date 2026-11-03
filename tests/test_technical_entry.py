"""Synthetic RCI timing and optional candle observations, without PA gates."""
import unittest
from copy import deepcopy
from fx_system.technical_entry import describe, candle_reference, turn_observed
from fx_system.standard_technicals import refresh
from fx_system.scheduled_outlook import build_scheduled_outlook
from fx_system.scenario_conditions import validate_conditions
from fx_system.scenario_followthrough import observe_frozen_condition
from test_standard_technicals import inputs, CLOCK


def record():
    d,q,_=inputs()
    o=build_scheduled_outlook({'EURUSD':d},{'EURUSD':q},evaluated_at=CLOCK)
    return next(r for r in o['strategy_assessments'] if r['pair']=='EURUSD' and r['strategy']=='daytrade')


class TechnicalEntryTests(unittest.TestCase):
    def test_rci_extreme_and_turn_both_required_but_not_a_candle(self):
        for v,p,d,expected in [(-79,-90,'long',True),(-85,-90,'long',True),
                (-90,-85,'long',False),(-70,-75,'long',False),(-80,-80,'long',False),
                (79,90,'short',True),(85,90,'short',True),(90,85,'short',False),
                (None,-90,'long',None),(float('nan'),90,'short',None),(101,90,'short',None)]:
            self.assertIs(turn_observed(v,p,d),expected)
        r=record();t=r['standard_inputs']['trigger'];t['rci']['9'].update(value=-79,previous=-90)
        # No lower wick, neutral body: RCI timing still observed.
        b=t['bars'][-1];b.update(open=b['close'],low=b['close'],high=b['close']+.2)
        c=describe(r);self.assertEqual(c['status'],'conditions_observed');self.assertIsNone(c['level'])
        self.assertIsNone(c['formation_price']);self.assertEqual(candle_reference(r)['status'],'not_observed')
        b['low']=b['close']-2
        self.assertEqual(candle_reference(r)['status'],'observed');self.assertEqual(describe(r),c)
        self.assertFalse(candle_reference(r)['required_for_timing'])
        t['verified']=False
        self.assertEqual(describe(r)['status'],'unavailable')
        self.assertEqual(candle_reference(r)['status'],'not_applicable')

    def test_new_conditions_validate_without_pa_and_old_record_is_frozen(self):
        r=record()
        self.assertEqual(validate_conditions(r),[])
        self.assertNotIn('obstacle_path_review',r)
        self.assertEqual(r['scenario_conditions']['route'],'technical_rci_recovery')
        bad=deepcopy(r);bad['scenario_conditions']['status']='conditions_observed'
        if bad!=r:self.assertTrue(validate_conditions(bad))
        old=deepcopy(r);old.pop('technical_entry_version');old.pop('candle_reference');old.pop('price_path_context')
        old['standard_technical_version']=1;refresh(old)
        self.assertIn('obstacle_path_review',old);self.assertEqual(old['scenario_conditions']['basis'],'contextual_saved_price_action_v1')
        self.assertEqual(refresh(deepcopy(old)),old)

    def test_frozen_rci_recovery_uses_complete_retained_history(self):
        r=record();tf=r['trigger_timeframe'];sec=300
        # Retained ten declining closes: RCI starts at -100, next close reverses.
        r['evaluated_at']=CLOCK+2
        f=r['standard_inputs']['trigger'];f['evaluated_at']=CLOCK+2;last=f['bars'][-1]['timestamp']
        values=[101-i*.1 for i in range(10)]
        f['bars']=[{'timestamp':last-(9-i)*sec,'open':v,'high':v+.1,'low':v-.1,'close':v} for i,v in enumerate(values)]
        f['rci']['9'].update(value=-100,previous=-100)
        r['reference_levels'].update(invalidation=90,scenario_target=110)
        r['wave_price_plan']['local_setup_failure']=91
        r['scenario_conditions']=describe(r)
        self.assertEqual(r['scenario_conditions']['status'],'waiting')
        # Include complete bridge candle spanning publication. It may supply
        # indicator history, but cannot itself confirm a post-publication turn.
        start=(CLOCK//sec)*sec
        bars=[{'timestamp':start+i*sec,'open':100.1,'high':101,'low':100,'close':100.1 if i==0 else 100.8} for i in range(2)]
        pair={'decision_data':{'raw':{'m5':bars},'provenance':{f'm5:{b["timestamp"]}':'Twelve Data' for b in bars}}}
        through=start+600
        out=observe_frozen_condition(r,pair,through)
        self.assertEqual(out['status'],'frozen_condition_observed')
        self.assertIsNone(out['original_level']);self.assertEqual(out['condition_observation']['closed_at'],through)
        incomplete=deepcopy(r);incomplete['standard_inputs']['trigger']['bars']=f['bars'][-1:]
        out=observe_frozen_condition(incomplete,pair,through)
        self.assertEqual(out['status'],'saved_condition_unverified')
        self.assertGreater(out['rci9_unverified_candles'],0)

if __name__=='__main__':unittest.main()
