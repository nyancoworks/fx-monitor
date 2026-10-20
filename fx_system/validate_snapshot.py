"""Fail a refresh run when the snapshot cannot support a live FX decision.

Validation runs after saving diagnostics, so failed market-data refreshes remain visible.
"""
from __future__ import annotations
import json
import pathlib
import sys
import time
from .core import PAIRS
from .data_quality import evaluate_pair
from .storage_paths import storage_root

ROOT=pathlib.Path(__file__).resolve().parents[1]

def validate(snapshot, now=None, *, ny=None, require_strategies=False):
    now=int(time.time()) if now is None else int(now)
    failures=[]
    if require_strategies or 'scheduled_outlook' in snapshot:
        from .validate_strategy_snapshot import validate_strategy_snapshot
        failures.extend(validate_strategy_snapshot(snapshot))
    transport=snapshot.get('ny17_transport')
    if transport is not None and (transport.get('restore_ok') is not True or transport.get('save_ok') is not True):
        failures.append('NY archive persistence evidence unverified')
    if now-int(snapshot.get("generated_at",0))>600:
        failures.append("snapshot older than 10 minutes")
    if int(snapshot.get("generated_at",0))>now:
        failures.append("snapshot generation time is in the future")
    for pair in PAIRS:
        name=pair.replace("/","")
        data=snapshot.get("pairs",{}).get(name,{})
        quality=snapshot.get("quality",{}).get(name,{})
        if not quality.get("ok"):
            failures.append(name+": NOT_READY")
        context=ny.context(name,now) if ny is not None else None
        _,decision_quality=evaluate_pair(data,now,ny_context=context)
        failures.extend(name+": "+reason for reason in decision_quality["reasons"])
        for tf,seconds in (("m5",300),("h1",3600)):
            rows=data.get(tf,{}).get("candles",[])
            expected=(now//seconds-1)*seconds
            timestamps=[bar.get("timestamp") for bar in rows]
            if any(type(t) is not int for t in timestamps):
                failures.append(name+":"+tf+" invalid timestamp")
                continue
            if not timestamps or timestamps[-1]<expected:
                failures.append(name+":"+tf+" missing latest closed candle")
            # Require a contiguous recent trading window, not merely a fresh final bar.
            # Weekend/session closures may legitimately interrupt FX candles, so this
            # gate checks only the last 60 minutes on active weekday sessions.
            weekday=__import__("datetime").datetime.fromtimestamp(expected,__import__("datetime").timezone.utc).weekday()
            if weekday<5 and tf=="m5":
                recent=set(t for t in timestamps if isinstance(t,int))
                missing=[t for t in range(expected-11*300,expected+1,300) if t not in recent]
                if missing:
                    failures.append(name+":m5 recent 12-bar window has "+str(len(missing))+" gaps")
            if timestamps!=sorted(set(timestamps)):
                failures.append(name+":"+tf+" unsorted or duplicate candles")
    return failures

def main():
    root=storage_root(ROOT)
    data=json.loads((root/"data/latest.json").read_text())
    from .ny_integration import configured
    ny=configured(root,root/"data/cache.json",root/"data/latest.json")
    if ny is not None:
        try:ny.value=ny.sidecar.load()
        except Exception:ny.failure="NY archive unavailable; manual recovery required"
    failures=validate(data,ny=ny,require_strategies=True)
    print("SNAPSHOT_VALIDATION",json.dumps({"passed":not failures,"failures":failures}))
    if failures:
        sys.exit(1)

if __name__=="__main__":
    main()


