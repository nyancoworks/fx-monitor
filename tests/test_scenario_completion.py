"""A is scenario completion, not just a defined list of possible reactions."""
import unittest
from copy import deepcopy
from unittest.mock import patch
from test_technical_entry import record
from fx_system.standard_technicals import refresh


class ScenarioCompletionTests(unittest.TestCase):
    def evaluate(self, *, observed=False, weak=False, legacy=False,
                 murphy_primary=False, opposition=()):
        r = record()
        r['macro_context'] = {}
        r.pop('murphy_primary_version', None)
        if legacy:
            r.pop('scenario_completion_version')
        if murphy_primary:
            r['murphy_primary_version'] = 1
        f = deepcopy(r['technical_outlook']['forecast'])
        f.update(phase='continuation', conviction='weak' if weak else 'developing',
                 material_cautions=[])
        signals = ['macd_signal_cross'] if observed else []
        with patch('fx_system.standard_technicals.forecast', side_effect=lambda *a,**k:deepcopy(f)), \
             patch('fx_system.span_special.apply', side_effect=lambda frame,f,**kw:f), \
             patch('fx_system.technical_entry.timing_signals', return_value=signals), \
             patch('fx_system.span_special.timing', return_value=[]), \
             patch('fx_system.murphy_timing_context.describe', return_value={
                 'opposing_components':list(opposition), 'concise_summary':'確認足の主軸を照合'}):
            return refresh(r)

    def test_defined_but_unobserved_reaction_is_b(self):
        old = self.evaluate(legacy=True)
        new = self.evaluate()
        self.assertEqual(old['grade'], 'A')
        self.assertEqual(new['grade'], 'B')
        self.assertEqual(new['scenario_conditions']['status'], 'waiting')
        self.assertIn('反応は未観測', new['grade_reason'])
        for key in ('direction','assessment','reference_levels','scenario_conditions'):
            self.assertEqual(old[key], new[key])

    def test_one_observed_alternative_can_still_be_a(self):
        r = self.evaluate(observed=True)
        self.assertEqual(r['grade'], 'A')
        self.assertEqual(r['scenario_conditions']['evidence']['signals'], ['macd_signal_cross'])
        self.assertIsNone(r['scenario_conditions']['formation_price'])

    def test_observed_reaction_does_not_override_weak_scenario(self):
        self.assertEqual(self.evaluate(observed=True, weak=True)['grade'], 'C')
        self.assertEqual(self.evaluate(weak=True)['grade'], 'C')

    def test_primary_sb_and_blue_opposition_keeps_local_reaction_b(self):
        old = self.evaluate(observed=True, opposition=('sb_movement','blue_position'))
        new = self.evaluate(observed=True, murphy_primary=True,
                            opposition=('sb_movement','blue_position'))
        self.assertEqual((old['grade'],new['grade']), ('A','B'))
        self.assertEqual(new['scenario_conditions']['status'], 'conditions_observed')
        self.assertIn('murphy_confirmation_opposed',
                      new['technical_outlook']['forecast']['material_cautions'])
        self.assertIn('局所反応のみ観測', new['grade_reason'])
        for key in ('direction','assessment','reference_levels','scenario_conditions'):
            self.assertEqual(old[key],new[key])

    def test_one_primary_disagreement_is_context_not_a_fixed_gate(self):
        for opposition in ((), ('sb_movement',), ('blue_position',)):
            result = self.evaluate(observed=True, murphy_primary=True,
                                   opposition=opposition)
            self.assertEqual(result['grade'], 'A')

    def test_murphy_primary_version_requires_current_context(self):
        r = record()
        r['murphy_primary_version'] = True
        with self.assertRaises(ValueError):
            refresh(r)

    def test_old_saved_record_and_version_validation(self):
        r = record();r.pop('scenario_completion_version');refresh(r)
        self.assertEqual(refresh(deepcopy(r)),r)
        r['scenario_completion_version'] = True
        with self.assertRaises(ValueError):
            refresh(r)
