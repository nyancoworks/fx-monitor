"""Revalidate decision inputs without modifying the retained provider cache."""
from __future__ import annotations
import datetime as dt
import math
from collections import Counter
from .core import INTERVALS, MIN_BARS, assess, aggregate, weekly, screen_setup, confirm_m5_entry, expected_closed_timestamp
from .provenance import key

SOURCE = "Twelve Data"

def evaluate_data(raw, provenance, now):
    """Use only the latest uninterrupted verified source segment.

    Every intraday gap ends a segment. Calendar weekends alone do not prove
    this provider was closed (the current FX feed advertises 24/7 coverage).
    Daily gaps (weekends/holidays) are retained
    and disclosed by weekly aggregation. No attribution is inferred from price.
    """
    now=int(now)
    frames={}
    exclusions={}
    source_inventory={}
    reasons=[]
    for tf in ("m5", "h1", "d1"):
        rows=raw.get(tf, [])
        source_inventory[tf]=dict(Counter(provenance.get(key(tf,b["timestamp"]),"unknown")
                                         for b in rows if type(b.get("timestamp")) is int))
        segment=[]
        counts={"unverified_source":0, "invalid_candle":0, "segment_reset":0}
        previous=None
        for bar in rows:
            valid=False
            try:
                stamp=bar["timestamp"]
                o,h,l,c=(bar[k] for k in ("open","high","low","close"))
                valid=(type(stamp) is int and stamp % INTERVALS[tf]==0
                       and stamp+INTERVALS[tf]<=now
                       and all(isinstance(v,(int,float)) and not isinstance(v,bool)
                               and math.isfinite(v) and v>0 for v in (o,h,l,c))
                       and l<=min(o,c)<=max(o,c)<=h)
            except (KeyError, TypeError, ValueError):
                pass
            if not valid:
                counts["invalid_candle"]+=1
                segment=[]
                previous=None
                continue
            if previous is not None and stamp<=previous:
                reasons.append(tf+": unsorted or duplicate candles")
                segment=[]
                break
            if provenance.get(key(tf,stamp))!=SOURCE:
                counts["unverified_source"]+=1
                segment=[]
            else:
                if segment and tf!="d1" and stamp-segment[-1]["timestamp"]!=INTERVALS[tf]:
                    counts["segment_reset"]+=1
                    segment=[]
                segment.append(dict(bar))
            previous=stamp
        frames[tf]=segment
        exclusions[tf]={**counts, "retained_count":len(rows), "decision_count":len(segment)}
    frames["m15"]=aggregate(frames["m5"],300,900)
    frames["h4"]=aggregate(frames["h1"],3600,14400)
    frames["w1"]=weekly(frames["d1"],now)
    checks={tf:assess(rows,tf,now) for tf,rows in frames.items()}
    minimum={**MIN_BARS,"h1":35,"h4":15}
    # W1 is macro context, not a hard veto on an otherwise verified H4/H1 setup.
    # Keep W1 quality visible in timeframes, but do not add it to blocking reasons.
    for tf in ("m5","h1","h4","d1"):
        if len(frames[tf])<minimum[tf]:
            reasons.append(f"{tf}: verified history insufficient ({len(frames[tf])}/{minimum[tf]})")
        if not checks[tf]["fresh"]:
            reasons.append(tf+": verified completed candles stale or missing")
    freshness={}
    for tf in ("m5","h1","h4","d1"):
        expected=expected_closed_timestamp(tf,now)
        actual=frames[tf][-1]["timestamp"] if frames[tf] else None
        present=actual==expected
        freshness[tf]={"expected_last_closed":expected,"actual_last":actual,"latest_closed_present":present}
        if not present:
            reasons.append(tf+": latest verified closed candle missing")
    # Do not bridge holes in the most recent execution window.
    expected=freshness["m5"]["expected_last_closed"]
    missing=[t for t in range(expected-11*300,expected+1,300)
             if t not in {b["timestamp"] for b in frames["m5"]}]
    if missing:
        reasons.append(f"m5: recent 12-bar window has {len(missing)} gaps")
    # This is a diagnostic observation, never permission to use an older bar.
    since_close=now-(expected+300)
    publication={"state":"complete" if not missing else "missing",
                 "missing_timestamps":missing,"seconds_since_expected_close":since_close}
    if missing==[expected] and 0<=since_close<=60:
        publication["state"]="possible_publication_delay_unconfirmed"
    intraday_reasons=[r for r in reasons if r.startswith(("m5:","h1:","h4:"))]
    return frames,{"ready":not reasons,"evaluated_at":now,"verified_source":SOURCE,
                   "intraday_monitoring_ready":not intraday_reasons,
                   "intraday_monitoring_reasons":intraday_reasons,
                   "session_policy":"verified_continuous_observations_no_assumed_closures",
                   "reasons":reasons,"timeframes":checks,"exclusions":exclusions,
                   "closed_candle_freshness":freshness,"source_inventory":source_inventory,
                   "m5_publication":publication}

def evaluate_pair(data, now, *, ny_context=None):
    """Recompute from evidence; never trust saved readiness flags or grades."""
    evidence=data.get("decision_data",{})
    frames,quality=evaluate_data(evidence.get("raw",{}),evidence.get("provenance",{}),now)
    return apply_ny_quality(frames,quality,ny_context,now) if ny_context is not None else (frames,quality)

def evaluate_screening(data, now, *, ny_context=None):
    """Fresh read-time screening; stored setup/grade is never reused."""
    frames,quality=evaluate_pair(data,now,ny_context=ny_context)
    setup=screen_setup(frames,now) if quality["ready"] else {
        "grade":"C","stage":"screening","entry_confirmed":False,
        "reason":"Decision data quality unverified","data_quality_reasons":quality["reasons"]}
    entry=confirm_m5_entry(setup,frames["m5"],now)
    setup={**setup,"m5_entry_check":entry}
    from .input_assessment import assess_input_layers
    setup["input_assessment"] = assess_input_layers(frames,quality,now)
    return frames,quality,setup



def apply_ny_quality(frames, quality, context, now):
    """Explicit opt-in; retain every intraday and downstream trading veto.

    Context is freshly loaded/recomputed by the private archive service, not a
    published readiness flag. Native-provider equivalence is never asserted.
    """
    import copy
    from .core import ny17_frames, MIN_BARS
    frames=copy.deepcopy(frames);quality=copy.deepcopy(quality)
    study=context.get("study")
    blockers=list(context.get("blockers",[]))
    diagnostic={"schema":"ny17_custom_h1_v1","mode":context["mode"],
        "provider_native_d1_equivalent_verified":False,
        "provider_session_verified":context.get("provider_session_verified",context.get("source_contract_verified",False)),
        "utc_h1_contract_supported":context.get("source_contract_verified",False),
        "publication_policy_verified":context.get("publication_verified",False),
        "evaluated_at":now,"d1_count":study["d1_count"] if study else 0,
        "w1_count":study["w1_count"] if study else 0,
        "calendar_ready":bool(study and study["calendar_ready"]),
        "blockers":blockers,"entry_permission":False}
    quality["ny17"]=diagnostic
    diagnostic["observed_availability"]=context.get("observed_availability")
    if context.get("evidence_profile"):
        diagnostic.update(evidence_profile=context["evidence_profile"],
                          utc_contract_reference=context.get("utc_contract_reference"),
                          provider_publication_sla_verified=context.get("provider_publication_sla_verified",False))
    adoption_blockers=list(blockers)
    if not study or not study["calendar_ready"]:adoption_blockers.append("NY D1 incomplete, stale, holiday or publication pending")
    if context.get("evaluated_at")!=now:adoption_blockers.append("NY evaluation clock mismatch")
    if not context.get("source_contract_verified"):adoption_blockers.append("NY provider session/UTC H1 contract unverified")
    if not context.get("publication_verified"):adoption_blockers.append("NY publication policy unverified")
    try:
        candidate_frames=ny17_frames(study,now) if study else {"d1":[],"w1":[]}
    except (ValueError,TypeError,KeyError,OverflowError):
        candidate_frames={"d1":[],"w1":[]};adoption_blockers.append("NY frame validation failed")
    if len(candidate_frames["d1"])<60:adoption_blockers.append("NY D1 verified history insufficient")
    diagnostic["adoption_blockers"]=list(dict.fromkeys(adoption_blockers))
    diagnostic["adoption_ready"]=not adoption_blockers
    if context["mode"]!="adopt":return frames,quality
    if not study or not study["calendar_ready"]:blockers.append("NY D1 incomplete, stale, holiday or publication pending")
    if context.get("evaluated_at")!=now:blockers.append("NY evaluation clock mismatch")
    if not context.get("source_contract_verified"):blockers.append("NY provider session/UTC H1 contract unverified")
    if not context.get("publication_verified"):blockers.append("NY publication policy unverified")
    # Only the D1 data-quality method is replaced; no old reason is softened.
    reasons=[r for r in quality["reasons"] if not r.startswith("d1:")]
    try:
        converted=ny17_frames(study,now) if study else {"d1":[],"w1":[]}
    except (ValueError,TypeError,KeyError,OverflowError):
        converted={"d1":[],"w1":[]};blockers.append("NY frame validation failed")
    if len(converted["d1"])<60:blockers.append("NY D1 verified history insufficient")
    frames.update(converted)
    for tf in ("d1","w1"):
        rows=frames[tf];enough=len(rows)>=MIN_BARS[tf]
        fresh=bool(rows) and (study["calendar_ready"] if tf=="d1" else now-rows[-1]["session_end_utc"]<=8*86400)
        quality["timeframes"][tf]={"count":len(rows),"required":MIN_BARS[tf],"enough":enough,"structure_sufficient":enough,"age_minutes":round((now-rows[-1]["session_end_utc"])/60,2) if rows else None,"fresh":fresh,"ok":enough and fresh and not blockers,"calendar":"America/New_York 17:00","last_timestamp":rows[-1]["timestamp"] if rows else None}
    last=frames["d1"][-1]["timestamp"] if frames["d1"] else None
    from diagnostics.issue43_ny_shadow import latest_closed_date,close_utc,UTC
    clock=dt.datetime.fromtimestamp(now,UTC)
    expected=int(close_utc(latest_closed_date(clock)).timestamp())-86400
    quality["closed_candle_freshness"]["d1"]={"expected_last_closed":expected,"actual_last":last,"latest_closed_present":last==expected,"calendar":"America/New_York 17:00"}
    reasons.extend("ny17: "+r for r in dict.fromkeys(blockers))
    diagnostic["blockers"]=list(dict.fromkeys(blockers))
    quality["reasons"]=reasons;quality["ready"]=not reasons
    quality["session_policy"]="ny17_custom_h1_with_independent_source_publication_gates"
    return frames,quality

