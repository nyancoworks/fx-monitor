"""Pinned real-H1 offline replay. Prints counts/hashes only, never prices."""
import argparse
import datetime as dt
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path
from .issue43_ny_incremental import PAIRS, empty_archive, ingest, snapshot, save_atomic, load_archive, digest
from .issue43_ny_shadow import close_utc, UTC

ZIP_HASHES = {
    '11724133751.zip':'97c6dd8e4a3f983ec3c90e520c99cf557e5e42b89cab80d8c1641d8a246b29d5',
    '11725892978.zip':'bf5ad77ac6e781f8f1780f3fcac3bd1d478d0c35a7f57ff06c49f9b8063017cd'}


def run(directory):
    originals = {}; sources = {}
    for name, expected in ZIP_HASHES.items():
        packed=(Path(directory)/name).read_bytes()
        if hashlib.sha256(packed).hexdigest()!=expected:
            raise ValueError('original ZIP digest mismatch')
        with zipfile.ZipFile(Path(directory)/name) as z:
            for entry in z.namelist():
                raw=z.read(entry); data=json.loads(raw)
                pair=data.get('pair',data.get('symbol','')).replace('/','')
                if pair not in PAIRS or pair in sources or data.get('provider')!='Twelve Data' or data.get('requested_timezone')!='UTC':
                    raise ValueError('unverified source identity')
                sources[pair]=data['rows'];originals[pair]=hashlib.sha256(raw).hexdigest()
    if set(sources)!=set(PAIRS):raise ValueError('missing monitored pair')
    as_of=dt.datetime(2026,10,10,0,tzinfo=UTC)
    state=empty_archive(); report=[]
    with tempfile.TemporaryDirectory() as temporary:
        path=Path(temporary)/'checkpoint.json'; save_atomic(path,state)
        for pair in PAIRS:
            raw=sources[pair]
            full=ingest(empty_archive(),pair,raw,as_of=as_of,source_digest=originals[pair])
            expected=snapshot(full,pair,as_of)
            if expected['d1_count']!=60 or expected['w1_count']!=12 or not expected['calendar_ready']:
                raise ValueError('incomplete real source')
            # Omit one actual last constituent, checkpoint, reload, then recover it.
            missing=max(raw,key=lambda r:r['timestamp'])
            before=digest(state)
            state=ingest(state,pair,[r for r in raw if r['timestamp']!=missing['timestamp']],as_of=as_of,source_digest=originals[pair])
            save_atomic(path,state,expected_digest=before); state=load_archive(path)
            if snapshot(state,pair,as_of)['calendar_ready']:raise ValueError('gap incorrectly accepted')
            before=digest(state)
            state=ingest(state,pair,[missing],as_of=as_of,source_digest=originals[pair])
            save_atomic(path,state,expected_digest=before);state=load_archive(path)
            # Replay actual evidence as progressively closed daily increments.
            rolling=empty_archive(); verified_days=0; week_counts=[]
            for day in [dt.date.fromisoformat(d['trading_date_ny']) for d in expected['d1']]:
                clock=close_utc(day)+dt.timedelta(seconds=300)
                cutoff=int(clock.timestamp())
                rolling=ingest(rolling,pair,[r for r in raw if r['timestamp']+3600<=cutoff],as_of=clock,source_digest=originals[pair])
                q=snapshot(rolling,pair,clock)
                verified_days+=1;week_counts.append(q['w1_count'])
                # Independent OHLC reference on original H1, not aggregator output.
                end=int(close_utc(day).timestamp())
                bars=sorted([r for r in raw if end-86400<=r['timestamp']<end],key=lambda r:r['timestamp'])
                if len(bars)!=24:raise ValueError('independent H1 day incomplete')
                ref={'open':bars[0]['open'],'high':max(r['high'] for r in bars),
                     'low':min(r['low'] for r in bars),'close':bars[-1]['close']}
                if q['d1'][-1]['ohlc']!=ref:raise ValueError('independent daily arithmetic mismatch')
            final=snapshot(state,pair,as_of);rolled=snapshot(rolling,pair,as_of)
            if final['d1']!=expected['d1'] or rolled['d1']!=expected['d1'] or rolled['w1']!=expected['w1']:
                raise ValueError('incremental/full replay mismatch')
            for w in final['w1']:
                monday=dt.date.fromisoformat(w['week_start_ny'])
                days=[d for d in final['d1'] if monday<=dt.date.fromisoformat(d['trading_date_ny'])<monday+dt.timedelta(days=5)]
                ref={'open':days[0]['ohlc']['open'],'high':max(d['ohlc']['high'] for d in days),
                     'low':min(d['ohlc']['low'] for d in days),'close':days[-1]['ohlc']['close']}
                if len(days)!=5 or w['ohlc']!=ref:raise ValueError('independent weekly arithmetic mismatch')
            if ingest(state,pair,raw,as_of=as_of,source_digest=originals[pair])!=state:
                raise ValueError('replay not idempotent')
            report.append({'pair':pair,'h1':len(raw),'d1':final['d1_count'],'w1':final['w1_count'],
                'daily_roll_steps':verified_days,'partial_restart_passed':True,'independent_ohlc_passed':True,
                'weekly_roll_monotonic':week_counts==sorted(week_counts),'source_sha256':originals[pair],
                'formal_decision_permission':False})
    return {'status':'offline_real_evidence_passed','pairs':report,'api_calls':0,
            'source_zip_digests_verified':True,'source_preserved':True,'entry_permission':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--evidence',required=True)
    print(json.dumps(run(parser.parse_args().evidence),sort_keys=True))

