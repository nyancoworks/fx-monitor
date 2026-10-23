"""Synthetic source-health association and private saved-input integration."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_financecalendar_adapter import event, page, iso, CLOCK
from fx_system.financecalendar_adapter import normalize_calendar
from fx_system.economic_calendar_report import calendar_lines
from fx_system.economic_calendar_context import enrich_outlook
from fx_system.saved_economic_calendar import (load_saved_calendar, configured_calendar,
    build_outlook_with_saved_calendar, RELATIVE_PATH, CODE_ROOT)
from fx_system.scheduled_outlook import build_scheduled_outlook
from fx_system.strategy_report import _clock
from fx_system.validate_strategy_snapshot import validate_strategy_snapshot
from diagnostics.monitoring_result_history import pack_generation, restore_generation


def health(state='degraded', **changes):
    row = {'source_id':'synthetic-source', 'status':state, 'mode':'live',
           'checked_at':iso(CLOCK-30), 'fetched_at':iso(CLOCK-30),
           'error':'SYNTHETIC_PRIVATE_ERROR_DO_NOT_COPY'}
    row.update(changes)
    return {'time_utc':iso(CLOCK-10), 'snapshot':{'generated_at':iso(CLOCK-40)},
            'source_health_summary':{'reported':True}, 'source_health':[row]}


def reference_payload():
    return page(event(source_id='synthetic-source'))


def envelope():
    return {'schema':'financecalendar_saved_input_v1',
            'calendar':{'observed_at_utc':CLOCK, 'payload':reference_payload()},
            'status':{'observed_at_utc':CLOCK-5, 'payload':health()}}


class SourceHealthTests(unittest.TestCase):
    def normalize(self, status, observed=CLOCK-5):
        return normalize_calendar(reference_payload(), observed_at_utc=CLOCK,
                                  source_status=status, status_observed_at_utc=observed)

    def test_each_recorded_state_has_no_grade_or_freshness_authority(self):
        baseline=build_scheduled_outlook({}, {}, evaluated_at=CLOCK)
        for state in ('success','degraded','failed','disabled'):
            result=self.normalize(health(state))
            saved=result['events'][0]['source_health']
            self.assertEqual(saved['status'],state)
            self.assertEqual(saved['generation_match'],'unverified')
            self.assertEqual(saved['current_freshness'],'unverified')
            self.assertNotIn('error',saved)
            enriched=enrich_outlook(baseline,result)
            for old,new in zip(baseline['strategy_assessments'],enriched['strategy_assessments']):
                stripped=deepcopy(new); stripped.pop('economic_calendar_context')
                self.assertEqual(old,stripped)

    def test_missing_unreported_future_and_ambiguous_health_not_used(self):
        unreported=health(); unreported['source_health_summary']['reported']=False
        duplicate=health(); duplicate['source_health'].append(deepcopy(duplicate['source_health'][0]))
        future=health(checked_at=iso(CLOCK+1))
        future_build=health(); future_build['snapshot']['generated_at']=iso(CLOCK+1)
        wrong=health(source_id='synthetic-source:child')
        for data, observed in ((None,CLOCK-5),(unreported,CLOCK-5),(duplicate,CLOCK-5),
                               (future,CLOCK-5),(future_build,CLOCK-5),(wrong,CLOCK-5),
                               (health(),CLOCK+1),(health(),True)):
            self.assertEqual(self.normalize(data,observed)['events'][0]['source_health']['status'],'unverified')

    def test_static_success_has_no_invented_live_fetch(self):
        saved=self.normalize(health('success',mode='static',fetched_at=None))['events'][0]['source_health']
        self.assertIsNone(saved['fetched_at_utc'])
        self.assertEqual(saved['current_freshness'],'unverified')

    def test_hidden_degraded_events_still_have_report_warning(self):
        normalized=self.normalize(health())
        records=normalized['events']*4
        for item in records[:3]:
            self.assertEqual(item['source_health']['status'],'degraded')
        ctx={'status':'partial','events':records}
        rendered='\n'.join(calendar_lines({'economic_calendar_context':ctx},_clock))
        self.assertIn('関連指標4件',rendered)
        self.assertIn('非掲載分も含む',rendered)
        self.assertIn('劣化',rendered)
        self.assertNotIn('SYNTHETIC_PRIVATE_ERROR',rendered)


class SavedCalendarTests(unittest.TestCase):
    def write(self, root, value):
        target=Path(root)/RELATIVE_PATH
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(value))
        return target

    def test_default_does_not_open_any_file_and_matches_old_pipeline(self):
        with patch.dict(os.environ,{},clear=True), patch('pathlib.Path.open',side_effect=AssertionError('disabled')):
            self.assertIsNone(configured_calendar(evaluated_at=CLOCK))
            actual=build_outlook_with_saved_calendar({}, {}, evaluated_at=CLOCK)
        self.assertEqual(actual,build_scheduled_outlook({}, {}, evaluated_at=CLOCK))

    def test_explicit_private_saved_input_passes_32_snapshot_and_history(self):
        with tempfile.TemporaryDirectory() as root:
            self.write(root,envelope())
            with patch.dict(os.environ,{'FX_DATA_ROOT':root,'FX_ECONOMIC_CALENDAR_SAVED_ENABLED':'true'},clear=True), \
                 patch('socket.socket',side_effect=AssertionError('no network')):
                outlook=build_outlook_with_saved_calendar({}, {}, evaluated_at=CLOCK)
            self.assertEqual(validate_strategy_snapshot({'evaluated_at':CLOCK,'scheduled_outlook':outlook}),[])
            restored=restore_generation(pack_generation(outlook['rows'],evaluated_at=CLOCK))
            self.assertEqual(restored['rows'],outlook['rows'])
            context=outlook['strategy_assessments'][0]['economic_calendar_context']
            self.assertEqual(context['events'][0]['source_health']['status'],'degraded')
            self.assertEqual(context['acquisition_age_seconds'],0)

    def test_missing_corrupt_future_bad_payload_and_oversize_do_not_stop_decisions(self):
        with tempfile.TemporaryDirectory() as root:
            for mode in ('missing','corrupt','future','bad_schema','bad_payload','oversize'):
                value=envelope()
                target=Path(root)/RELATIVE_PATH
                if target.exists(): target.unlink()
                if mode=='future': value['calendar']['observed_at_utc']=CLOCK+1
                if mode=='bad_schema': value['schema']='unexpected'
                if mode=='bad_payload': value['calendar']['payload']={}
                if mode!='missing':
                    self.write(root,value)
                    if mode=='corrupt': target.write_text('{')
                    if mode=='oversize': target.write_bytes(b' '*100)
                with patch.dict(os.environ,{'FX_DATA_ROOT':root,'FX_ECONOMIC_CALENDAR_SAVED_ENABLED':'true'},clear=True), \
                     patch('fx_system.saved_economic_calendar.MAX_BYTES',50 if mode=='oversize' else 4*1024*1024):
                    actual=build_outlook_with_saved_calendar({}, {}, evaluated_at=CLOCK)
                self.assertEqual(validate_strategy_snapshot({'evaluated_at':CLOCK,'scheduled_outlook':actual}),[])
                for old,new in zip(build_scheduled_outlook({}, {}, evaluated_at=CLOCK)['strategy_assessments'],actual['strategy_assessments']):
                    stripped=deepcopy(new); context=stripped.pop('economic_calendar_context')
                    self.assertEqual(context['status'],'unavailable',mode)
                    self.assertEqual(old,stripped)

    def test_public_location_relative_root_and_symlink_inputs_refused(self):
        self.assertEqual(load_saved_calendar(CODE_ROOT,evaluated_at=CLOCK)['load_status'],'unavailable')
        self.assertEqual(load_saved_calendar('relative',evaluated_at=CLOCK)['load_status'],'unavailable')
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            target=self.write(root,envelope())
            original=self.write(outside,envelope())
            target.unlink(); target.symlink_to(original)
            self.assertEqual(load_saved_calendar(root,evaluated_at=CLOCK)['load_status'],'unavailable')
        with patch.dict(os.environ,{'FX_ECONOMIC_CALENDAR_SAVED_ENABLED':'true'},clear=True):
            self.assertEqual(configured_calendar(evaluated_at=CLOCK)['load_status'],'unavailable')

    def test_older_saved_reference_keeps_its_acquisition_age(self):
        with tempfile.TemporaryDirectory() as root:
            self.write(root,envelope())
            calendar=load_saved_calendar(root,evaluated_at=CLOCK+86400)
            enriched=enrich_outlook(build_scheduled_outlook({}, {}, evaluated_at=CLOCK+86400),calendar)
            context=enriched['strategy_assessments'][0]['economic_calendar_context']
            self.assertEqual(context['acquisition_age_seconds'],86400)
            self.assertEqual(context['freshness'],'unverified')

    def test_parent_symlink_and_non_regular_input_do_not_block(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            self.write(outside,envelope())
            (Path(root)/'data').symlink_to(Path(outside)/'data',target_is_directory=True)
            self.assertEqual(load_saved_calendar(root,evaluated_at=CLOCK)['load_status'],'unavailable')
        with tempfile.TemporaryDirectory() as root:
            target=Path(root)/RELATIVE_PATH
            target.parent.mkdir(parents=True)
            os.mkfifo(target)
            self.assertEqual(load_saved_calendar(root,evaluated_at=CLOCK)['load_status'],'unavailable')
