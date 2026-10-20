"""Approved isolated custom-NY17 policy; production activation needs approval.

This profile trusts the documented UTC intraday API contract and immutable
originals, and requires observed complete receipts. It does not attest native
daily equivalence, broker prices, provider NY sessions, or a publication SLA.
"""
import hashlib
import json
import zipfile
import datetime as dt
from pathlib import Path
from diagnostics.issue43_ny_incremental import PAIRS, digest
from diagnostics.issue43_ny_incremental_e2e import ZIP_HASHES
from .monitor_pairs import PINNED_ORIGINAL_PAIRS

PROFILE="custom_ny17_observed_h1_v1"
REFERENCE={"url":"https://twelvedata.com/docs","reviewed_on":"2026-10-12",
           "scope":"documented UTC timezone parameter for intraday requests"}


def verify_originals(directory):
    contracts={}
    for filename,expected in ZIP_HASHES.items():
        path=Path(directory)/filename
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise ValueError("immutable source ZIP hash mismatch")
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                raw=json.loads(archive.read(name))
                pair=raw.get("pair",raw.get("symbol","")).replace("/","")
                if (pair not in PAIRS or pair in contracts or
                    raw.get("provider")!="Twelve Data" or raw.get("requested_timezone")!="UTC" or
                    raw.get("schema") not in ("issue43_h1_observation_v1","issue43_raw_h1_v1")):
                    raise ValueError("unrecognized original source contract")
                rows=[{k:r.get(k) for k in ("timestamp","open","high","low","close")} for r in raw["rows"]]
                contracts[pair]={"source_sha256":digest(rows),
                                 "bars":{str(r["timestamp"]):r for r in rows}}
    if set(contracts)!=set(PINNED_ORIGINAL_PAIRS):raise ValueError("original universe incomplete")
    # New pair evidence is separately pinned; never rewrite the original 13 ZIPs.
    # Malformed additional evidence isolates only pairs without a pinned contract.
    extra = Path(directory)/'additional-originals.json'
    if extra.exists():
        try:
            manifest=json.loads(extra.read_text())
            if manifest.get('schema')!=1 or not isinstance(manifest.get('originals'),list):
                raise ValueError('invalid additional originals manifest')
            seen=set()
            for item in manifest['originals']:
                pair=item['pair'];filename=item['file']
                if (pair in contracts or pair in seen or pair not in PAIRS or
                    Path(filename).name!=filename or filename in ('.','..')):
                    raise ValueError('invalid additional original identity')
                seen.add(pair)
                content=(Path(directory)/filename).read_bytes()
                if hashlib.sha256(content).hexdigest()!=item['sha256']:
                    raise ValueError('additional original hash mismatch')
                raw=json.loads(content)
                received=dt.datetime.fromisoformat(raw['received_as_of_utc'])
                if (raw.get('schema')!='custom_ny17_observed_h1_original_v1' or
                    raw.get('pair')!=pair or raw.get('provider')!='Twelve Data' or
                    raw.get('requested_timezone')!='UTC' or received.utcoffset()!=dt.timedelta(0)):
                    raise ValueError('additional original source contract mismatch')
                rows=raw['rows']
                normalized=sorted(({k:r[k] for k in ('timestamp','open','high','low','close')} for r in rows),key=lambda r:r['timestamp'])
                if rows!=normalized or len({r['timestamp'] for r in rows})!=len(rows):
                    raise ValueError('additional original requires unique normalized chronological rows')
                from diagnostics.issue43_ny_incremental import empty_archive,ingest,validate_state
                state=ingest(empty_archive(),pair,raw['rows'],as_of=received,
                             source_digest=digest(raw['rows']))
                validate_state(state)
                if not state['events']:raise ValueError('empty additional original')
                contracts[pair]={'source_sha256':digest(raw['rows']),
                    'bars':state['pairs'][pair], 'received_as_of_utc':received.isoformat()}
        except (ValueError,TypeError,KeyError,OSError,AttributeError):
            for pair in set(PAIRS)-set(PINNED_ORIGINAL_PAIRS):contracts.pop(pair,None)
    return contracts


def supported_source(checkpoint,pair,contracts):
    original=contracts.get(pair)
    if original is None:return False
    events=[e for e in checkpoint["archive"]["events"] if e["pair"]==pair]
    if not events:return False
    first=events[0]
    return (first["source_sha256"]==original["source_sha256"] and
            ('received_as_of_utc' not in original or
             first['received_as_of_utc']==original['received_as_of_utc']) and
            {str(c["timestamp"]):c["new"] for c in first["changes"]}==original["bars"] and
            all(c["old"] is None for c in first["changes"]))


def apply_observed_profile(context,checkpoint,pair,contracts):
    """Use explicit policy evidence, not the old environment verification flags."""
    result=dict(context)
    availability=context.get("observed_availability") or {}
    study=context.get("study") or {}
    # Generic archive tooling can retain explicitly reviewed revisions. This
    # profile has no approval to adopt them: immutable genesis plus append-only
    # observations is its narrower source contract, independently per pair.
    revised=any(c.get("old") is not None
                for e in checkpoint["archive"]["events"] if e["pair"]==pair
                for c in e["changes"])
    result.update({"evidence_profile":PROFILE,"utc_contract_reference":REFERENCE,
                   "source_contract_verified":supported_source(checkpoint,pair,contracts) and not revised,
                   "provider_session_verified":False,
                   "publication_verified":availability.get("observed_available") is True
                       and study.get("calendar_ready") is True,
                   "provider_publication_sla_verified":False})
    if revised:
        result["publication_verified"]=False
        result["blockers"]=[*context["blockers"],"NY observed profile rejects revised H1 history"]
    if not result["source_contract_verified"]:
        if not revised:
            result["blockers"]=[*context["blockers"],"immutable UTC H1 original does not match archive genesis"]
    return result
