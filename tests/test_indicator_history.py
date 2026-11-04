"""Retention and archived-prefix reuse without requests, gap repair or revisions."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fx_system.core import aggregate
from fx_system.indicator_history import RETAINED_BARS, extend_from_archive, indicator_health
from fx_system.standard_technicals import frame
from fx_system.mt4_calendar import aggregate_h4
from fx_system.acquisition import rebuild_verified_h1, request_plan
from fx_system.provenance import key


NOW = 1800000000 // 14400 * 14400


def bars(count, seconds):
    return [{'timestamp': NOW-(count-i)*seconds, 'open':100+i*.01,
             'high':101+i*.01, 'low':99+i*.01, 'close':100.5+i*.01}
            for i in range(count)]


class IndicatorHistoryTests(unittest.TestCase):
    def context(self):
        return {'mode':'adopt', 'evaluated_at':NOW, 'source_contract_verified':True,
                'observed_availability':{'observed_available':True}}

    def test_existing_archive_supplies_201_h4_without_changing_retained_or_original(self):
        all_rows = bars(1000, 3600)
        current = all_rows[-500:]
        frames = {'h1':current, 'h4':aggregate_h4(current)}
        checkpoint = {'archive':{'pairs':{'EURUSD':{str(b['timestamp']):b for b in all_rows}}},
                      'blocked_pairs':{}}
        before = deepcopy((frames,checkpoint))
        result, diagnostic = extend_from_archive(frames,checkpoint,'EURUSD',self.context(),
            {'timeframes':{'h1':{'ok':True}}},NOW)
        self.assertEqual((frames,checkpoint),before)
        self.assertEqual(diagnostic['added_h1'],340)
        self.assertEqual(len(result['h1']),840)
        self.assertGreaterEqual(len(result['h4']),209)
        from fx_system.mt4_calendar import h4_start
        self.assertTrue(all(h4_start(r['timestamp'])==r['timestamp'] for r in result['h4']))
        f=frame(result['h4'],'h4',NOW,True)
        self.assertIsNotNone(f['sma']['200']['previous'])
        self.assertAlmostEqual(f['sma']['200']['value'],sum(b['close'] for b in result['h4'][-200:])/200)

    def test_gap_conflict_missing_evidence_and_future_clock_do_not_extend(self):
        all_rows=bars(900,3600);current=all_rows[-500:]
        original={'archive':{'pairs':{'EURUSD':{str(b['timestamp']):b for b in all_rows}}},'blocked_pairs':{}}
        frames={'h1':current,'h4':aggregate_h4(current)}
        for variant in ('gap','conflict','blocked','receipt','source','clock','quality'):
            state=deepcopy(original);context=self.context();quality={'timeframes':{'h1':{'ok':True}}}
            if variant=='gap':state['archive']['pairs']['EURUSD'].pop(str(current[0]['timestamp']-3600))
            if variant=='conflict':state['archive']['pairs']['EURUSD'][str(current[0]['timestamp'])]['close']+=.1
            if variant=='blocked':state['blocked_pairs']['EURUSD']='rejected'
            if variant=='receipt':context['observed_availability']['observed_available']=False
            if variant=='source':context['source_contract_verified']=False
            if variant=='clock':context['evaluated_at']=NOW+1
            if variant=='quality':quality['timeframes']['h1']['ok']=False
            result,d=extend_from_archive(frames,state,'EURUSD',context,quality,NOW)
            self.assertEqual(result,frames,variant)
            self.assertEqual(d['added_h1'],0,variant)

    def test_retention_has_room_for_sma200_slope_and_fetch_plan_unchanged(self):
        h1=bars(RETAINED_BARS['h1']+50,3600);m5=bars(RETAINED_BARS['m5'],300)
        sources={key('h1',b['timestamp']):'Twelve Data' for b in h1}
        sources.update({key('m5',b['timestamp']):'Twelve Data' for b in m5})
        retained,_=rebuild_verified_h1(h1,m5,sources,NOW)
        self.assertEqual(len(retained),840)
        self.assertGreaterEqual(len(aggregate(retained,3600,14400)),201)
        self.assertGreaterEqual(len(aggregate(m5,300,900)),201)
        self.assertEqual(sorted(request_plan({'h1':retained,'m5':m5},sources,NOW)),
                         [('h1','1h',240),('m5','5min',288)])

    def test_health_distinguishes_200_value_from_201_slope_without_inventing_values(self):
        for n in (166,200,201):
            health=indicator_health({'m15':frame(bars(n,900),'m15',NOW,True)})['m15']
            self.assertEqual(health['sma200_available'],n>=200)
            self.assertEqual(health['slope_available'],n>=201)
            self.assertEqual(health['shortfall'],max(0,201-n))

    def test_annotation_stays_compact_and_preserves_every_value(self):
        from fx_system.ny_archive_status import main,annotate
        value={'pairs':{'EURUSD':{'input':bars(660,300)}},'explanation':'日本語の保存根拠'}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'snapshot.json';path.write_text(json.dumps(value,indent=2))
            restore=Path(folder)/'restore.json';restore.write_text('{"status":"restored"}')
            save=Path(folder)/'save.json';save.write_text('{"status":"persisted"}')
            with patch('sys.argv',['annotate','--snapshot',str(path),'--restore-result',str(restore),
                 '--save-result',str(save),'--restore-outcome','success','--save-outcome','success']):
                main()
            expected=annotate(deepcopy(value),{'status':'restored'},{'status':'persisted'},restore_ok=True,save_ok=True)
            self.assertEqual(json.loads(path.read_bytes()),expected)
            self.assertEqual(path.read_bytes(),json.dumps(expected,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode())

    def test_larger_indicator_cache_keeps_existing_warehouse_transfer_window(self):
        from fx_system.backtest_cache_input import batches_from_cache
        from fx_system.monitor_pairs import PAIR_KEYS
        value={}
        for pair in PAIR_KEYS:
            value[pair]={tf:bars(RETAINED_BARS[tf],seconds) for tf,seconds in (('h1',3600),('m5',300))}
            value[pair]['bar_provenance']={key(tf,b['timestamp']):'Twelve Data'
                for tf in ('h1','m5') for b in value[pair][tf]}
        def batches(obj):
            raw=json.dumps(obj).encode();sha=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
            return batches_from_cache(raw,expected_git_blob=sha,evaluated_at=NOW)[0]
        expected=deepcopy(value)
        for item in expected.values():
            for tf in ('h1','m5'):item[tf]=item[tf][-500:]
        self.assertEqual(batches(value),batches(expected))


if __name__=='__main__':unittest.main()
