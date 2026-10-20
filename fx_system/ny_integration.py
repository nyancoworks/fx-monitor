"""Opt-in NY17 publisher integration; performs no network requests."""
from contextlib import contextmanager
import datetime as dt
import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path
from diagnostics.issue43_ny_incremental import PAIRS,UTC,digest,snapshot
from diagnostics.issue43_ny_incremental_e2e import ZIP_HASHES
from diagnostics.issue43_ny_runtime import NYSidecar,observation,validate_checkpoint,MAX_CHECKPOINT_BYTES
from .monitor_pairs import PINNED_ORIGINAL_PAIRS

class PrivateArchive(NYSidecar):
    def seed_additional_originals(self,evidence_directory,as_of=None):
        """Append verified new-pair genesis; preserve all existing pair histories."""
        from .ny_observed_policy import verify_originals,supported_source
        contracts=verify_originals(evidence_directory)
        state=self.load();queue=[]
        for pair,original in contracts.items():
            if pair in PINNED_ORIGINAL_PAIRS:continue
            received=dt.datetime.fromisoformat(original['received_as_of_utc'])
            if as_of is not None and received.timestamp()>as_of:continue
            if pair in state['archive']['pairs']:
                # Existing observed history is never overwritten by a seed.
                if not supported_source(state,pair,contracts):continue
                continue
            queue.append(observation(pair,list(original['bars'].values()),
                received,kind='private_pinned_additional_seed'))
        return self.update(queue)

    def load(self):
        if self.directory.is_symlink() or self.path.is_symlink():raise ValueError('symlink archive forbidden')
        return super().load()

    @contextmanager
    def _writer(self):
        if self.directory.exists() and self.directory.stat().st_mode & 0o077:
            raise ValueError('private archive directory permissions required')
        with super()._writer():yield

    @property
    def backup(self):return self.directory/'ny17-checkpoint.previous.json'

    def _replace(self,path,payload):
        if path.is_symlink():raise ValueError('symlink destination forbidden')
        fd,name=tempfile.mkstemp(dir=self.directory,prefix='.ny17-backup-')
        try:
            with os.fdopen(fd,'wb') as stream:
                stream.write(payload);stream.flush();os.fsync(stream.fileno())
            os.replace(name,path)
            fd=os.open(self.directory,os.O_RDONLY)
            try:os.fsync(fd)
            finally:os.close(fd)
        finally:Path(name).unlink(missing_ok=True)

    def _commit(self,value):
        validate_checkpoint(value)
        payload=json.dumps(value,sort_keys=True,allow_nan=False).encode()
        if len(payload)>MAX_CHECKPOINT_BYTES:raise ValueError('checkpoint capacity exceeded')
        if self.path.exists():
            prior=self.load()
            if value['previous_checkpoint_sha256']!=digest(prior):raise ValueError('checkpoint generation conflict')
            self._replace(self.backup,self.path.read_bytes())
        self._replace(self.path,payload)

    def restore_previous(self,expected_sha256):
        """Explicit recovery with caller-verified backup identity; no silent reset."""
        if not self.enabled:raise ValueError('disabled recovery')
        with self._writer():
            if self.backup.is_symlink() or self.backup.stat().st_size>MAX_CHECKPOINT_BYTES:raise ValueError('unsafe backup')
            payload=self.backup.read_bytes();value=json.loads(payload);validate_checkpoint(value)
            if digest(value)!=expected_sha256:raise ValueError('backup identity mismatch')
            self._replace(self.path,payload)
            return value['generation']

    def bootstrap(self,evidence_directory,as_of):
        if self.load()['generation']!=0:return {'status':'already_seeded'}
        queue=[]
        for name,expected in ZIP_HASHES.items():
            path=Path(evidence_directory)/name
            if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:raise ValueError('seed ZIP hash mismatch')
            with zipfile.ZipFile(path) as archive:
                for entry in archive.namelist():
                    data=json.loads(archive.read(entry));pair=data.get('pair',data.get('symbol','')).replace('/','')
                    if data.get('provider')!='Twelve Data' or data.get('requested_timezone')!='UTC':raise ValueError('seed source mismatch')
                    queue.append(observation(pair,data['rows'],as_of,kind='private_pinned_zip_seed'))
        if sorted(x['pair'] for x in queue)!=sorted(PINNED_ORIGINAL_PAIRS):raise ValueError('incomplete seed universe')
        report=self.update(queue)
        if report.get('blocked_pairs'):raise ValueError('seed batch rejected')
        return report

class NYIntegration:
    def __init__(self,*,mode,directory,source_contract_verified=False,publication_verified=False,publication_lag_seconds=None,closed_holidays=(),evidence_profile=None,evidence_directory=None):
        if mode not in ('shadow','adopt'):raise ValueError('invalid NY mode')
        if type(source_contract_verified) is not bool or type(publication_verified) is not bool:raise ValueError('explicit evidence flags required')
        if publication_lag_seconds is not None and (type(publication_lag_seconds) is not int or publication_lag_seconds<0):raise ValueError('invalid publication lag')
        self.mode=mode;self.sidecar=PrivateArchive(directory,enabled=True)
        self.source_verified=source_contract_verified
        self.publication_verified=publication_verified and publication_lag_seconds is not None
        self.lag=publication_lag_seconds if publication_lag_seconds is not None else 0
        self.holidays=tuple(closed_holidays);self.queue=[];self.value=None;self.failure=None;self.invalid_pairs=set()
        self.evidence_profile=evidence_profile;self.evidence_directory=evidence_directory;self.original_contracts=None
        if evidence_profile is not None:
            from .ny_observed_policy import PROFILE
            if evidence_profile!=PROFILE:raise ValueError('unsupported NY evidence profile')
            if evidence_directory is None:raise ValueError('immutable original evidence required')
            # Receipt completeness is the proposed publication policy; never a
            # claimed arbitrary provider delay such as the old 300-second fixture.
            self.lag=0

    def check_payload(self,payload,pair,now):
        """Filtered-out malformed CLOSED H1 must not silently preserve old history."""
        from .core import parse_row
        try:
            if not isinstance(payload.get('values'),list):raise ValueError('invalid source list')
            for row in payload['values']:
                date=dt.datetime.fromisoformat(row['datetime'].replace(' ','T'))
                if date.tzinfo is None:date=date.replace(tzinfo=UTC)
                stamp=int(date.timestamp())
                if stamp%3600 or (stamp+3600<=now and parse_row(row,3600,now) is None):raise ValueError('invalid closed H1')
        except (ValueError,TypeError,KeyError,OverflowError,AttributeError):self.invalid_pairs.add(pair.replace('/',''))

    def wrap_fetch(self,fetch,clock):
        def wrapped(session,key,pair,interval,limit,now):
            try:returned=fetch(session,key,pair,interval,limit,now)
            except Exception:
                if interval=='1h':self.queue.append({'pair':pair.replace('/',''),'capture_error':True})
                raise
            if interval=='1h':
                try:
                    if pair.replace('/','') in self.invalid_pairs:raise ValueError('invalid source batch')
                    self.queue.append(observation(pair,returned[0],clock()))
                except Exception:self.queue.append({'pair':pair.replace('/',''),'capture_error':True})
            return returned
        return wrapped

    def synchronize(self,production):
        if os.getenv('FX_NY17_RESTORE_FAILED') == '1':
            self.value=None;self.failure='NY remote restore failed; persistent continuity unverified'
            self.queue=[]
            return
        try:
            if self.evidence_profile is not None:
                from .ny_observed_policy import verify_originals
                self.original_contracts=verify_originals(self.evidence_directory)
                self.original_contracts={p:o for p,o in self.original_contracts.items()
                    if 'received_as_of_utc' not in o or
                    dt.datetime.fromisoformat(o['received_as_of_utc']).timestamp()<=production['evaluated_at']}
                if (Path(self.evidence_directory)/'additional-originals.json').exists():
                    self.sidecar.seed_additional_originals(self.evidence_directory,production['evaluated_at'])
                # No unpinned partial genesis for a new pair: install its complete
                # immutable seed before capturing normal rolling H1 responses.
                missing=set(PAIRS)-set(self.original_contracts)-set(PINNED_ORIGINAL_PAIRS)
                if missing:
                    production={**production,'pairs':{p:d for p,d in production['pairs'].items() if p not in missing}}
                    self.queue=[item for item in self.queue if item.get('pair') not in missing]
            self.sidecar.synchronize(production,self.queue,publication_lag_seconds=self.lag,closed_holidays=self.holidays)
            self.value=self.sidecar.load()
        except Exception:self.value=None;self.failure='NY archive unavailable; manual recovery required'
        self.queue=[]

    def context(self,pair,now):
        blockers=[];study=None;availability=None
        if self.value is None:blockers.append(self.failure or 'NY archive not synchronized')
        else:
            if pair in self.value['blocked_pairs']:blockers.append('NY incoming source batch rejected')
            clock=dt.datetime.fromtimestamp(now,UTC)
            from .ny_availability import observed_availability
            try:
                availability=observed_availability(self.value,pair,now)
                blockers.extend(availability['reasons'])
            except (ValueError,TypeError,KeyError,OverflowError):
                blockers.append('NY source availability audit failed')
            if any(r['pair']==pair and dt.datetime.fromisoformat(r['available_at_utc'])>clock for r in self.value['receipts']):blockers.append('NY H1 unavailable at evaluation clock')
            try:study=snapshot(self.value['archive'],pair,clock,publication_lag_seconds=self.lag,closed_holidays=self.holidays)
            except Exception:blockers.append('NY snapshot validation failed')
        context={'mode':self.mode,'evaluated_at':now,'study':study,'blockers':list(dict.fromkeys(blockers)),
                'observed_availability':availability,
                'source_contract_verified':self.source_verified,'publication_verified':self.publication_verified}
        if self.evidence_profile is not None and self.value is not None:
            from .ny_observed_policy import verify_originals,apply_observed_profile
            try:
                if self.original_contracts is None:self.original_contracts=verify_originals(self.evidence_directory)
                context=apply_observed_profile(context,self.value,pair,self.original_contracts)
            except (ValueError,TypeError,KeyError,OverflowError,OSError):
                context.update(source_contract_verified=False,publication_verified=False)
                context['blockers'].append('NY immutable original evidence unavailable')
        return context


def configured(root,cache_path,output_path):
    mode=os.getenv('FX_NY17_MODE','off')
    if mode=='off':return None
    directory=Path(os.environ['FX_NY17_ARCHIVE_DIR'])
    if not directory.is_absolute():raise ValueError('absolute private archive directory required')
    resolved=directory.resolve()
    if resolved==Path(root).resolve() or resolved==Path(cache_path).parent.resolve() or resolved==Path(output_path).parent.resolve():raise ValueError('independent archive directory required')
    for legacy in (Path(cache_path).resolve(),Path(output_path).resolve()):
        if resolved==legacy or resolved in legacy.parents:raise ValueError('legacy destination forbidden')
    lag=os.getenv('FX_NY17_PUBLICATION_LAG_SECONDS')
    profile=os.getenv('FX_NY17_EVIDENCE_PROFILE') or None
    return NYIntegration(mode=mode,directory=directory,source_contract_verified=os.getenv('FX_NY17_SOURCE_CONTRACT_VERIFIED')=='1',publication_verified=os.getenv('FX_NY17_PUBLICATION_VERIFIED')=='1',publication_lag_seconds=int(lag) if lag is not None else None,closed_holidays=json.loads(os.getenv('FX_NY17_CLOSED_HOLIDAYS','[]')),
                         evidence_profile=profile,evidence_directory=Path(root)/'evidence/issue43-h1-originals' if profile else None)
