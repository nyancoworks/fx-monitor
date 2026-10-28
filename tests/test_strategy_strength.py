"""Synthetic graph, past-only windows and contextual assessment effects."""
from copy import deepcopy
import math
import unittest
from unittest.mock import patch

from fx_system.core import expected_closed_timestamp
from fx_system.monitor_pairs import PAIR_KEYS
from fx_system.strategy_strength import build_contexts, interpret
from fx_system.strategy_scenario_assessment import assess_strategy

CLOCK = 1800000000
END = expected_closed_timestamp('h1', CLOCK)


def fixture(missing=(), hours=60):
    rates = {'USD': .0002, 'EUR': .0005, 'GBP': .0003, 'JPY': -.0002,
             'AUD': .0001, 'NZD': .00015, 'CAD': -.0001, 'CHF': .00025}
    pairs = {}
    for pair in PAIR_KEYS:
        if pair in missing: continue
        rate = rates[pair[:3]]-rates[pair[3:]]
        rows = []
        for i in range(hours):
            close = 100*math.exp(rate*i)
            rows.append({'timestamp': END-(hours-1-i)*3600,
                         'open': close, 'high': close+1, 'low': close-1, 'close': close})
        pairs[pair] = {'decision_data': {'raw': {'h1': rows}, 'provenance': {
            'h1:'+str(b['timestamp']): 'Twelve Data' for b in rows}}}
    return pairs


def mature_track(context=None):
    return {'base_timeframe': 'h1', 'trigger_timeframe': 'm5', 'base_verified': True,
        'trigger_verified': True, 'direction': 'long', 'base_structure': 'HH_HL',
        'reference_levels': {'invalidation': 90, 'structural_target': 130, 'reference_rr': 3},
        'reference_plan': {'reference_close': 100}, 'saved_reference_close': 100,
        'trigger_price_reference': {'status': 'observed_reference', 'close': 100,
            'timeframe': 'm5', 'evaluated_at': CLOCK, 'closed_at': CLOCK},
        'reaction_timestamp': CLOCK-300, 'price_action': {'status': 'watch_pattern'},
        'currency_strength_context': context,
        'condition_inputs': __import__('fx_system.scenario_conditions',fromlist=['condition_inputs']).condition_inputs(
            {'m5':{'candles':[{'timestamp':CLOCK-(5-i)*300,'open':100,'high':104 if i==4 else 102,'low':99,'close':103 if i==4 else 101} for i in range(5)]}},
            {'trigger_timeframe':'m5','base_timeframe':'h1','base_verified':True,'trigger_verified':True,'direction':'long'},CLOCK)}


class StrategyStrengthTests(unittest.TestCase):
    def test_exact_synthetic_relative_returns_and_separate_horizons(self):
        contexts = build_contexts(fixture(), CLOCK)
        swing = contexts['EURUSD']['swing']; day = contexts['EURUSD']['daytrade']
        self.assertEqual((swing['lookback_h1_bars'], day['lookback_h1_bars']), (24,6))
        self.assertAlmostEqual(swing['difference'], .72, places=9)
        self.assertAlmostEqual(day['difference'], .18, places=9)
        self.assertEqual(day['comparison']['contributing_pairs'], swing['comparison']['contributing_pairs'])
        self.assertAlmostEqual(day['comparison']['change'], 0, places=9)

    def test_own_pair_price_changes_cannot_be_used_as_corroboration(self):
        pairs = fixture(); baseline = build_contexts(pairs, CLOCK)['EURUSD']
        for row in pairs['EURUSD']['decision_data']['raw']['h1']:
            for k in ('open','high','low','close'): row[k] *= 1.5
        # Change the own-pair return, not just its absolute price level.
        pairs['EURUSD']['decision_data']['raw']['h1'][-1].update(open=200, high=201, low=199, close=200)
        self.assertEqual(build_contexts(pairs, CLOCK)['EURUSD'], baseline)
        self.assertNotIn('EURUSD', baseline['daytrade']['contributing_pairs'])

    def test_missing_currency_does_not_disable_other_connected_pair_context(self):
        pairs = fixture(missing=tuple(p for p in PAIR_KEYS if 'CHF' in p))
        result = build_contexts(pairs, CLOCK)
        self.assertEqual(result['EURUSD']['daytrade']['status'], 'available')
        self.assertNotIn('CHF', result['EURUSD']['daytrade']['component_currencies'])
        self.assertEqual(result['USDCHF']['daytrade']['status'], 'unavailable')

    def test_single_own_edge_cannot_fabricate_strength(self):
        pairs = {'EURUSD': fixture()['EURUSD']}
        self.assertEqual(build_contexts(pairs, CLOCK)['EURUSD']['swing']['status'], 'unavailable')

    def test_research_source_override_cannot_relabel_strength_as_primary(self):
        pairs=fixture()
        for data in pairs.values():
            data['decision_data']['provenance']={k:'Dukascopy bid'
                for k in data['decision_data']['provenance']}
        with patch('fx_system.data_quality.SOURCE','Dukascopy bid'):
            result=build_contexts(pairs,CLOCK)
        self.assertEqual(result['EURUSD']['daytrade']['status'],'unavailable')

    def test_future_prices_and_input_mutation_are_excluded(self):
        pairs = fixture(); before = deepcopy(pairs); baseline = build_contexts(pairs, CLOCK)
        self.assertEqual(pairs, before)
        for data in pairs.values():
            data['decision_data']['raw']['h1'].append({'timestamp': END+3600,
                'open': 1e6, 'high': 1e6+1, 'low': 1e6-1, 'close': 1e6})
        self.assertEqual(build_contexts(pairs, CLOCK), baseline)

    def test_missing_old_window_does_not_hide_current_or_invent_change(self):
        result = build_contexts(fixture(hours=25), CLOCK)
        self.assertEqual(result['EURUSD']['swing']['status'], 'available')
        self.assertEqual(result['EURUSD']['swing']['comparison']['status'], 'unavailable')
        self.assertEqual(interpret(result['EURUSD']['swing'], 'EURUSD', 'swing', 'long', CLOCK)['movement'], 'unverified')

    def test_adjacent_comparison_uses_identical_pair_sets_and_no_stale_clock(self):
        pairs=fixture()
        pairs['GBPUSD']['decision_data']['raw']['h1'] = pairs['GBPUSD']['decision_data']['raw']['h1'][-30:]
        context=build_contexts(pairs,CLOCK)['EURUSD']['swing']
        self.assertIn('GBPUSD',context['contributing_pairs'])
        self.assertNotIn('GBPUSD',context['comparison']['contributing_pairs'])
        self.assertTrue(context['comparison']['same_pair_set'])
        bad=deepcopy(context);bad['comparison']['previous_end_closed_at']+=3600
        value=interpret(bad,'EURUSD','swing','long',CLOCK)
        self.assertEqual(value['status'],'available')
        self.assertEqual(value['movement'],'unverified')

    def test_stale_source_gap_or_unknown_provider_removes_affected_input(self):
        for mutation in ('stale','gap','source'):
            pairs = fixture()
            item = pairs['GBPUSD']['decision_data']; rows = item['raw']['h1']
            if mutation == 'stale': rows.pop()
            elif mutation == 'gap': rows.pop(-3)
            else: item['provenance']['h1:'+str(rows[-1]['timestamp'])] = 'Yahoo'
            result = build_contexts(pairs, CLOCK)['EURUSD']['daytrade']
            self.assertNotIn('GBPUSD', result['contributing_pairs'])
            self.assertEqual(result['status'], 'available')

    def test_stale_malformed_context_is_not_allowed_to_change_assessment(self):
        good = build_contexts(fixture(), CLOCK)['EURUSD']['daytrade']
        for changes in ({'evaluated_at':CLOCK-1}, {'difference': float('nan')},
                        {'contributing_pairs':['EURUSD','USDJPY']}, {'end_closed_at':CLOCK+3600},
                        {'source':'unknown'}):
            context = {**good, **changes}
            self.assertEqual(interpret(context, 'EURUSD', 'daytrade', 'long', CLOCK)['status'], 'unavailable')

    def test_opposition_is_context_not_skip_and_alignment_is_not_permission(self):
        good = build_contexts(fixture(), CLOCK)['EURUSD']['daytrade']
        aligned = assess_strategy('EURUSD', 'daytrade', mature_track(good), CLOCK)
        self.assertEqual((aligned['assessment'],aligned['grade']), ('review','A'))
        opposed = deepcopy(good); opposed['difference'] = -good['difference']
        opposed['comparison'] = {'status':'unavailable'}
        result = assess_strategy('EURUSD', 'daytrade', mature_track(opposed), CLOCK)
        self.assertEqual((result['assessment'],result['grade']), ('review','B'))
        self.assertEqual(result['currency_strength_context']['comparison_priority'],2)
        self.assertEqual(result['execution_authority'], 'none')
        self.assertTrue(any('通貨強弱' in r for r in result['opposing_evidence']))
        pending = mature_track(good); pending['base_verified'] = False
        self.assertEqual(assess_strategy('EURUSD','daytrade',pending,CLOCK)['assessment'], 'evaluation_pending')
        missing_plan = mature_track(good); missing_plan['reference_levels']['structural_target'] = None
        self.assertEqual(assess_strategy('EURUSD','daytrade',missing_plan,CLOCK)['grade'], 'C')

    def test_small_opposition_and_missing_scale_do_not_become_grade_gates(self):
        good=build_contexts(fixture(hours=150),CLOCK)['EURUSD']['daytrade']
        for mode in ('small','missing','tampered'):
            context=deepcopy(good); context['comparison']={'status':'unavailable'}
            context['difference']=-good['difference']*.01 if mode=='small' else -good['difference']
            if mode=='missing': context.pop('temporal_reference')
            if mode=='tampered': context['temporal_reference']['last_end_closed_at']+=3600
            result=assess_strategy('EURUSD','daytrade',mature_track(context),CLOCK)
            self.assertEqual(result['grade'],'A')
            self.assertFalse(result['currency_strength_context']['material_opposition'])

    def test_temporal_scale_uses_only_past_same_edges_and_horizon(self):
        from fx_system.strategy_strength import temporal_reference
        frames={p:{i*3600:100*math.exp(.001*i) for i in range(201)} for p in ('EURJPY','USDJPY')}
        # A gap invalidates its window, without treating the gap as a flat return.
        frames['EURJPY'].pop(190*3600)
        ref=temporal_reference(frames,['EURJPY','USDJPY'],'EURUSD',200*3600,6,.1)
        self.assertLess(ref['sample_count'],12)
        self.assertEqual(ref['status'],'unavailable')  # zero relative history
        contexts=build_contexts(fixture(hours=150),CLOCK)
        c=interpret(contexts['EURUSD']['daytrade'],'EURUSD','daytrade','long',CLOCK)
        self.assertEqual(c['gap_size'],'at_least_recent_median')
        self.assertEqual(c['other_horizon_relation'],'aligned')
        self.assertNotIn('EURUSD',c['temporal_reference']['contributing_pairs'])

    def test_frozen_legacy_context_roundtrip_and_mixed_generation_comparison(self):
        import json
        from fx_system.strategy_report_export import build_strategy_report_export, restore_strategy_report_export
        from fx_system.scenario_continuity import build_continuity
        from test_strategy_report_export import snapshot, SOURCE
        from unittest.mock import patch
        current=build_strategy_report_export(json.dumps(snapshot()).encode(),SOURCE)
        prior_clock=SOURCE['evaluated_at']-300
        with patch('test_strategy_report_export.CLOCK',prior_clock), patch('synthetic_candles.CLOCK',prior_clock):
            older=snapshot()
        context=build_contexts(fixture(),CLOCK)['EURUSD']['daytrade']
        context.pop('temporal_reference'); context.pop('other_horizon')
        legacy=interpret(context,'EURUSD','daytrade','long',CLOCK)
        self.assertNotIn('gap_size',legacy)
        self.assertEqual(legacy['comparison_priority'],0)
        self.assertEqual(interpret(legacy,'EURUSD','daytrade','long',CLOCK),legacy)
        # Exercise a frozen available legacy context inside a full32export.
        for row in older['scheduled_outlook']['strategy_assessments']:
            c=row.get('currency_strength_context',{})
            if c.get('status')!='available': continue
            for field in ('temporal_reference','other_horizon','gap_size','relative_size',
                          'material_opposition','other_horizon_relation'):
                c.pop(field,None)
            row['currency_strength_context']=interpret(c,row['pair'],row['strategy'],row['direction'],prior_clock)
        for row in older['scheduled_outlook']['rows']:
            row['strategy_assessments']={r['strategy']:r for r in older['scheduled_outlook']['strategy_assessments'] if r['pair']==row['pair']}
        source={**SOURCE,'run_id':122,'evaluated_at':prior_clock}
        prior=build_strategy_report_export(json.dumps(older).encode(),source)
        self.assertEqual(prior['status'],'saved')
        self.assertEqual(len(restore_strategy_report_export(prior,source,prior['snapshot_git_blob_sha'])['scheduled_outlook']['strategy_assessments']),32)
        comparison=build_continuity(current,SOURCE,current['snapshot_git_blob_sha'],prior,source,prior['snapshot_git_blob_sha'])
        self.assertEqual(comparison['status'],'saved')
        self.assertEqual(len(comparison['rows']),32)

    def test_balanced_strength_does_not_invent_a_range_trade(self):
        track = mature_track(); track.update(direction=None, base_structure='mixed')
        result = assess_strategy('EURUSD','daytrade',track,CLOCK)
        self.assertEqual(result['assessment'], 'skip')
        self.assertIn('方向構造', result['grade_reason'])

    def test_all32_contexts_roundtrip_and_tampered_clock_is_rejected(self):
        from fx_system.scheduled_outlook import build_scheduled_outlook
        from fx_system.validate_strategy_snapshot import validate_strategy_snapshot
        from diagnostics.monitoring_result_history import pack_generation, restore_generation
        outlook=build_scheduled_outlook(fixture(),{},evaluated_at=CLOCK)
        snapshot={'evaluated_at':CLOCK,'scheduled_outlook':outlook}
        self.assertEqual(len(outlook['strategy_assessments']),32)
        self.assertEqual(validate_strategy_snapshot(snapshot),[])
        restored=restore_generation(pack_generation(outlook['rows'],evaluated_at=CLOCK))
        self.assertEqual(restored['rows'],outlook['rows'])
        outlook['strategy_assessments'][0]['currency_strength_context']['evaluated_at']-=1
        self.assertTrue(validate_strategy_snapshot(snapshot))


if __name__ == '__main__': unittest.main()
