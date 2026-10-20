"""Opt-in sidecar for existing H1 acquisition, never a production writer.

No network code. Capture returns the existing fetch result unchanged; only
the caller's already-existing request executes. Own checkpoint, not cache/latest.
"""
import copy
import datetime as dt
import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from .issue43_ny_incremental import (
    PAIRS, UTC, empty_archive, ingest, digest, validate_state, snapshot)
from .issue43_ny_switch_adapter import rehearse

MAX_CHECKPOINT_BYTES=64*1024*1024


def empty_checkpoint():
    return {'schema':'issue43_ny_runtime_v1','generation':0,'archive':empty_archive(),
            'blocked_pairs':{},'receipts':[],'previous_checkpoint_sha256':None}


def validate_checkpoint(value):
    if (not isinstance(value,dict) or value.get('schema')!='issue43_ny_runtime_v1'
            or type(value.get('generation')) is not int or value['generation']<0
            or not isinstance(value.get('blocked_pairs'),dict)
            or not isinstance(value.get('receipts'),list)):
        raise ValueError('invalid checkpoint')
    validate_state(value['archive'])
    if any(p not in PAIRS for p in value['blocked_pairs']):
        raise ValueError('unknown blocked pair')


def observation(pair, rows, available_at, *, kind='existing_h1_response'):
    if available_at.tzinfo is None or available_at.utcoffset() is None:
        raise ValueError('aware response availability required')
    # Explicit allowlist: keys, URLs, response objects cannot enter the archive.
    clean=[{k:r.get(k) for k in ('timestamp','open','high','low','close')} for r in rows]
    return {'pair':pair.replace('/',''),'rows':clean,
            'available_at_utc':available_at.astimezone(UTC).isoformat(),
            'source_sha256':digest(clean),'kind':kind}


def capture_existing_fetch(fetch, queue, *, clock):
    """Transparent wrapper. Capture failure never changes legacy fetch outcome."""
    def wrapped(session, key, pair, interval, limit, now):
        returned=fetch(session,key,pair,interval,limit,now)
        if interval=='1h':
            try:
                rows=returned[0]
                queue.append(observation(pair,rows,clock()))
            except Exception:
                # Do not expose exceptions that may contain credentials.
                queue.append({'pair':pair.replace('/',''),'capture_error':True})
        return returned
    return wrapped


class NYSidecar:
    def __init__(self, directory, *, enabled=False):
        if type(enabled) is not bool:raise TypeError('explicit enabled bool required')
        self.directory=Path(directory);self.enabled=enabled
        # A sidecar may not masquerade as the legacy persistence files.
        if self.directory.name in ('latest.json','cache.json'):
            raise ValueError('legacy persistence destination forbidden')
        self.path=self.directory/'ny17-checkpoint.json'

    def load(self):
        if self.path.exists() and self.path.stat().st_size>MAX_CHECKPOINT_BYTES:
            raise ValueError('checkpoint capacity exceeded')
        value=json.loads(self.path.read_bytes()) if self.path.exists() else empty_checkpoint()
        validate_checkpoint(value)
        return value

    @contextmanager
    def _writer(self):
        if self.directory.is_symlink():raise ValueError('symlink storage forbidden')
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        if self.path.is_symlink():raise ValueError('symlink checkpoint forbidden')
        lock=self.directory/'ny17-writer.lock'
        if lock.is_symlink():raise ValueError('symlink lock forbidden')
        fd=os.open(lock,os.O_CREAT|os.O_RDWR,0o600)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)

    def _commit(self, value):
        validate_checkpoint(value)
        payload=json.dumps(value,sort_keys=True,allow_nan=False).encode()
        if len(payload)>MAX_CHECKPOINT_BYTES:raise ValueError('checkpoint capacity exceeded')
        fd,name=tempfile.mkstemp(dir=self.directory,prefix='.ny17-')
        try:
            with os.fdopen(fd,'wb') as f:
                f.write(payload)
                f.flush();os.fsync(f.fileno())
            os.replace(name,self.path)
            dir_fd=os.open(self.directory,os.O_RDONLY)
            try:os.fsync(dir_fd)
            finally:os.close(dir_fd)
        finally:
            Path(name).unlink(missing_ok=True)

    def update(self, observations, *, accept_revisions=False):
        if not self.enabled:return {'status':'disabled','saved':False,'generation':None}
        with self._writer():
            previous=self.load();value=copy.deepcopy(previous);summaries=[]
            for item in observations:
                pair=item.get('pair')
                if pair not in PAIRS:raise ValueError('unknown pair')
                before=digest(value['archive'])
                try:
                    if item.get('capture_error'):raise ValueError('capture failure')
                    available=dt.datetime.fromisoformat(item['available_at_utc'])
                    if digest(item['rows'])!=item['source_sha256']:
                        raise ValueError('response digest mismatch')
                    value['archive']=ingest(value['archive'],pair,item['rows'],as_of=available,
                        source_digest=item['source_sha256'],accept_revisions=accept_revisions)
                    pending=value['blocked_pairs'].get(pair,{})
                    required=pending.get('required_timestamps',[]) if isinstance(pending,dict) else []
                    received={r['timestamp'] for r in item['rows']}
                    # Empty/unrelated responses cannot erase a rejected revision.
                    if received and set(required).issubset(received):
                        value['blocked_pairs'].pop(pair,None)
                    if digest(value['archive'])!=before:
                        value['receipts'].append({'pair':pair,'source_sha256':item['source_sha256'],
                            'available_at_utc':item['available_at_utc'],'kind':item.get('kind'),
                            'revisions_explicitly_accepted':accept_revisions})
                    summaries.append({'pair':pair,'status':'accepted','rows_observed':len(item['rows'])})
                except (ValueError,TypeError,KeyError,OverflowError):
                    # Entire pair batch rejected. Keep prior history but block its use.
                    required=[r['timestamp'] for r in item.get('rows',[])
                              if isinstance(r,dict) and type(r.get('timestamp')) is int]
                    value['blocked_pairs'][pair]={'reason':'incoming_h1_rejected_requires_review',
                                                 'required_timestamps':sorted(set(required))}
                    summaries.append({'pair':pair,'status':'blocked'})
            saved=False
            if value!=previous:
                value['generation']+=1;value['previous_checkpoint_sha256']=digest(previous)
                self._commit(value);saved=True
            return {'status':'updated','generation':value['generation'],'saved':saved,
                    'pairs':summaries,'blocked_pairs':sorted(value['blocked_pairs'])}

    def quality(self, production_snapshot, *, ny_contract_adopted=False,
                publication_lag_seconds=0, closed_holidays=(), as_of=None):
        if as_of is None:
            as_of=dt.datetime.fromtimestamp(production_snapshot['evaluated_at'],UTC)
        if not self.enabled:
            return {'status':'disabled','formal_decision_permission':False,'entry_permission':False}
        value=self.load();rows=[]
        for pair in PAIRS:
            if pair not in production_snapshot['pairs']:continue
            result=rehearse(production_snapshot['pairs'][pair],value['archive'],pair,as_of,
                ny_contract_adopted=ny_contract_adopted,
                publication_lag_seconds=publication_lag_seconds,closed_holidays=closed_holidays)
            if pair in value['blocked_pairs']:
                result['candidate_decision_data_ready']=False
                result['candidate_blockers'].append('archive_incoming_batch_blocked')
            if any(r['pair']==pair and dt.datetime.fromisoformat(r['available_at_utc'])>as_of
                   for r in value['receipts']):
                result['candidate_decision_data_ready']=False
                result['candidate_blockers'].append('source_not_available_at_evaluation')
            rows.append(result)
        return {'schema':'issue43_ny_quality_sidecar_v1','generation':value['generation'],
                'checkpoint_sha256':digest(value),'pairs':rows,
                'formal_decision_permission':False,'entry_permission':False}

    def synchronize(self, production_snapshot, captured=(), *, ny_contract_adopted=False,
                    publication_lag_seconds=0, closed_holidays=()):
        """Existing responses first; cache-derived H1 fills only the new tail.

        Historical cache overlap is not treated as a new provider revision.
        Direct response overlap is checked and can block the pair. No retries.
        """
        if not self.enabled:return {'status':'disabled','saved':False}
        direct=self.update(captured)
        checkpoint=self.load();queue=[]
        available=dt.datetime.fromtimestamp(production_snapshot['evaluated_at'],UTC)
        for pair in PAIRS:
            if pair not in production_snapshot['pairs']:continue
            if pair in checkpoint['blocked_pairs']:continue
            data=production_snapshot['pairs'][pair]['decision_data']
            old=checkpoint['archive']['pairs'].get(pair,{})
            watermark=max((int(t) for t in old),default=-1)
            rows=[b for b in data['raw']['h1'] if b['timestamp']>watermark
                  and data['provenance'].get('h1:'+str(b['timestamp']))=='Twelve Data']
            if rows:queue.append(observation(pair,rows,available,kind='verified_snapshot_h1_tail'))
        tail=self.update(queue)
        return {'direct_capture':direct,'tail_capture':tail,
                'quality':self.quality(production_snapshot,ny_contract_adopted=ny_contract_adopted,
                    publication_lag_seconds=publication_lag_seconds,closed_holidays=closed_holidays)}


def run_existing_refresh(refresh, module, sidecar, *, clock, load_snapshot,
                         ny_contract_adopted=False, publication_lag_seconds=0):
    """Candidate hookup for the *same* existing refresh. Never starts a refresh itself.

    Caller supplies the already-authorized refresh and snapshot reader. Tests
    use an offline publisher. Default disabled does not patch or read/write storage.
    """
    if not sidecar.enabled:return refresh(),{'status':'disabled'}
    queue=[];original=module.fetch
    module.fetch=capture_existing_fetch(original,queue,clock=clock)
    try:
        result=refresh()
    except Exception:
        # Keep already-returned H1 evidence even if a later legacy step fails.
        # This does not retry or suppress the original publisher exception.
        try:sidecar.update(queue)
        except Exception:pass
        raise
    finally:
        module.fetch=original
    try:
        report=sidecar.synchronize(load_snapshot(),queue,ny_contract_adopted=ny_contract_adopted,
                                   publication_lag_seconds=publication_lag_seconds)
    except Exception:
        report={'status':'sidecar_unavailable','formal_decision_permission':False,'entry_permission':False}
    return result,report

