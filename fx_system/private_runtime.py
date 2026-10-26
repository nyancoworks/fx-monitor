"""Run trusted collection stages with their output confined to private storage.

This module never enables or schedules collection. The owner must first verify
the private data migration and explicitly enable the existing collection time.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

CODE_ROOT = Path(__file__).resolve().parents[1]
DATA_REPOSITORY = 'nyancoworks/fx-monitor-data'
CODE_REPOSITORY = 'nyancoworks/fx-monitor'
STAGES = ('restore', 'refresh', 'archive', 'annotate', 'validate', 'snapshot', 'history', 'backtest')
MAX_LOG_BYTES = 32 * 1024 * 1024


def private_root(value):
    path = Path(value)
    if not path.is_absolute() or path.is_symlink():
        raise ValueError('private checkout path required')
    root = path.resolve()
    if root.is_relative_to(CODE_ROOT) or CODE_ROOT.is_relative_to(root):
        raise ValueError('code and private data checkouts must be separate')
    if not (root / '.git').exists():
        raise ValueError('private data Git checkout required')
    return root


def git(root, *args):
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, timeout=30)
    if result.returncode:
        raise ValueError('private data Git operation failed')
    return result.stdout.decode().strip()


def verify_ready(root):
    # Fixed destination: a caller cannot route data to an arbitrary public repo.
    remote = git(root, 'remote', 'get-url', 'origin')
    if not re.fullmatch(r'(?:https://github\.com/|git@github\.com:)' +
                        re.escape(DATA_REPOSITORY) + r'(?:\.git)?', remote):
        raise ValueError('unexpected private data destination')
    marker = root / 'migration/READY.json'
    if marker.is_symlink():
        raise ValueError('migration marker must not be a symlink')
    state = json.loads(marker.read_bytes())
    if (state.get('data_repository') != DATA_REPOSITORY or
            state.get('source_bytes_verified') is not True or
            state.get('ny17_full_restore_verified') is not True or
            state.get('canonical32_verified') is not True):
        raise ValueError('private migration is not verified')
    for name in ('data/cache.json', 'data/latest.json', 'evidence/issue43-h1-originals'):
        path = root / name
        if not path.exists() or not path.resolve().is_relative_to(root):
            raise ValueError('private source data is incomplete')


def run_private(command, *, root, log, env, timeout=720):
    if log.is_symlink() or not log.resolve().is_relative_to(root):
        raise ValueError('diagnostic log must remain in private storage')
    result = subprocess.run(command, cwd=root, env=env, capture_output=True, timeout=timeout)
    output = result.stdout + b'\n' + result.stderr
    # Redact configured credentials before retaining even private diagnostic logs.
    for name, value in env.items():
        if value and len(value) >= 6 and (name.endswith('_TOKEN') or name.endswith('_KEY')):
            output = output.replace(value.encode(), b'[REDACTED]')
    if len(output) > MAX_LOG_BYTES:
        output = b'Private diagnostic output exceeded the configured limit.\n'
    log.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    log.write_bytes(output)
    log.chmod(0o600)
    return result.returncode


def prepare_optional_calendar(root, run_id, env):
    """Optional provider failure must not stop the existing FX refresh."""
    from .economic_calendar_collection import collection_enabled, prepare_calendar
    try:
        enabled = collection_enabled(root)
    except Exception:
        return env
    if not enabled:
        return env
    env = {**env, 'FX_ECONOMIC_CALENDAR_SAVED_ENABLED': 'true'}
    try:
        outcome = prepare_calendar(root, run_id=run_id)
        env['FX_ECONOMIC_CALENDAR_COLLECTION_STATUS'] = outcome['status']
    except Exception:
        env['FX_ECONOMIC_CALENDAR_COLLECTION_STATUS'] = 'unavailable'
    return env


def command(stage, root, run_id, source_commit):
    base = [sys.executable, '-m']
    archive = root / '.private-ny17'
    logs = root / '.private-run' / run_id
    commands = {
        'restore': base + ['fx_system.ny_archive_transport', 'restore', '--directory', str(archive), '--continuous'],
        'refresh': base + ['fx_system.main'],
        'archive': base + ['fx_system.ny_archive_transport', 'publish', '--directory', str(archive), '--continuous'],
        'validate': base + ['fx_system.validate_snapshot'],
        'backtest': base + ['fx_system.backtest_persistence', '--state', str(root)],
        'history': base + ['diagnostics.monitoring_result_git_store', '--repo', str(root),
                          '--snapshot', str(root/'data/latest.json'), '--source-run-id', run_id,
                          '--source-commit', source_commit, '--source-repository', CODE_REPOSITORY],
    }
    if stage == 'annotate':
        def outcome(name):
            path = logs / (name + '.status.json')
            return 'success' if path.exists() and json.loads(path.read_bytes())['returncode'] == 0 else 'failure'
        return base + ['fx_system.ny_archive_status', '--snapshot', str(root/'data/latest.json'),
                       '--restore-result', str(logs/'restore.stdout.json'),
                       '--save-result', str(logs/'archive.stdout.json'),
                       '--restore-outcome', outcome('restore'), '--save-outcome', outcome('archive')]
    return commands[stage]


def save_snapshot(root, run_id, source_commit):
    from .strength_export import build_strength_export
    from .strategy_report_export import build_strategy_report_export
    from .run_diagnostics import build_diagnostics
    snapshot_bytes = (root/'data/latest.json').read_bytes()
    snapshot = json.loads(snapshot_bytes)
    old = json.loads(git(root, 'show', 'HEAD:data/latest.json'))
    if snapshot['generated_at'] <= old.get('generated_at', 0):
        raise ValueError('snapshot did not advance; preserve existing data')
    source = {'source_repository': CODE_REPOSITORY, 'source_commit': source_commit,
              'run_id': int(run_id), 'evaluated_at': snapshot['evaluated_at']}
    for name in ('data/source.json', 'data/currency-strength.json', 'data/run-diagnostics.json',
                 'data/strategy-report.json'):
        path = root/name
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('private derived file path invalid')
    compact = build_strength_export(snapshot_bytes, source)
    strategy_report = build_strategy_report_export(snapshot_bytes, source)
    # Save a bounded diagnostic view in the same private Git push.
    # The public stage log and monitoring assessment stay unchanged. A new run
    # with no report is explicitly unavailable, never a prior run's success.
    logs = root/'.private-run'/run_id
    report = ''; returncode = None
    for path in (logs/'validate.log', logs/'validate.status.json'):
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('validation diagnostic must remain private')
    if (logs/'validate.log').exists():
        report = (logs/'validate.log').read_text(errors='replace')
    if (logs/'validate.status.json').exists():
        returncode = json.loads((logs/'validate.status.json').read_bytes()).get('returncode')
    diagnostic = build_diagnostics(snapshot_bytes, source, validation_log=report,
                                   returncode=returncode, env=os.environ)
    (root/'data/run-diagnostics.json').write_bytes(diagnostic)
    (root/'data/run-diagnostics.json').chmod(0o600)
    (root/'data/source.json').write_text(json.dumps(source, sort_keys=True) + '\n')
    (root/'data/currency-strength.json').write_text(json.dumps(compact, ensure_ascii=False, sort_keys=True,
                                                           allow_nan=False) + '\n')
    (root/'data/strategy-report.json').write_text(json.dumps(strategy_report, ensure_ascii=False,
                                                          sort_keys=True, allow_nan=False) + '\n')
    (root/'data/strategy-report.json').chmod(0o600)
    git(root, 'add', '--', 'data/cache.json', 'data/latest.json', 'data/source.json', 'data/currency-strength.json', 'data/run-diagnostics.json', 'data/strategy-report.json')
    staged = git(root, 'diff', '--cached', '--name-only').splitlines()
    if not set(staged) <= {'data/cache.json', 'data/latest.json', 'data/source.json', 'data/currency-strength.json', 'data/run-diagnostics.json', 'data/strategy-report.json'}:
        raise ValueError('unexpected staged private files')
    git(root, '-c', 'user.name=github-actions[bot]', '-c',
        'user.email=41898286+github-actions[bot]@users.noreply.github.com',
        'commit', '-m', 'Save scheduled FX observations')
    git(root, 'push', 'origin', 'HEAD:refs/heads/main')
    # Reuse the acknowledged snapshot push; long-term storage must not add a
    # second remote read just to establish which input was already saved.
    receipt = root/'.private-run'/run_id/'snapshot.receipt.json'
    if receipt.is_symlink() or not receipt.resolve().is_relative_to(root):
        raise ValueError('snapshot receipt must remain private')
    receipt.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    receipt.write_text(json.dumps({'data_commit':git(root,'rev-parse','HEAD'),
                                  'cache_blob':git(root,'rev-parse','HEAD:data/cache.json'),
                                  **source}, sort_keys=True))
    receipt.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=STAGES)
    parser.add_argument('--state', required=True)
    args = parser.parse_args()
    # The only public output is a fixed stage identifier and a status.
    try:
        run_id = os.environ['GITHUB_RUN_ID']
        commit = os.environ['GITHUB_SHA']
        if (not run_id.isdigit() or not re.fullmatch('[0-9a-f]{40}', commit) or
                os.environ.get('GITHUB_REPOSITORY') != CODE_REPOSITORY or
                os.environ.get('GITHUB_REF') != 'refs/heads/main'):
            raise ValueError('trusted code run identity required')
        root = private_root(args.state)
        verify_ready(root)
        env = {**os.environ, 'FX_DATA_ROOT': str(root), 'PYTHONPATH': str(CODE_ROOT),
               # Archive transport uses commit-tree, which needs both identities.
               # Checkout credentials do not configure Git author/committer data.
               'GIT_AUTHOR_NAME': 'github-actions[bot]',
               'GIT_AUTHOR_EMAIL': '41898286+github-actions[bot]@users.noreply.github.com',
               'GIT_COMMITTER_NAME': 'github-actions[bot]',
               'GIT_COMMITTER_EMAIL': '41898286+github-actions[bot]@users.noreply.github.com',
               'FX_NY17_MODE': 'adopt', 'FX_NY17_EVIDENCE_PROFILE': 'custom_ny17_observed_h1_v1',
               'FX_NY17_ARCHIVE_DIR': str(root/'.private-ny17'),
               'FX_NEW_PAIR_H1_BOOTSTRAP': '1',
               'FX_H1_EVIDENCE_DIR': str(root/'.private-run'/run_id/'h1-evidence')}
        logs = root/'.private-run'/run_id
        if args.stage == 'refresh':
            env = prepare_optional_calendar(root, run_id, env)
        if args.stage == 'snapshot':
            save_snapshot(root, run_id, commit)
            rc = 0
        else:
            rc = run_private(command(args.stage, root, run_id, commit), root=root,
                             log=logs/(args.stage+'.log'), env=env)
        logs.mkdir(parents=True, exist_ok=True, mode=0o700)
        (logs/(args.stage+'.status.json')).write_text(json.dumps({'returncode': rc}))
        if args.stage == 'backtest' and rc != 0:
            from .backtest_failure import safe_failure_line
            print(safe_failure_line((logs/'backtest.log').read_text(errors='replace')))
        if args.stage == 'backtest' and rc == 0:
            # Fixed, price-free operational counters are reviewable after a
            # runner is discarded. Full inputs/results remain private.
            summary = json.loads((logs/'backtest-result.json').read_bytes())['result']
            counters = {key:summary[key] for key in ('requests','used_bytes','added')}
            if any(type(value) is not int or value < 0 for value in counters.values()):
                raise ValueError('invalid backtest counters')
            if counters['requests'] > 64 or counters['used_bytes'] > 1024**3:
                raise ValueError('backtest storage exceeded approved budget')
            print('FX_BACKTEST_STORAGE ' + json.dumps(counters, sort_keys=True))
        if args.stage in ('restore', 'archive') and rc == 0:
            # Commands emit a single JSON object; stderr must not be mixed into it.
            text = (logs/(args.stage+'.log')).read_text().strip()
            value = json.loads(text)
            expected = {'restored'} if args.stage == 'restore' else {'persisted', 'unchanged'}
            if value.get('status') not in expected:
                raise ValueError('archive persistence not verified')
            (logs/(args.stage+'.stdout.json')).write_text(json.dumps(value))
    except Exception:
        print('FX_STAGE ' + args.stage + ' failed; private diagnostics retained when available')
        return 1
    print('FX_STAGE ' + args.stage + (' success' if rc == 0 else ' failed'))
    return 0 if rc == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
