"""Lossless, bounded storage for full-prefix technical inputs; synthetic only."""
import base64
from copy import deepcopy
import gzip
import json
import unittest
from unittest.mock import patch
from fx_system.saved_standard_inputs import pack,unpack
from diagnostics.monitoring_result_history import pack_generation,restore_generation,append_generation
from fx_system.strategy_report_export import build_strategy_report_export,restore_strategy_report_export
from fx_system.scheduled_outlook import build_scheduled_outlook
from fx_system.monitor_pairs import PAIR_KEYS
from test_standard_technicals import inputs,CLOCK
from test_strategy_report_export import SOURCE


class SavedStandardInputsTests(unittest.TestCase):
    def test_identical_frames_interned_and_typed_candles_restored_exactly(self):
        d,_,_=inputs(count=40);f=d['standard_technical_frames']
        v={'standard_inputs':{'base':f['h4'],'trigger':f['m15'],'evaluated_at':CLOCK}}
        obj={'a':v,'b':deepcopy(v)};before=deepcopy(obj)
        packed=pack(obj)
        self.assertEqual(len(packed['standard_inputs']),1)
        self.assertIsInstance(packed['standard_inputs'][0]['base']['bars'],dict)
        self.assertEqual(unpack(packed,max_expanded_bytes=1000000),obj)
        self.assertEqual(obj,before)
        for change in ('index','columns','extra_table','layout','bomb'):
            bad=deepcopy(packed)
            if change=='index':bad['value']['a']['standard_inputs']['table_index']=True
            elif change=='columns':bad['standard_inputs'][0]['base']['bars']['columns'].append('unknown')
            elif change=='extra_table':bad['standard_inputs'].append(deepcopy(bad['standard_inputs'][0]))
            elif change=='layout':bad['schema']='future'
            with self.assertRaises(ValueError):unpack(bad,max_expanded_bytes=5 if change=='bomb' else 1000000)

    def test_32_calendar_enriched_records_report_and_history_roundtrip(self):
        d,q,_=inputs();calendar={'observed_at_utc':CLOCK,'complete':False,
            'attribution_url':'https://example.invalid/synthetic','events':[
                {'currency':'USD','scheduled_at_utc':CLOCK+3600,'observed_at_utc':CLOCK,
                 'reference_only':True,'title':'Synthetic reference '+str(i),'actual':None} for i in range(20)]}
        o=build_scheduled_outlook({p:deepcopy(d) for p in PAIR_KEYS},{p:deepcopy(q) for p in PAIR_KEYS},
            evaluated_at=CLOCK,economic_calendar=calendar)
        s={'evaluated_at':CLOCK,'scheduled_outlook':o};before=deepcopy(s)
        b=build_strategy_report_export(json.dumps(s).encode(),SOURCE)
        self.assertEqual(b['status'],'saved');self.assertEqual(b['payload_layout'],'standard_inputs_v3')
        v=restore_strategy_report_export(b,SOURCE,b['snapshot_git_blob_sha'])
        self.assertEqual(v['scheduled_outlook']['strategy_assessments'],o['strategy_assessments'])
        generation=pack_generation(o['rows'],evaluated_at=CLOCK)
        self.assertEqual(generation['payload_layout'],'standard_inputs_v1')
        self.assertEqual(restore_generation(generation)['rows'],o['rows'])
        # The existing decoded bound applies to the smaller representation,
        # not to copies reconstructed under their separate expansion bound.
        packed_len=len(gzip.decompress(base64.b64decode(generation['gzip_base64'])))
        original_len=len(json.dumps({'schema':'monitoring_result_generation_v1','evaluated_at':CLOCK,'rows':o['rows']},ensure_ascii=False,separators=(',',':')).encode())
        self.assertLess(packed_len,original_len)
        with patch('diagnostics.monitoring_result_history.MAX_PLAIN_BYTES',packed_len):
            self.assertEqual(restore_generation(pack_generation(o['rows'],evaluated_at=CLOCK))['rows'],o['rows'])
        self.assertEqual(s,before)
        self.assertEqual(append_generation([generation],o['rows'],evaluated_at=CLOCK),[generation])

if __name__=='__main__':unittest.main()
