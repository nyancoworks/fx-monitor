"""Synthetic indicator application; no market requests or private prices."""
from copy import deepcopy
import json
import unittest
from fx_system.dinapoli_research import dma_snapshot
from fx_system.dinapoli_indicator_reference import indicator_reference
from fx_system.indicator_research import super_bollinger_context, research_snapshot
from fx_system.strategy_indicator_context import strategy_indicator_context
from fx_system.technical_context import build_technical_context
from fx_system.strategy_scenario_assessment import assess_strategy
from test_strategy_strength import mature_track, CLOCK


def candles(tf, direction=1, clock=CLOCK):
    seconds={'m5':300,'m15':900,'h1':3600,'h4':14400,'d1':86400,'w1':604800}[tf]
    end=clock//seconds*seconds
    return [{'timestamp':end-(40-i)*seconds,'open':100+direction*i/10,
             'high':101+direction*i/10,'low':99+direction*i/10,'close':100+direction*i/10}
            for i in range(40)]


def data(clock=CLOCK):
    result={'indicator_context_version':2,'super_bollinger_context':{},'indicator_research':{},
            'dinapoli_research':{},'dinapoli_indicator_reference':{}}
    for tf in ('h1','h4','m5','m15'):
        rows=candles(tf,clock=clock)
        result['super_bollinger_context'][tf]=super_bollinger_context(rows)
        result['indicator_research'][tf]=research_snapshot(rows)
        result['dinapoli_research'][tf]=dma_snapshot(rows)
        result['dinapoli_indicator_reference'][tf]=indicator_reference(rows)
    result['h4_setup_shadow']={'dinapoli':result['dinapoli_research']['h4']}
    return result


def track(direction='long', swing=False):
    return {'base_timeframe':'h4' if swing else 'h1','trigger_timeframe':'m15' if swing else 'm5',
            'base_verified':True,'trigger_verified':True,'direction':direction}


class TechnicalContextTests(unittest.TestCase):
    def test_current_plot_uses_historical_sma_not_latest_future_display_value(self):
        rows=candles('m5');d=dma_snapshot(rows)['dma']['3x3']
        self.assertAlmostEqual(d['current_plot'],sum(b['close'] for b in rows[-6:-3])/3)
        self.assertAlmostEqual(d['previous_plot'],sum(b['close'] for b in rows[-7:-4])/3)
        self.assertNotEqual(d['current_plot'],d['latest_known'])
        self.assertEqual(d['source_timestamp'],rows[-4]['timestamp'])
        changed=deepcopy(rows)
        for b in changed[-3:]:b['close']+=100
        self.assertEqual(dma_snapshot(changed)['dma']['3x3']['current_plot'],d['current_plot'])

    def test_warmup_does_not_substitute_latest_known_for_current_plot(self):
        d=dma_snapshot(candles('m5')[-25:])['dma']['25x5']
        self.assertIsNotNone(d['latest_known']);self.assertIsNone(d['current_plot'])

    def test_future_or_wrong_shift_source_is_not_a_current_dma_reference(self):
        source=data()
        source['dinapoli_research']['m5']['dma']['3x3']['source_timestamp']=CLOCK+300
        c=strategy_indicator_context(source,track(),evaluated_at=CLOCK)
        n=next(n for n in c['frames']['trigger']['observations'] if n['indicator']=='standard_fibonacci_and_dma')
        self.assertEqual(n['application']['positions']['3x3']['status'],'unverified')

    def test_all_dma_specs_position_and_slope_are_direction_relative(self):
        source=data();before=deepcopy(source)
        for direction,relation in [('long','aligned'),('short','opposed')]:
            c=strategy_indicator_context(source,track(direction),evaluated_at=CLOCK)
            for frame in c['frames'].values():
                n=next(n for n in frame['observations'] if n['indicator']=='standard_fibonacci_and_dma')
                self.assertEqual(set(n['application']['positions']),{'3x3','7x5','25x5'})
                for p in n['application']['positions'].values():
                    self.assertEqual((p['price_relation'],p['slope_relation']),(relation,relation))
        self.assertEqual(source,before)

    def test_short_and_swing_have_own_timeframes_and_no_h1_dma_leak(self):
        c=strategy_indicator_context(data(),track('short',True),evaluated_at=CLOCK)
        r={'evaluated_at':CLOCK,'direction':'short','reference_timeframe':'h4','trigger_timeframe':'m15','indicator_context':c}
        t=build_technical_context(r)
        self.assertEqual((t['frames']['base']['timeframe'],t['frames']['trigger']['timeframe']),('h4','m15'))
        self.assertEqual(t['frames']['trigger']['interpretation'],'counterpressure')
        self.assertTrue(any('DMA' in x for x in t['cautions']))
        self.assertIsNotNone(t['waiting_note']);self.assertFalse(t['changes_price_conditions'])

    def test_band_lagging_and_width_are_separate_from_centerline(self):
        source=data();sb=source['super_bollinger_context']['h1'];sb['lagging_span']['location']='below'
        source['indicator_research']['h1']['band_research']['bandwidth_change']=-1
        c=strategy_indicator_context(source,track(),evaluated_at=CLOCK)
        r={'evaluated_at':CLOCK,'direction':'long','indicator_context':c}
        t=build_technical_context(r)
        self.assertEqual(t['frames']['base']['sb_centerline'],'aligned')
        self.assertEqual(t['frames']['base']['sb_lagging'],'opposed')
        self.assertEqual(t['frames']['base']['bandwidth_state'],'contracting')
        self.assertTrue(any('遅行' in x for x in t['cautions']))
        self.assertTrue(any('縮小' in x for x in t['cautions']))

    def test_stale_or_unverified_frame_does_not_claim_indicator_support(self):
        source=data(clock=CLOCK-14400)
        c=strategy_indicator_context(source,track(),evaluated_at=CLOCK)
        for frame in c['frames'].values():
            for note in frame['observations']:
                if note['indicator']=='super_bollinger':self.assertEqual(note['centerline_relation'],'unconfirmed')
                if note['indicator']=='standard_fibonacci_and_dma':
                    self.assertTrue(all(p['status']=='unverified' for p in note['application']['positions'].values()))
                if note['indicator']=='dinapoli_macd_preferred_stochastic':self.assertEqual(note['status'],'unverified')
        t=track();t['trigger_verified']=False
        c=strategy_indicator_context(data(),t,evaluated_at=CLOCK)
        self.assertEqual(c['frames']['trigger']['observations'],[])

    def test_existing_a_and_price_conditions_are_not_replaced_by_indicator_votes(self):
        t=mature_track();legacy=assess_strategy('EURUSD','daytrade',deepcopy(t),CLOCK)
        # Synthetic structure long while all indicator prices slope down.
        source=data()
        for tf in ('h1','m5'):
            rows=candles(tf,-1)
            source['dinapoli_research'][tf]=dma_snapshot(rows)
            source['dinapoli_indicator_reference'][tf]=indicator_reference(rows)
        t['indicator_context']=strategy_indicator_context(source,track(),evaluated_at=CLOCK)
        current=assess_strategy('EURUSD','daytrade',t,CLOCK)
        self.assertEqual(current['scenario_conditions'],legacy['scenario_conditions'])
        self.assertEqual((current['direction'],current['grade']),(legacy['direction'],legacy['grade']))
        self.assertIn('technical_context',current)
        self.assertTrue(any('DMA' in s for s in current['opposing_evidence']))
        self.assertTrue(any('DMA' in s for s in current['waiting_conditions']))

    def test_unversioned_context_does_not_reinterpret_frozen_legacy_records(self):
        source=data();source.pop('indicator_context_version')
        c=strategy_indicator_context(source,track())
        self.assertNotIn('schema',c)
        self.assertIsNone(build_technical_context({'indicator_context':c,'evaluated_at':CLOCK}))

    def test_full32_calendar_enrichment_export_restore_and_tampering(self):
        from test_strategy_report_export import snapshot,SOURCE
        from fx_system.economic_calendar_context import enrich_outlook
        from fx_system.strategy_report_export import build_strategy_report_export,restore_strategy_report_export
        from fx_system.validate_strategy_snapshot import validate_strategy_snapshot
        s=snapshot();clock=s['evaluated_at'];source=data(clock=clock)
        for r in s['scheduled_outlook']['strategy_assessments']:
            t=track(r['direction'],r['strategy']=='swing')
            r['indicator_context']=strategy_indicator_context(source,t,evaluated_at=clock)
            r['technical_context']=build_technical_context(r)
        for row in s['scheduled_outlook']['rows']:
            row['strategy_assessments']={r['strategy']:deepcopy(r) for r in s['scheduled_outlook']['strategy_assessments'] if r['pair']==row['pair']}
        s['scheduled_outlook']=enrich_outlook(s['scheduled_outlook'],{'observed_at_utc':clock,'complete':False,'events':[]})
        self.assertEqual(validate_strategy_snapshot(s),[])
        e=build_strategy_report_export(json.dumps(s).encode(),SOURCE);self.assertEqual(e['status'],'saved')
        self.assertEqual(e['payload_layout'],'canonical_rows_v2')
        self.assertEqual(len(restore_strategy_report_export(e,SOURCE,e['snapshot_git_blob_sha'])['scheduled_outlook']['strategy_assessments']),32)
        self.assertEqual(restore_strategy_report_export(e,SOURCE,e['snapshot_git_blob_sha'])['scheduled_outlook']['rows'],
                         [{'pair':r['pair'],'strategy_assessments':r['strategy_assessments']} for r in s['scheduled_outlook']['rows']])
        with self.assertRaises(ValueError):restore_strategy_report_export({**e,'payload_layout':'unknown'},SOURCE,e['snapshot_git_blob_sha'])
        s['scheduled_outlook']['strategy_assessments'][0]['technical_context']['summary']='invented'
        self.assertIn('scheduled technical context mismatch',validate_strategy_snapshot(s))

    def test_production_dma_diagnostics_includes_m15(self):
        from fx_system.indicator_refresh import refresh_strategy_indicators
        frames={tf:candles(tf) for tf in ('w1','d1','h4','h1','m15','m5')}
        result={}
        refresh_strategy_indicators(result,frames,frames,{'timeframes':{tf:{} for tf in frames}}, {'direction':'long'})
        self.assertTrue(result['dinapoli_research']['m15']['dma'])
        self.assertEqual(result['super_bollinger_context']['m15']['status'],'calculated')
        self.assertEqual(result['super_bollinger_context']['m5']['status'],'calculated')
        self.assertEqual(result['indicator_context_version'],2)


if __name__=='__main__':unittest.main()
