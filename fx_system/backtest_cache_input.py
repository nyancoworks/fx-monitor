"""Read an already saved, hash-pinned cache; no market requests or D1 guesses."""
import hashlib
import json
from .backtest_partition import month_for, validate_bar

PAIRS = ('AUDJPY','AUDNZD','AUDUSD','CADJPY','CHFJPY','EURAUD','EURGBP','EURJPY',
         'EURUSD','GBPJPY','GBPUSD','NZDJPY','NZDUSD','USDCAD','USDCHF','USDJPY')
PROVIDERS = {'Twelve Data':'TwelveData','Dukascopy bid':'DukascopyBid'}


def batches_from_cache(raw, *, expected_git_blob, evaluated_at):
    actual=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    if actual!=expected_git_blob:raise ValueError('cache does not match canonical Git blob')
    if type(evaluated_at) is not int or evaluated_at<0:raise ValueError('invalid saved evaluation clock')
    cache=json.loads(raw)
    if not all(isinstance(cache.get(pair),dict) for pair in PAIRS):
        raise ValueError('canonical16 pair cache required')
    groups={};unknown=[];forming=[];missing=[]
    for pair in PAIRS:
        item=cache[pair];provenance=item.get('bar_provenance',{})
        for tf,seconds in (('m5',300),('h1',3600)):
            rows=item.get(tf,[])
            if not rows:missing.append({'pair':pair,'timeframe':tf})
            for original in rows:
                ts=original.get('timestamp')
                if type(ts) is not int:raise ValueError('invalid cache timestamp')
                if ts+seconds>evaluated_at:
                    forming.append({'pair':pair,'timeframe':tf,'timestamp':ts});continue
                source=provenance.get(tf+':'+str(ts))
                provider=PROVIDERS.get(source)
                if not provider:
                    unknown.append({'pair':pair,'timeframe':tf,'timestamp':ts,'source':source});continue
                month=month_for(ts);key=(provider,pair,tf,month)
                row={k:original[k] for k in ('timestamp','open','high','low','close')}
                row.update(source=source,captured_at=evaluated_at,capture_basis='saved_cache_known_by')
                groups.setdefault(key,[]).append(row)
    return [{'provider':k[0],'pair':k[1],'tf':k[2],'month':k[3],'rows':rows}
            for k,rows in sorted(groups.items())], {
                'cache_git_blob':actual,'saved_known_by':evaluated_at,
                'accepted_rows':sum(len(v) for v in groups.values()),
                'unknown_source_rows':unknown,'forming_rows':forming,'missing_streams':missing,
                'd1_from_cache_used':False,'provider_publication_clock_verified':False}


def daily_batches_from_snapshot(raw, *, expected_git_blob, evaluated_at):
    """Latest verified saved NY17 day, not a fresh reconstruction or backfill.

    Session validity is inherited from the saved adoption evidence and checked
    again by the existing codec. This does not certify a provider publication SLA.
    """
    actual=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    if actual!=expected_git_blob:
        raise ValueError('snapshot does not match saved Git blob')
    value=json.loads(raw)
    if value.get('evaluated_at')!=evaluated_at:
        raise ValueError('snapshot evaluation differs')
    transport=value.get('ny17_transport',{})
    if transport.get('restore_ok') is not True or transport.get('save_ok') is not True:
        raise ValueError('NY17 persistence must be verified first')
    groups={};unavailable=[]
    for pair in PAIRS:
        item=value.get('pairs',{}).get(pair,{})
        daily=item.get('d1',{})
        if (item.get('decision_quality',{}).get('ny17',{}).get('adoption_ready') is not True or
                daily.get('quality',{}).get('calendar')!='America/New_York 17:00' or
                not daily.get('candles')):
            unavailable.append(pair);continue
        original=daily['candles'][-1]
        row={k:original[k] for k in ('timestamp','open','high','low','close','session_end_utc')}
        row.update(session_start_utc=row['timestamp'],timestamp_role='session_start',
                   session_policy='NY17_verified',source='saved_NY17_from_private_archive',
                   captured_at=evaluated_at,capture_basis='saved_snapshot_known_by')
        validate_bar(row,'d1',evaluated_at)
        month=month_for(row['timestamp']);key=('DerivedNY17',pair,'d1',month)
        groups[key]=[row]
    return [{'provider':k[0],'pair':k[1],'tf':k[2],'month':k[3],'rows':rows}
            for k,rows in sorted(groups.items())],{
                'snapshot_git_blob':actual,'d1_rows':len(groups),'unavailable_d1_pairs':unavailable,
                'daily_scope':'latest_saved_verified_NY17_only',
                'provider_publication_clock_verified':False}
