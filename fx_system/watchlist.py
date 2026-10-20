"""H1 structural monitoring shortlist, not a trading execution system."""
from __future__ import annotations
import math

REASON_CODES={
    "H1 stop distance needs review":"stop_distance_review",
    "H4 opposes H1; context and risk require review":"higher_timeframe_conflict",
    "Confirmed structural target offers RR below 1.5":"rr_below_minimum",
    "H1 confirmed swing direction unclear":"h1_direction_unclear",
    "H1 invalidation breached":"structural_invalidation",
    "No confirmed structural target ahead of reference price":"structural_target_missing",
    "insufficient H1/H4 history":"history_insufficient",
}


def m5_diagnostic(setup, ready):
    check=setup.get("m5_entry_check") or {}
    reason=check.get("reason","M5 diagnostic unavailable")
    pattern=check.get("pattern")
    if not ready:
        status="data_not_ready"
    elif check.get("grade")=="D":
        status="invalidated"
    elif pattern in ("pullback","break_retest") and all(
            type(check.get(k)) in (int,float) and math.isfinite(check[k])
            for k in ("entry","sl","tp","rr")) and check["rr"]>=1.5:
        status="pattern_detected"
    elif "stale" in reason.lower() or "gaps" in reason.lower() or "insufficient" in reason.lower():
        status="unverified"
    else:
        status="waiting"
    return {"status":status,"pattern":pattern if status=="pattern_detected" else None,
            "reason":reason,"entry":check.get("entry") if status=="pattern_detected" else None,
            "sl":check.get("sl") if status=="pattern_detected" else None,
            "tp":check.get("tp") if status=="pattern_detected" else None,
            "rr":check.get("rr") if status=="pattern_detected" else None,
            }


def candidate(pair, data, quality):
    setup=data.get("setup") or {}
    ready=(quality.get("ok") is True and data.get("decision_quality",{}).get("ready") is True)
    direction=setup.get("direction")
    sl=setup.get("invalidation")
    tp=setup.get("structural_target")
    rr=setup.get("reference_rr")
    numbers=all(type(x) in (int,float) and math.isfinite(x) and x>0 for x in (sl,tp,rr))
    valid=(direction in ("long","short") and numbers and rr>=1.5
           and ((sl<tp) if direction=="long" else (sl>tp))
           and setup.get("grade")!="D")
    status="data_not_ready" if not ready else ("watch_candidate" if valid else "rejected")
    reason="verified data unavailable" if not ready else setup.get("reason","structure not verified")
    reason_code=("data_not_ready" if not ready else
                 "structural_candidate" if status=="watch_candidate" else
                 REASON_CODES.get(reason,"other_structural_rejection"))
    m5=m5_diagnostic(setup,ready)
    zone_proposal=setup.get("zone_proposal") or {"status":"unavailable","reason":"not_calculated"}
    expected_h4={"long":"HH_HL","short":"LH_LL"}.get(direction)
    h4_aligned=bool(status=="watch_candidate" and expected_h4 and setup.get("h4_structure")==expected_h4)
    # Zone has not yet been independently constructed or verified. Fail closed.
    zone_verified=False
    method_qualified=bool(h4_aligned and zone_verified)
    qualification={"status":"qualified" if method_qualified else "unqualified",
                   "h4_h1_aligned":h4_aligned,"zone_verified":zone_verified,
                   "missing":["h4_h1_alignment"] if not h4_aligned else []}
    if not zone_verified:
        qualification["missing"].append("verified_zone")
    return {"pair":pair,"status":status,"m5":m5,"zone_proposal":zone_proposal,"method_qualification":qualification,"reason_code":reason_code,"direction":direction if valid else None,
            "h4_structure":setup.get("h4_structure"),
            "invalidation":sl if valid else None,
            "structural_target":tp if valid else None,
            "reference_rr":rr if valid else None,
            "m5_pattern":(setup.get("m5_entry_check") or {}).get("pattern"),
            "evaluated_at":data.get("decision_quality",{}).get("evaluated_at"),
            "reason":reason}


def build_watchlist(pairs, qualities):
    rows=[candidate(name,data,qualities.get(name,{})) for name,data in pairs.items()]
    order={"watch_candidate":0,"rejected":1,"data_not_ready":2}
    rows.sort(key=lambda r:(order[r["status"]],-(r["reference_rr"] or 0),r["pair"]))
    candidates=[r for r in rows if r["status"]=="watch_candidate"]
    return {"candidates":candidates,"excluded":[r for r in rows if r["status"]!="watch_candidate"],
            "candidate_count":len(candidates),"total_pairs":len(rows),
            "note":"Watchlist only; not a trade instruction or execution."}
