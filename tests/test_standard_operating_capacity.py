"""Full-universe capacity with distinct, maximum-retained indicator inputs."""
from copy import deepcopy
import base64
import json
import math
import random
import unittest
from unittest.mock import patch

from fx_system.core import aggregate, technical
from fx_system.indicator_history import RETAINED_BARS, indicator_health
from fx_system.standard_technicals import prepare
from fx_system.monitor_pairs import PAIR_KEYS
from fx_system.scheduled_outlook import build_scheduled_outlook
from fx_system.strategy_report_export import build_strategy_report_export,restore_strategy_report_export,MAX_EXPORT_BYTES
from diagnostics.monitoring_result_history import pack_generation,restore_generation,append_generation
from fx_system.run_diagnostics import build_diagnostics,LIMIT
from test_standard_technicals import CLOCK
from test_strategy_report_export import SOURCE


def maximum_pair(seed):
    rng=random.Random(seed);frames={}
    for tf,seconds,count in (('h1',3600,RETAINED_BARS['h1']),('m5',300,RETAINED_BARS['m5'])):
        start=(CLOCK//seconds-count)*seconds;price=100+seed
        rows=[]
        for i in range(count):
            o=price;price=round(price+.015+rng.uniform(-.05,.05),5)
            rows.append({'timestamp':start+i*seconds,'open':o,'close':price,
                         'high':round(max(o,price)+rng.uniform(.01,.09),5),'low':round(min(o,price)-rng.uniform(.01,.09),5)})
        frames[tf]=rows
    frames.update(h4=aggregate(frames['h1'],3600,14400),m15=aggregate(frames['m5'],300,900),d1=[],w1=[])
    q={'evaluated_at':CLOCK,'timeframes':{tf:{'ok':True} for tf in frames}}
    data={'technical':{tf:technical(rows) for tf,rows in frames.items()}}
    prepare(data,frames,frames,q)
    data['standard_technical_health']=indicator_health(data['standard_technical_frames'])
    data['decision_data']={'raw':{tf:frames[tf] for tf in ('h1','m5')},'provenance':{}}
    data['decision_quality']=q
    return data,q


class StandardOperatingCapacityTests(unittest.TestCase):
    def test_full32_maximum_distinct_inputs_restore_report_history_diagnostics_within_bounds(self):
        pairs={};quality={}
        for i,p in enumerate(PAIR_KEYS):pairs[p],quality[p]=maximum_pair(i)
        calendar={'observed_at_utc':CLOCK,'complete':False,'attribution_url':'https://example.invalid/synthetic',
                  'events':[{'currency':'USD','scheduled_at_utc':CLOCK+3600,'observed_at_utc':CLOCK,
                             'reference_only':True,'title':'Synthetic calendar '+str(i),'actual':None} for i in range(20)]}
        outlook=build_scheduled_outlook(pairs,quality,evaluated_at=CLOCK,economic_calendar=calendar)
        snapshot={'generated_at':CLOCK,'evaluated_at':CLOCK,'pairs':pairs,'quality':quality,'scheduled_outlook':outlook}
        raw=json.dumps(snapshot,ensure_ascii=False,separators=(',',':')).encode()
        self.assertLess(len(raw),32*1024*1024)
        report=build_strategy_report_export(raw,SOURCE)
        self.assertEqual(report['status'],'saved')
        self.assertEqual(report['encoding'],'xz_base64_json')
        self.assertLessEqual(len(json.dumps(report,ensure_ascii=False).encode()),MAX_EXPORT_BYTES)
        restored=restore_strategy_report_export(report,SOURCE,report['snapshot_git_blob_sha'])
        self.assertEqual(restored['scheduled_outlook']['strategy_assessments'],outlook['strategy_assessments'])
        self.assertEqual(len(restored['scheduled_outlook']['strategy_assessments']),32)
        self.assertNotIn('long_swing_reference', restored['scheduled_outlook'])
        self.assertNotIn('長期スイング参考', report['report_text'])
        broken=deepcopy(report)
        broken['payload_base64']=base64.b64encode(base64.b64decode(report['payload_base64'])+b'trailing').decode()
        with self.assertRaises(ValueError):restore_strategy_report_export(broken,SOURCE,report['snapshot_git_blob_sha'])
        with patch('fx_system.strategy_report_export.MAX_PAYLOAD_BYTES',100):
            with self.assertRaises(ValueError):restore_strategy_report_export(report,SOURCE,report['snapshot_git_blob_sha'])
        generation=pack_generation(outlook['rows'],evaluated_at=CLOCK)
        self.assertEqual(restore_generation(generation)['rows'],outlook['rows'])
        history=[]
        for i in range(4):history=append_generation(history,outlook['rows'],evaluated_at=CLOCK+i)
        self.assertEqual(len(history),3)
        diagnostic=json.loads(build_diagnostics(raw,SOURCE,returncode=0,
            validation_log='SNAPSHOT_VALIDATION {"passed":true,"failures":[]}'))
        self.assertFalse(diagnostic['truncated'])
        self.assertLessEqual(len(json.dumps(diagnostic).encode()),LIMIT)
        for p in PAIR_KEYS:
            for tf in ('h4','m15','h1','m5'):
                self.assertTrue(diagnostic['pairs'][p]['standard_technicals'][tf]['slope_available'])


if __name__=='__main__':unittest.main()
