"""Persist only canonical, already committed observations; never collect prices."""
import argparse
import hashlib
import json
import os
import re

from .backtest_cache_input import batches_from_cache, daily_batches_from_snapshot
from .backtest_release_store import GitHubStorage, ReleaseWarehouse
from .private_runtime import git, private_root, verify_ready, CODE_REPOSITORY


def saved_input(root, run_id, source_commit):
    head=git(root,'rev-parse','HEAD')
    raw=(root/'data/cache.json').read_bytes()
    sha=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    if sha!=git(root,'rev-parse','HEAD:data/cache.json'):
        raise ValueError('cache is not the saved Git input')
    source_raw=(root/'data/source.json').read_bytes()
    source_sha=hashlib.sha1(b'blob '+str(len(source_raw)).encode()+b'\0'+source_raw).hexdigest()
    if source_sha!=git(root,'rev-parse','HEAD:data/source.json'):
        raise ValueError('source is not the saved Git input')
    source=json.loads(source_raw)
    if (source.get('run_id')!=int(run_id) or source.get('source_commit')!=source_commit or
            source.get('source_repository')!=CODE_REPOSITORY):
        raise ValueError('saved source does not match this collection')
    # Written only after the existing snapshot push was acknowledged. Avoid a
    # new remote/Git request outside the storage request counter.
    receipt=json.loads((root/'.private-run'/run_id/'snapshot.receipt.json').read_bytes())
    if receipt!={**source,'data_commit':head,'cache_blob':sha}:
        raise ValueError('saved private head is not remotely confirmed')
    batches,quality=batches_from_cache(raw,expected_git_blob=sha,evaluated_at=source['evaluated_at'])
    snapshot_raw=(root/'data/latest.json').read_bytes()
    snapshot_sha=hashlib.sha1(b'blob '+str(len(snapshot_raw)).encode()+b'\0'+snapshot_raw).hexdigest()
    if snapshot_sha!=git(root,'rev-parse','HEAD:data/latest.json'):
        raise ValueError('snapshot is not saved Git input')
    daily,daily_quality=daily_batches_from_snapshot(snapshot_raw,expected_git_blob=snapshot_sha,
                                                   evaluated_at=source['evaluated_at'])
    return batches+daily,{'intraday':quality,'daily':daily_quality},{
        **source,'data_commit':head,'cache_blob':sha,'snapshot_blob':snapshot_sha}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state',required=True)
    args=parser.parse_args()
    root=private_root(args.state);verify_ready(root)
    run=os.environ['GITHUB_RUN_ID'];commit=os.environ['GITHUB_SHA']
    if (not run.isdigit() or not re.fullmatch('[0-9a-f]{40}',commit) or
            os.environ.get('GITHUB_REPOSITORY')!=CODE_REPOSITORY or
            os.environ.get('GITHUB_REF')!='refs/heads/main'):
        raise ValueError('trusted collection identity required')
    batches,quality,source=saved_input(root,run,commit)
    # Unknown provenance is retained as unknown in the private diagnostic. No
    # guesses or market fetches are introduced to fill rejected observations.
    api=GitHubStorage(os.environ['FX_DATA_REPO_TOKEN'])
    result=ReleaseWarehouse(api).cycle(batches,now=source['evaluated_at'],source=source)
    log=root/'.private-run'/run/'backtest-result.json'
    if log.is_symlink() or not log.resolve().is_relative_to(root):
        raise ValueError('storage diagnostics must remain private')
    log.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    log.write_text(json.dumps({'result':result,'quality':quality,'source':source},sort_keys=True))
    log.chmod(0o600)
    # This stdout is captured by private_runtime, never emitted in public logs.
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':
    main()
