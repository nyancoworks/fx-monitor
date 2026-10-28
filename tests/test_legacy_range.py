"""Frozen synthetic legacy compatibility; no range generation."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from fx_system.legacy_range import validate_range
from fx_system.scenario_conditions import validate_conditions


class LegacyRangeTests(unittest.TestCase):
    def test_frozen_long_short_both_timeframes_remain_readable(self):
        rows=json.loads((Path(__file__).parent/'fixtures/legacy_ranges.json').read_text())
        for r in rows:
            self.assertEqual(validate_range(r)+validate_conditions(r),[])
            bad=deepcopy(r);bad['range_context']['lower_outer']-=1
            self.assertTrue(validate_range(bad))

    def test_directionless_production_stays_waiting_without_range_generation(self):
        from synthetic_candles import sample,CLOCK
        from fx_system.scheduled_outlook import build_scheduled_outlook
        from fx_system.validate_strategy_snapshot import validate_strategy_snapshot
        data,_=sample();q={'timeframes':{'h1':{'ok':True,'count':20},'m5':{'ok':True,'count':5,'age_minutes':0}}}
        data['decision_quality']={**deepcopy(q),'evaluated_at':CLOCK}
        data['technical']={'h1':{'status':'ok','structure':'mixed'}}
        o=build_scheduled_outlook({'EURUSD':data},{'EURUSD':q},evaluated_at=CLOCK)
        self.assertEqual(len(o['strategy_assessments']),32)
        self.assertTrue(all(r.get('scenario_type')!='range_reversal' for r in o['strategy_assessments']))
        r=next(r for r in o['strategy_assessments'] if r['pair']=='EURUSD' and r['strategy']=='daytrade')
        self.assertIsNone(r['direction']);self.assertEqual(r['assessment'],'skip')
        self.assertEqual(validate_strategy_snapshot({'evaluated_at':CLOCK,'scheduled_outlook':o}),[])
