from copy import deepcopy
import json
import unittest
from fx_system.technical_scenario import refresh
from fx_system.scenario_continuity import _brief
from fx_system.strategy_report_export import build_strategy_report_export,restore_strategy_report_export
from test_technical_forecast import track,assess
from test_swing_horizon import with_record
from test_strategy_report_export import SOURCE


def ending(strategy='swing',direction='long',hist=(.1,.2,.3)):
    t=track(strategy,direction,hist=hist)
    inp=t['technical_plan_inputs'];end=inp['projection']['end_pivot']
    old=end['price'];new=104 if direction=='long' else 116
    end['price']=new
    for p in inp['highs' if direction=='long' else 'lows']:
        if p['price']==old:p['price']=new
    return t


class WaveExtensionTests(unittest.TestCase):
    def test_sustained_break_and_directional_momentum_activate_conditional_extension(self):
        for strategy in ('swing','daytrade'):
            for direction in ('long','short'):
                r=assess(ending(strategy,direction),strategy)
                self.assertEqual(r['wave_price_plan']['path_stage'],'extension_active')
                self.assertIsNotNone(r['reference_levels']['scenario_target'])

    def test_fading_or_mixed_momentum_cannot_activate_distant_target(self):
        for hist in ((.3,.2,.1),(.2,.1,.3),(-.3,-.2,-.1)):
            r=assess(ending(hist=hist))
            self.assertEqual(r['wave_price_plan']['path_stage'],'extension_wait')
            self.assertIsNone(r['reference_levels']['scenario_target'])
            self.assertNotEqual(r['practical_review']['status'],'technical_watch')
            self.assertIsNotNone(r['wave_price_plan']['extension_zone'])

    def test_first_break_does_not_activate_extension_or_change_wave_anchors(self):
        t=ending();t['base_evolution_inputs']['points'][-2]['close']=103
        r=assess(t)
        self.assertEqual(r['wave_price_plan']['path_stage'],'extension_wait')
        original=deepcopy(r);legacy=deepcopy(r);legacy.pop('price_path_review_version');refresh(legacy)
        self.assertIsNotNone(legacy['reference_levels']['scenario_target'])
        self.assertEqual(r['direction'],legacy['direction'])
        for field in ('start_pivot','end_pivot','thesis_invalidation','local_setup_failure','first_obstacle'):
            self.assertEqual(r['wave_price_plan'][field],legacy['wave_price_plan'][field])
        self.assertEqual(refresh(json.loads(json.dumps(original,sort_keys=True))),original)
        brief=_brief(r)['wave_price_plan']
        self.assertEqual(brief['path_stage'],'extension_wait')
        self.assertEqual(brief['thesis_invalidation'],r['wave_price_plan']['thesis_invalidation'])
        self.assertEqual(brief['extension_confirmation']['active'],False)
        self.assertNotIn('meaning',brief['extension_confirmation'])
        self.assertIn('meaning',r['wave_price_plan']['extension_confirmation'])

    def test_retest_keeps_endpoint_and_old_saved_interpretation_restores(self):
        r=assess(track());self.assertEqual(r['wave_price_plan']['path_stage'],'retest')
        self.assertEqual(r['reference_levels']['scenario_target'],r['wave_price_plan']['retest_objective']['price'])
        for mode in ('new','old'):
            value=deepcopy(r)
            if mode=='old':value.pop('price_path_review_version');refresh(value)
            snapshot=with_record(value);b=build_strategy_report_export(json.dumps(snapshot).encode(),SOURCE)
            self.assertEqual(b['status'],'saved')
            restore_strategy_report_export(b,SOURCE,b['snapshot_git_blob_sha'])
        for version in (True,2,'1'):
            broken=deepcopy(r);broken['price_path_review_version']=version
            with self.assertRaises(ValueError):refresh(broken)
