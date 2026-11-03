import json
import math
import unittest
from copy import deepcopy
from fx_system.standard_technicals import macd,frame,PROFILE,METHOD,prepare,assess,refresh
from fx_system.scheduled_outlook import build_scheduled_outlook
from fx_system.strategy_report_export import build_strategy_report_export,restore_strategy_report_export
from fx_system.validate_strategy_snapshot import validate_strategy_snapshot
from test_strategy_strength import CLOCK
from test_strategy_report_export import SOURCE


def inputs(sign=1,count=220):
    from fx_system.core import technical
    frames={}
    for tf,sec in (('h4',14400),('h1',3600),('m15',900),('m5',300),('d1',86400),('w1',604800)):
        last=(CLOCK//sec-1)*sec
        frames[tf]=[{'timestamp':last-(count-1-i)*sec,'open':200+sign*(i*.1+math.sin(i*.6))-.05,
                     'high':200+sign*(i*.1+math.sin(i*.6))+.3,'low':200+sign*(i*.1+math.sin(i*.6))-.3,
                     'close':200+sign*(i*.1+math.sin(i*.6))} for i in range(count)]
    q={'evaluated_at':CLOCK,'timeframes':{tf:{'ok':True} for tf in frames}}
    d={'technical':{tf:technical(rows) for tf,rows in frames.items()},'dinapoli_research':{'obsolete':True},'span_model_inputs':{}}
    prepare(d,frames,frames,q)
    return d,q,frames


class StandardTechnicalTests(unittest.TestCase):
    def test_standard_macd_golden_linear_series_and_full_prefix(self):
        m=macd(list(range(1,81)))
        self.assertIsNone(m[24]['line']);self.assertIsNone(m[32]['signal'])
        for x in m[33:]:
            self.assertAlmostEqual(x['line'],7);self.assertAlmostEqual(x['signal'],7);self.assertAlmostEqual(x['histogram'],0)
        values=[100+math.sin(i*.3)+i*.02 for i in range(250)]
        self.assertNotAlmostEqual(macd(values)[-1]['line'],macd(values[-35:])[-1]['line'],places=8)

    def test_standard_sma_and_macd_can_challenge_sb_without_forcing_a_turn(self):
        from fx_system.standard_technicals import forecast
        d,_,_=inputs();f=deepcopy(d['standard_technical_frames']['h4'])
        f['super_bollinger']['centerline_direction']='down'
        f['macd']['observations']=[{'histogram':x} for x in (.1,.2,.3)]
        f['sma']['50'].update(slope='up',value=f['bars'][-1]['close']-1)
        out=forecast(f,'HH_HL')
        self.assertEqual(out['direction'],'long');self.assertEqual(out['phase'],'reversal_developing')
        self.assertEqual(out['conviction'],'weak')

    def test_exact_profile_and_no_retired_indicators_in_new_data(self):
        d,q,frames=inputs()
        self.assertNotIn('dinapoli_research',d);self.assertNotIn('span_model_inputs',d)
        f=d['standard_technical_frames']['h4']
        self.assertEqual(f['macd']['parameters'],[12,26,9]);self.assertEqual(set(f['sma']),{'50','200'})
        self.assertEqual(set(f['rci']),{'9','26','52'})
        self.assertAlmostEqual(f['sma']['50']['value'],sum(b['close'] for b in frames['h4'][-50:])/50)

    def test_32_new_records_export_restore_and_no_legacy_generation(self):
        for sign in (1,-1):
            d,q,_=inputs(sign)
            o=build_scheduled_outlook({p:deepcopy(d) for p in __import__('fx_system.monitor_pairs',fromlist=['PAIR_KEYS']).PAIR_KEYS},
                {p:q for p in __import__('fx_system.monitor_pairs',fromlist=['PAIR_KEYS']).PAIR_KEYS},evaluated_at=CLOCK)
            self.assertEqual(validate_strategy_snapshot({'evaluated_at':CLOCK,'scheduled_outlook':o}),[])
            self.assertEqual(len(o['strategy_assessments']),32)
            for r in o['strategy_assessments']:
                self.assertEqual(r['method_version'],METHOD);self.assertEqual(r['technical_profile'],PROFILE)
                self.assertNotIn('span_model_version',r);self.assertNotIn('forecast_wave_version',r)
                self.assertNotIn('DMA',json.dumps(r,ensure_ascii=False));self.assertNotIn('stochastic',json.dumps(r))
            b=build_strategy_report_export(json.dumps({'evaluated_at':CLOCK,'scheduled_outlook':o}).encode(),SOURCE)
            self.assertEqual(b['status'],'saved');v=restore_strategy_report_export(b,SOURCE,b['snapshot_git_blob_sha'])
            self.assertEqual(v['scheduled_outlook']['strategy_assessments'],o['strategy_assessments'])
            broken=deepcopy(o['strategy_assessments'][0]);broken['standard_inputs']['base']['macd']['observations'][-1]['histogram']+=1
            with self.assertRaises(ValueError):refresh(broken)

    def test_missing_sma200_is_auxiliary_not_all_pairs_pending(self):
        d,q,_=inputs(count=100)
        o=build_scheduled_outlook({'EURUSD':d},{'EURUSD':q},evaluated_at=CLOCK)
        r=next(r for r in o['strategy_assessments'] if r['pair']=='EURUSD' and r['strategy']=='swing')
        self.assertIsNone(r['standard_inputs']['base']['sma']['200']['value'])
        self.assertEqual(r['technical_outlook']['forecast']['status'],'available')

    def test_invalid_quality_does_not_become_market_skip(self):
        d,q,_=inputs();q['timeframes']['h4']['ok']=False
        o=build_scheduled_outlook({'EURUSD':d},{'EURUSD':q},evaluated_at=CLOCK)
        r=next(r for r in o['strategy_assessments'] if r['pair']=='EURUSD' and r['strategy']=='swing')
        self.assertEqual(r['assessment'],'evaluation_pending')


if __name__=='__main__':unittest.main()
