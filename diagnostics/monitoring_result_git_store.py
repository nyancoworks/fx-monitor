"""Canonical monitoring history publisher; no optional research generation."""
import json
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile
import zlib
from .monitoring_result_history import append_generation, restore_generation, latest_restorable

BRANCH = 'monitoring-result-state'
REF = 'refs/heads/' + BRANCH
FILES = {'history.json', 'provenance.json'}
MAX_BYTES = 13 * 1024 * 1024


def _git(repo, *args, stdin=None, optional=False, env=None):
    # Never surface stderr, credentials, remote URLs or command arguments.
    try:
        result = subprocess.run(['git','-C',str(repo),*args], input=stdin,
                                capture_output=True, timeout=30, env=env)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError('history Git operation unavailable') from error
    if result.returncode and not optional:
        raise ValueError('history Git operation failed or concurrent update rejected')
    if len(result.stdout) > MAX_BYTES:
        raise ValueError('history Git output exceeds limit')
    return result.stdout.decode('utf-8').strip()


def _bytes(value):
    return json.dumps(value,sort_keys=True,separators=(',', ':'),allow_nan=False).encode()


def read_remote_history(repo):
    listing = _git(repo,'ls-remote','--heads','origin',REF)
    if not listing:
        return {'head':None,'history':[],'provenance':{}}
    lines = listing.splitlines()
    if len(lines)!=1 or lines[0].split()[1]!=REF:
        raise ValueError('unexpected history ref')
    _git(repo,'fetch','--no-tags','origin',REF)
    head = _git(repo,'rev-parse','FETCH_HEAD')
    paths = set(_git(repo,'ls-tree','--name-only',head).splitlines())
    if paths not in (FILES, FILES | {'followup'}):
        raise ValueError('unexpected history tree; preserve it for review')
    if 'followup' in paths and _git(repo, 'cat-file', '-t', head+':followup') != 'tree':
        raise ValueError('unexpected followup object; preserve it for review')
    history = json.loads(_git(repo,'show',head+':history.json'))
    provenance = json.loads(_git(repo,'show',head+':provenance.json'))
    if not isinstance(history,list) or len(history)>3 or not isinstance(provenance,dict):
        raise ValueError('invalid history state')
    clocks = [restore_generation(g)['evaluated_at'] for g in history]
    if clocks != sorted(set(clocks)) or set(provenance)!={str(t) for t in clocks}:
        raise ValueError('history provenance mismatch')
    for source in provenance.values():
        if (not isinstance(source,dict) or type(source.get('run_id')) is not int or source['run_id']<=0
                or not isinstance(source.get('source_commit'),str)
                or not re.fullmatch('[0-9a-f]{40}',source['source_commit'])):
            raise ValueError('invalid history source identity')
    return {'head':head,'history':history,'provenance':provenance}


def publish_results(repo, rows, *, evaluated_at, source_run_id, source_commit, allow_create=False, snapshot=None, input_identity=None, source_repository=None):
    """Publish via a parented, non-forced push; conflicts stop without retries."""
    if type(source_run_id) is not int or source_run_id<=0 or not isinstance(source_commit,str) or not re.fullmatch('[0-9a-f]{40}',source_commit):
        raise ValueError('source run identity required')
    if snapshot is not None:
        if snapshot.get('evaluated_at') != evaluated_at or snapshot.get('scheduled_outlook', {}).get('rows') != rows:
            raise ValueError('snapshot and result rows disagree')
    identity = None
    if input_identity is not None:
        if (not isinstance(input_identity, dict)
                or not isinstance(input_identity.get('sha256'), str)
                or re.fullmatch('[0-9a-f]{64}', input_identity['sha256']) is None
                or not isinstance(input_identity.get('git_blob_sha'), str)
                or re.fullmatch('[0-9a-f]{40}', input_identity['git_blob_sha']) is None):
            raise ValueError('invalid snapshot input identity')
        identity = {k: input_identity[k] for k in ('sha256', 'git_blob_sha')}
    previous = read_remote_history(repo)
    if previous['head'] is None and not allow_create:
        raise ValueError('history ref creation requires explicit opt-in')
    history = append_generation(previous['history'],rows,evaluated_at=evaluated_at)
    source={'run_id':source_run_id,'source_commit':source_commit}
    if source_repository is not None:
        if not isinstance(source_repository, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', source_repository):
            raise ValueError('invalid source repository')
        source['source_repository']=source_repository
    if identity is not None:
        source['snapshot_identity'] = identity
    old_source=previous['provenance'].get(str(evaluated_at))
    if old_source is not None and old_source!=source:
        raise ValueError('conflicting source run for evaluation')
    provenance={str(g['evaluated_at']):previous['provenance'].get(str(g['evaluated_at']),source) for g in history}
    if history==previous['history'] and provenance==previous['provenance']:
        return {'status':'unchanged','head':previous['head'],'generations':len(history)}
    blobs={name:_git(repo,'hash-object','-w','--stdin',stdin=_bytes(value))
           for name,value in [('history.json',history),('provenance.json',provenance)]}
    # Keep existing immutable history-tree objects; only update canonical history/provenance.
    with tempfile.TemporaryDirectory() as folder:
        env = {**os.environ, 'GIT_INDEX_FILE': str(Path(folder)/'index')}
        if previous['head']:
            _git(repo, 'read-tree', previous['head'], env=env)
        else:
            _git(repo, 'read-tree', '--empty', env=env)
        for path, blob in blobs.items():
            _git(repo, 'update-index', '--add', '--cacheinfo', f'100644,{blob},{path}', env=env)
        tree = _git(repo, 'write-tree', env=env)
    parent=['-p',previous['head']] if previous['head'] else []
    commit=_git(repo,'-c','user.name=github-actions[bot]',
                '-c','user.email=41898286+github-actions[bot]@users.noreply.github.com',
                'commit-tree',tree,*parent,stdin=b'Persist monitoring result references\n')
    # No force, reset, checkout, history rewrite, remote branch deletion or retry.
    _git(repo,'push','origin',commit+':'+REF)
    return {'status':'persisted','head':commit,'generations':len(history),
            'saved_evaluated_at':latest_restorable(history)['saved_evaluated_at'],
            'snapshot_identity_recorded': identity is not None}


def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--repo',required=True)
    parser.add_argument('--snapshot',required=True)
    parser.add_argument('--source-run-id',required=True,type=int)
    parser.add_argument('--source-commit',required=True)
    parser.add_argument('--source-repository')
    parser.add_argument('--allow-create',action='store_true')
    args=parser.parse_args()
    try:
        path=Path(args.snapshot)
        if path.stat().st_size>32*1024*1024: raise ValueError('snapshot too large')
        raw_snapshot=path.read_bytes()
        snapshot=json.loads(raw_snapshot)
        from fx_system.validate_strategy_snapshot import validate_strategy_snapshot
        if validate_strategy_snapshot(snapshot):
            raise ValueError('scheduled strategy snapshot invalid; history not published')
        outlook=snapshot['scheduled_outlook']
        clock=snapshot.get('evaluated_at')
        if type(clock) is not int or outlook.get('evaluated_at')!=clock:
            raise ValueError('snapshot clocks do not match')
        blob = _git(args.repo, 'hash-object', '--stdin', stdin=raw_snapshot)
        saved_blob = _git(args.repo, 'rev-parse', 'HEAD:data/latest.json', optional=True)
        identity = {'sha256': hashlib.sha256(raw_snapshot).hexdigest(), 'git_blob_sha': blob,
                    'snapshot_commit': _git(args.repo, 'rev-parse', 'HEAD') if blob == saved_blob else None,
                    'snapshot_commit_matches_input': blob == saved_blob}
        result=publish_results(args.repo,outlook['rows'],evaluated_at=clock,
            source_run_id=args.source_run_id,source_commit=args.source_commit,allow_create=args.allow_create,
            snapshot=snapshot,input_identity=identity,source_repository=args.source_repository)
    except (ValueError,KeyError,TypeError,OSError,zlib.error) as error:
        print(json.dumps({'status':'failed','error_type':type(error).__name__,'entry_permission':False}))
        raise SystemExit(1)
    print(json.dumps({**result,'entry_permission':False}))


if __name__=='__main__':main()
