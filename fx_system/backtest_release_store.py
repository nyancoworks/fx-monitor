"""Bounded private Release storage for derived backtest observations only.

One writer: the existing collection workflow concurrency group. Immutable
bundles and two verified index copies precede pointer publication and cleanup.
No original Git files, tags, releases or NY17 archives are deleted.
"""
import base64
import copy
from datetime import datetime, timezone
import gzip
import hashlib
import json
import re
from urllib.parse import urlparse, quote
import zlib

from .backtest_partition import canonical, pack, unpack, partition_key
from .archive_inventory import summarize

REPOSITORY = 'nyancoworks/fx-monitor-data'
TAG = 'fx-backtest-derived-v1'
MARKER = 'fx-derived-release-v1'
POLICY = {'m5': 3, 'h1': 5, 'd1': 10}
QUOTA = 1024**3
LIMIT = 64*1024**2
MAX_ASSETS = 900
NAME = re.compile(r'fxbt-(?:bundle|index|backup)-[0-9a-f]{64}\.(?:gz|json)\Z')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def envelope(payload):
    return canonical({'schema': MARKER, 'payload': payload, 'sha256': digest(canonical(payload))})


def open_envelope(raw):
    obj = json.loads(raw)
    if obj.get('schema') != MARKER or digest(canonical(obj['payload'])) != obj.get('sha256'):
        raise ValueError('invalid derived index')
    return obj['payload']


def bundle_key(tf, month):
    partition_key('bundle', 'all', tf, month)
    return tf+'/'+month


def decode_bundle(raw, key, now):
    decoder = zlib.decompressobj(31)
    plain = decoder.decompress(raw, LIMIT+1)
    if len(plain)>LIMIT or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError('invalid bundle compression')
    obj = json.loads(plain)
    if obj.get('schema') != 'fx_backtest_bundle_v1' or obj.get('key') != key or canonical(obj) != plain:
        raise ValueError('invalid bundle identity')
    result = {}
    for partition, entry in obj['partitions'].items():
        provider, pair, tf, month = partition.split('/')
        partition_key(provider, pair, tf, month)
        if bundle_key(tf, month) != key:
            raise ValueError('cross-month bundle')
        rows = unpack(base64.b64decode(entry['gzip'], validate=True), entry['sha256'],
                      provider=provider, pair=pair, tf=tf, month=month, now=now)
        if len(rows) != entry['count']:
            raise ValueError('partition count mismatch')
        result[partition] = rows
    return result


def encode_bundle(key, partitions, now):
    entries = {}
    for partition, rows in sorted(partitions.items()):
        provider, pair, tf, month = partition.split('/')
        if bundle_key(tf, month) != key:
            raise ValueError('bundle mismatch')
        raw, info = pack(provider, pair, tf, month, rows, now)
        entries[partition] = {**info, 'gzip':base64.b64encode(raw).decode('ascii')}
    plain = canonical({'schema':'fx_backtest_bundle_v1', 'key':key, 'partitions':entries})
    if len(plain)>LIMIT:
        raise ValueError('bundle exceeds bounded decoder')
    return gzip.compress(plain, compresslevel=6, mtime=0)


class GitHubStorage:
    """No retries/implicit redirects; count every HTTP request including redirects."""
    def __init__(self, token, *, session=None):
        if not token:
            raise ValueError('private writer credential required')
        if session is None:
            import requests
            session = requests.Session()
        self.session, self.token = session, token
        self.calls, self.remaining = 0, None
        self.last_status = 0

    def reserve(self, count):
        if self.calls+count>64 or (self.remaining is not None and self.remaining-count<=200):
            raise ValueError('storage request budget exhausted')

    def request(self, method, path, *, body=None, raw=None, binary=False, missing=False):
        url = 'https://api.github.com/repos/'+REPOSITORY+path
        if method == 'UPLOAD':
            method = 'POST'
            url = 'https://uploads.github.com/repos/'+REPOSITORY+path
        headers = {'Authorization':'Bearer '+self.token, 'X-GitHub-Api-Version':'2026-03-10',
                   'Accept':'application/octet-stream' if binary else 'application/vnd.github+json'}
        if raw is not None:
            headers['Content-Type'] = 'application/octet-stream'
        for hop in range(2):
            self.reserve(1)
            self.calls += 1
            self.last_status = 0
            response = self.session.request(method, url, headers=headers, json=body, data=raw,
                                            timeout=(10, 30), allow_redirects=False, stream=True)
            self.last_status = response.status_code
            try:
                rate = response.headers.get('X-RateLimit-Remaining')
                if rate is not None:
                    self.remaining = int(rate)
                if response.status_code in (301,302,303,307,308):
                    location = response.headers.get('Location','')
                    parsed = urlparse(location)
                    if (not binary or method!='GET' or hop or parsed.scheme!='https' or
                            parsed.hostname not in ('release-assets.githubusercontent.com','objects.githubusercontent.com') or
                            parsed.username or parsed.password or parsed.port not in (None,443)):
                        raise ValueError('unexpected storage redirect')
                    url, headers = location, {'Accept':'application/octet-stream'}
                    continue
                if response.status_code==404 and missing:
                    return None
                if response.status_code not in (200,201,204):
                    raise ValueError('storage HTTP operation failed')
                chunks=[]; size=0
                for chunk in response.iter_content(65536):
                    size+=len(chunk)
                    if size>LIMIT:
                        raise ValueError('storage response exceeds limit')
                    chunks.append(chunk)
                content=b''.join(chunks)
                if response.status_code==204:
                    return None
                return content if binary else json.loads(content)
            finally:
                response.close()
        raise ValueError('storage redirect limit')


class ReleaseWarehouse:
    def __init__(self, api, *, quota=QUOTA):
        if type(quota) is not int or not 0<quota<=QUOTA:
            raise ValueError('invalid storage quota')
        self.api, self.quota = api, quota
        self.assets = {}

    def _inventory(self, release_id):
        assets=[]
        for page in range(1,11):
            part=self.api.request('GET',f'/releases/{release_id}/assets?per_page=100&page={page}')
            if not isinstance(part,list):
                raise ValueError('invalid asset listing')
            assets.extend(part)
            if len(assets)>MAX_ASSETS:
                raise ValueError('asset inventory exceeds budget')
            if len(part)<100:
                break
        self.assets={}
        names=set()
        for asset in assets:
            if (type(asset.get('id')) is not int or type(asset.get('size')) is not int or asset['size']<0 or
                    asset.get('state')!='uploaded' or not NAME.fullmatch(asset.get('name','')) or
                    not re.fullmatch(r'sha256:[0-9a-f]{64}',asset.get('digest','')) or
                    asset['name'] in names or asset['id'] in self.assets):
                raise ValueError('unexpected asset in dedicated derived release')
            if asset['name'].split('-')[-1].split('.')[0]!=asset['digest'][7:]:
                raise ValueError('asset content address differs')
            names.add(asset['name']); self.assets[asset['id']]=asset
        if sum(a['size'] for a in assets)>self.quota:
            raise ValueError('existing derived storage exceeds budget')

    def _check(self, ref):
        asset=self.assets[ref['id']]
        if (set(ref)!={'id','name','size','sha256'} or
                (asset['name'],asset['size'],asset['digest']) !=
                (ref['name'],ref['size'],'sha256:'+ref['sha256'])):
            raise ValueError('asset reference differs from remote inventory')
        return asset

    def _get(self, ref):
        self._check(ref)
        raw=self.api.request('GET',f"/releases/assets/{ref['id']}",binary=True)
        if len(raw)!=ref['size'] or digest(raw)!=ref['sha256']:
            raise ValueError('asset readback differs')
        return raw

    def _put(self, release_id, kind, raw):
        sha=digest(raw);name=f'fxbt-{kind}-{sha}.'+('gz' if kind=='bundle' else 'json')
        found=next((a for a in self.assets.values() if a['name']==name),None)
        if found is None:
            if (sum(a['size'] for a in self.assets.values())+len(raw)>self.quota or
                    len(self.assets)>=MAX_ASSETS or len(raw)>LIMIT):
                raise ValueError('derived storage capacity exhausted')
            found=self.api.request('UPLOAD',f'/releases/{release_id}/assets?name='+quote(name),raw=raw)
            if (found.get('name')!=name or found.get('state')!='uploaded' or
                    found.get('digest')!='sha256:'+sha or found.get('size')!=len(raw)):
                raise ValueError('upload acknowledgement differs')
            self.assets[found['id']]=found
        ref={'id':found['id'],'name':name,'size':len(raw),'sha256':sha}
        if self._get(ref)!=raw:
            raise ValueError('upload not recoverable')
        return ref

    def _validate_state(self, state):
        if (state.get('policy')!=POLICY or type(state.get('generation')) is not int or
                state['generation']<0 or not isinstance(state.get('pins'),dict)):
            raise ValueError('invalid archive state')
        for key,ref in state['bundles'].items():
            tf,month=key.split('/');bundle_key(tf,month);self._check(ref)
            if not ref['name'].startswith('fxbt-bundle-'):
                raise ValueError('invalid bundle reference')
        inventory=state.get('inventory')
        if inventory is not None:
            if inventory.get('schema')!='archive_inventory_v1' or not isinstance(inventory.get('bundles'),dict):
                raise ValueError('invalid inventory')
            for key,item in inventory['bundles'].items():
                if key not in state['bundles'] or item.get('bundle_sha256')!=state['bundles'][key]['sha256']:
                    raise ValueError('inventory bundle identity differs')
            if inventory.get('unknown_bundle_keys')!=sorted(set(state['bundles'])-set(inventory['bundles'])):
                raise ValueError('inventory coverage differs')
        for name,pins in state['pins'].items():
            if not re.fullmatch('[A-Za-z0-9_-]{1,64}',name):
                raise ValueError('invalid research pin')
            for key,ref in pins.items():
                tf,month=key.split('/');bundle_key(tf,month);self._check(ref)
                if not ref['name'].startswith('fxbt-bundle-'):
                    raise ValueError('invalid pinned bundle')

    def cycle(self, batches, *, now, source):
        if type(now) is not int or now<0 or not isinstance(source,dict) or not source:
            raise ValueError('immutable saved input reference required')
        repo=self.api.request('GET','')
        if repo.get('full_name')!=REPOSITORY or repo.get('private') is not True:
            raise ValueError('private destination required')
        release=self.api.request('GET','/releases/tags/'+TAG,missing=True)
        empty={'generation':0,'policy':POLICY,'bundles':{},'pins':{},'last_source':None}
        if release is None:
            # Existing observations are used; this creates no collection or Actions.
            release=self.api.request('POST','/releases',body={'tag_name':TAG,'target_commitish':'main',
                'name':'Derived backtest storage','body':envelope({'state':empty,'uninitialized':True}).decode(),
                'draft':False,'prerelease':True,'make_latest':'false'})
        if (release.get('tag_name')!=TAG or release.get('draft') or release.get('immutable') or
                type(release.get('id')) is not int):
            raise ValueError('unexpected derived release')
        rid=release['id'];prior_body=release['body']
        pointer=open_envelope(prior_body)
        self._inventory(rid)
        if pointer.get('uninitialized') is True:
            if pointer!={'state':empty,'uninitialized':True}:
                raise ValueError('invalid initial pointer')
            old=empty
        else:
            if (set(pointer) not in ({'index','backup'},{'index','backup','inventory'}) or pointer['index']['id']==pointer['backup']['id'] or
                    not pointer['index']['name'].startswith('fxbt-index-') or
                    not pointer['backup']['name'].startswith('fxbt-backup-')):
                raise ValueError('independent index copies required')
            # Both copies must restore identically before writes or cleanup.
            old=open_envelope(self._get(pointer['index']))
            if open_envelope(self._get(pointer['backup']))!=old:
                raise ValueError('backup differs; refuse writes/deletion')
            self._validate_state(old)
            if 'inventory' in pointer and pointer['inventory']!=old.get('inventory'):
                raise ValueError('inventory differs from verified index')
        new=copy.deepcopy(old); grouped={}; seen=set()
        current=datetime.fromtimestamp(now,timezone.utc)
        def expired(key):
            tf,month=key.split('/')
            return month<f'{current.year-POLICY[tf]:04d}-{current.month:02d}'
        for batch in batches:
            tf,month=batch['tf'],batch['month']
            key=bundle_key(tf,month)
            partition=partition_key(batch['provider'],batch['pair'],tf,month).as_posix()
            if partition in seen:
                raise ValueError('duplicate incoming partition')
            seen.add(partition)
            if not expired(key):
                grouped.setdefault(key,[]).append((partition,batch['rows']))
        # Hold enough calls for 302 downloads, two indices, pointer commit and GC.
        self.api.reserve(2*len(grouped)+1)
        objects={};added=0;conflicts=[];observed_inventory={}
        for key,items in sorted(grouped.items()):
            previous=old['bundles'].get(key)
            partitions=decode_bundle(self._get(previous),key,now) if previous else {}
            changed=0
            for partition,incoming in items:
                provider,pair,tf,month=partition.split('/')
                rows={r['timestamp']:r for r in partitions.get(partition,[])}
                # Existing codec validates every input before any upload.
                pack(provider,pair,tf,month,incoming,now)
                for row in incoming:
                    prior=rows.get(row['timestamp'])
                    if prior is not None:
                        if ({k:v for k,v in prior.items() if k not in ('captured_at','capture_ref')} !=
                                {k:v for k,v in row.items() if k not in ('captured_at','capture_ref')} or
                                row['captured_at']<prior['captured_at']):
                            # Preserve the first archived observation byte-for-byte.
                            # The alternate remains in the acknowledged immutable
                            # input commit; retain identities and digests for audit.
                            conflicts.append({'partition':partition,'timestamp':row['timestamp'],
                                'archived_sha256':digest(canonical(prior)),
                                'incoming_sha256':digest(canonical(row))})
                    else:
                        rows[row['timestamp']]={**row,'capture_ref':copy.deepcopy(source)};changed+=1
                partitions[partition]=list(rows.values())
            if changed:
                objects[key]=encode_bundle(key,partitions,now);added+=changed
            observed_inventory[key]=summarize(partitions)
        for key in list(new['bundles']):
            if expired(key):
                del new['bundles'][key]
        if conflicts:
            new['last_revision_observation']={'source':copy.deepcopy(source),
                'policy':'preserve_first_archived_use_saved_input_for_alternate',
                'conflicts':conflicts}
        if not objects and new==old:
            return {'status':'unchanged','added':0,'requests':self.api.calls,
                    'used_bytes':sum(a['size'] for a in self.assets.values())}
        # Publish only during an already-required storage generation. Never add
        # requests for an otherwise unchanged cycle, or download sealed months.
        inventory=copy.deepcopy(old.get('inventory',{}).get('bundles',{}))
        inventory.update(observed_inventory)
        inventory={k:v for k,v in inventory.items() if k in new['bundles'] or k in objects}
        new['inventory']={'schema':'archive_inventory_v1','bundles':inventory,
            'unknown_bundle_keys':sorted(set(new['bundles'])-set(inventory)),
            'source':copy.deepcopy(source),'cross_month_gaps_checked':False}
        new['generation']+=1;new['last_source']=source
        # Capacity before any upload includes both full new index copies and a
        # conservative allowance for remote IDs/references, all old assets remain.
        peak=sum(len(b) for b in objects.values())+2*(len(envelope(new))+len(objects)*512+4096)
        if sum(a['size'] for a in self.assets.values())+peak>self.quota:
            raise ValueError('insufficient room for recoverable generation')
        self.api.reserve(3*len(objects)+24)
        for key,raw in objects.items():
            ref=self._put(rid,'bundle',raw)
            # _put has read back these exact bytes and verified their digest.
            decode_bundle(raw,key,now)
            new['bundles'][key]=ref
        for key,item in new['inventory']['bundles'].items():
            item['bundle_sha256']=new['bundles'][key]['sha256']
        index=envelope(new)
        index_ref=self._put(rid,'index',index)
        backup_ref=self._put(rid,'backup',index)
        self._validate_state(new)
        fresh=self.api.request('GET',f'/releases/{rid}')
        if fresh['body']!=prior_body:
            raise ValueError('archive writer changed; preserve unreferenced uploads')
        pointer_body={'index':index_ref,'backup':backup_ref}
        if len(canonical(new['inventory']))<=60000:
            pointer_body['inventory']=new['inventory']
        body=envelope(pointer_body).decode()
        self.api.request('PATCH',f'/releases/{rid}',body={'body':body})
        saved=self.api.request('GET',f'/releases/{rid}')
        if saved['body']!=body:
            raise ValueError('published pointer not verified')
        if open_envelope(self._get(backup_ref))!=new or open_envelope(self._get(index_ref))!=new:
            raise ValueError('published index restoration failed')
        # Remote sha256 inventory authenticates untouched sealed bundles. Their
        # full contents are read/validated on use; not downloaded every cycle.
        self._inventory(rid);self._validate_state(new)
        keep={index_ref['id'],backup_ref['id']}|{r['id'] for r in new['bundles'].values()}
        keep|={r['id'] for pins in new['pins'].values() for r in pins.values()}
        deleted=0;removed=set()
        for aid,asset in sorted(self.assets.items()):
            if aid not in keep:
                # Deletion is restricted to content-addressed assets of this
                # dedicated release. A leftover is safe if budget is exhausted.
                try:
                    self.api.reserve(1)
                except ValueError:
                    break
                self.api.request('DELETE',f'/releases/assets/{aid}')
                deleted+=1;removed.add(aid)
        return {'status':'persisted','added':added,'generation':new['generation'],
                'requests':self.api.calls,'deleted_derived_assets':deleted,
                'used_bytes':sum(a['size'] for aid,a in self.assets.items() if aid not in removed),
                'retained_bundles':len(new['bundles']),'backup_verified':True,'revision_conflicts':len(conflicts)}
