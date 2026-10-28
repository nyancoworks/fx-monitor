from __future__ import annotations
import datetime as dt
import json
import os
import pathlib
import time
import requests
import lzma
from .dukascopy_probe import tick_url, decode_ticks, ticks_to_m5
from .core import PAIRS, INTERVALS, aggregate, assess, parse_row, technical, expected_closed_timestamp
from .strength import compute_strength
from .yahoo_provider import fetch_yahoo
from .provenance import record, reconcile_existing, assess_feed_consistency, key as provenance_key
from .data_quality import evaluate_screening
from .acquisition import request_plan, h1_recovery_needed, rebuild_verified_h1, retry_after_seconds
from .catchup import needs_m5_catchup
from .minute_quota import MinuteQuota
from .watchlist import build_watchlist
from .monitoring_scenarios import build_monitoring_scenarios
from .saved_economic_calendar import build_outlook_with_saved_calendar
from .indicator_inputs import contiguous_indicator_frames
from .monitoring_macro import build_reference, unavailable as unavailable_macro_reference
from .h4_setup import h4_setup_diagnostic
from .zones import propose_h1_zone
from .advisory_indicators import advisory_snapshot
from .indicator_research import research_snapshot
from .setup_comparison import compare_setups
from .m15_entry_shadow import m15_entry_shadow
from .m5_price_action import observe_m5_price_action
from .m5_counterpressure import assess_m5_counterpressure
from .m5_rci_momentum import observe_m5_rci, m5_history_diagnostic
from .h1_rci_shadow import h1_rci_shadow
from .multitimeframe_shadow import multitimeframe_shadow
from .dinapoli_research import dma_snapshot, confirmed_fibonacci
from .indicator_refresh import dinapoli_diagnostics, refresh_strategy_indicators
from .storage_paths import storage_root

ROOT=pathlib.Path(__file__).resolve().parents[1]
CACHE=storage_root(ROOT)/"data/cache.json"
OUTPUT=storage_root(ROOT)/"data/latest.json"
_NY_CAPTURE=None
DAILY_LIMIT=800
DAILY_RESERVE=80
# H1 recovery + M5 for the configured pairs shares the existing request budget.
# Keep this bounded and below the workflow's 12-minute refresh timeout.
REFRESH_DEADLINE_SECONDS=360

class ProviderRateLimit(requests.HTTPError):
    """Provider error payload reports quota rejection even with HTTP 200."""

def budget_for_day(cache,now):
    """Persist conservative request accounting, resetting at 00:00 UTC."""
    day=time.strftime("%Y-%m-%d",time.gmtime(now))
    budget=cache.get("_api_budget",{})
    if budget.get("utc_day")!=day:
        budget={"utc_day":day,"requests":0,"credits":0,"daily_limit":DAILY_LIMIT,"reserve":DAILY_RESERVE}
        cache["_api_budget"]=budget
    budget.setdefault("credits",budget.get("requests",0))  # Existing days: conservative migration.
    return budget


def fetch(session,key,pair,interval,limit,now):
    params={"symbol":pair,"interval":interval,"outputsize":limit,"timezone":"UTC","apikey":key}
    request_started_at=int(time.time())
    minute_quota=getattr(session,"_fx_minute_quota",None)
    response=session.get("https://api.twelvedata.com/time_series",params=params,timeout=(5,12))
    if minute_quota is not None:
        minute_quota.observe(response.headers,time.time(),time.monotonic())
    # Log quota headers without API keys, URLs or response bodies.
    quota_headers=("api-credits-used","api-credits-left","api-credits-request","retry-after","date")
    quota={name:response.headers.get(name) for name in quota_headers if response.headers.get(name) is not None}
    print("TWELVE_DATA_QUOTA",json.dumps({"pair":pair.replace("/",""),"interval":interval,"http_status":response.status_code,"request_started_at":request_started_at,"headers":quota}),flush=True)
    if response.status_code == 429:
        # Record only provider-defined diagnostic fields; never log URLs or API keys.
        try:
            error_payload = response.json()
        except ValueError:
            error_payload = None
        if isinstance(error_payload, dict):
            details = {k: error_payload[k] for k in ("code", "message", "status") if isinstance(error_payload.get(k), (str, int, float, bool))}
            print("TWELVE_DATA_429_DETAIL", json.dumps(details), flush=True)
    response.raise_for_status()
    payload=response.json()
    if payload.get("status")=="error":
        if payload.get("code")==429:
            raise ProviderRateLimit("provider quota rejection",response=response)
        raise RuntimeError("provider error code "+str(payload.get("code","unknown")))
    seconds={"5min":300,"1h":3600,"1day":86400}[interval]
    received_at=max(now,int(time.time()))
    from .provider_contract import observe_contract
    # Metadata evidence from the SAME response; no retry or additional request.
    print("PROVIDER_CONTRACT_OBSERVATION",json.dumps(observe_contract(payload,pair,interval,request_started_at,received_at)),flush=True)
    from .h1_response_evidence import capture
    capture(response, secret=key, pair=pair, interval=interval, outputsize=limit,
            started_at=request_started_at, received_at=received_at)
    if _NY_CAPTURE is not None and interval=="1h":
        _NY_CAPTURE.check_payload(payload,pair,received_at)
    return [r for r in (parse_row(x,seconds,received_at) for x in payload.get("values",[])) if r], response.headers.get("api-credits-request")

def missing_recent_m5(rows, now, count=12):
    """Missing completed M5 timestamps within the latest hour (active weekdays)."""
    latest=(now//300-1)*300
    # Do not treat ordinary weekend closures as provider failures.
    if dt.datetime.fromtimestamp(latest,dt.timezone.utc).weekday()>=5:
        return []
    present={bar["timestamp"] for bar in rows}
    return [t for t in range(latest-(count-1)*300,latest+1,300) if t not in present]

def _refresh(ny=None):
    selected=os.getenv("FX_PAIR","").replace("/","").upper().strip()
    if selected and selected not in {p.replace("/","") for p in PAIRS}:
        raise SystemExit("Unsupported FX_PAIR: "+selected)
    key=os.getenv("TWELVE_DATA_API_KEY")
    if not key:raise SystemExit("TWELVE_DATA_API_KEY is required")
    now=int(time.time())
    CACHE.parent.mkdir(parents=True,exist_ok=True)
    try: cache=json.loads(CACHE.read_text())
    except (OSError,ValueError):cache={}
    result={"generated_at":now,"source":"Twelve Data","pairs":{},"quality":{},"ready_pairs":[]}
    budget=budget_for_day(cache,now)
    session=requests.Session()
    minute_quota=MinuteQuota()
    session._fx_minute_quota=minute_quota
    requests_this_minute=0
    minute_window=time.monotonic()
    # One account-level diagnostic per UTC day; never log credentials or raw payload.
    if not budget.get("usage_checked") and not budget.get("provider_daily_exhausted") and budget["credits"] < DAILY_LIMIT-DAILY_RESERVE and time.time()>=cache.get("_primary_retry_after_until",0):
        budget["usage_checked"]=True
        budget["requests"]+=1
        budget["credits"]+=1
        requests_this_minute+=1
        try:
            minute_quota.reserve(time.monotonic())
            usage_response=session.get("https://api.twelvedata.com/api_usage",
                                       headers={"Authorization":"apikey "+key},timeout=(5,12))
            minute_quota.observe(usage_response.headers,time.time(),time.monotonic())
            usage_response.raise_for_status()
            usage_payload=usage_response.json()
            if isinstance(usage_payload,dict):
                print("TWELVE_DATA_USAGE_SCHEMA",json.dumps({"fields":sorted(usage_payload.keys()),"status":usage_payload.get("status")}),flush=True)
            else:
                print("TWELVE_DATA_USAGE_SCHEMA",json.dumps({"type":type(usage_payload).__name__}),flush=True)
        except (requests.RequestException,ValueError) as exc:
            print("TWELVE_DATA_USAGE_CHECK_FAILED",type(exc).__name__,flush=True)
    refresh_started=time.monotonic()
    deadline=refresh_started+REFRESH_DEADLINE_SECONDS
    provider_blocked_until=time.monotonic()+max(0,cache.get("_primary_retry_after_until",0)-time.time())
    dukascopy_blocked=False
    yahoo_blocked=False
    yahoo_attempts=0
    YAHOO_MAX_ATTEMPTS=26
    rotation=(now//3600)%len(PAIRS) if not selected else 0
    ordered_pairs=PAIRS[rotation:]+PAIRS[:rotation]
    print("RESCUE_PRIORITY",json.dumps({"rotation":rotation,"pairs":ordered_pairs}),flush=True)
    for pair in (p for p in ordered_pairs if not selected or p.replace("/","")==selected):
        name=pair.replace("/","")
        cached=cache.setdefault(name,{})
        errors={}
        raw={"m5":cached.get("m5",[]),"h1":cached.get("h1",[]),"d1":[]}
        provenance={}
        for source_tf in ('m5','h1'):
            provenance.update(reconcile_existing(cached,source_tf))
        from .new_pair_bootstrap import due, plan as bootstrap_plan, mark_attempt
        bootstrap=due(name,cached,os.getenv("FX_NEW_PAIR_H1_BOOTSTRAP")=="1")
        plan=bootstrap_plan(name,cached,request_plan(cached,provenance,now),bootstrap)
        acquisition={tf:{"priority":i+1,"attempted":False,"status":"cached"}
                     for i,(tf,_,_) in enumerate(plan)}
        for tf,provider,limit in plan:
            if tf=="h1" and not bootstrap and not h1_recovery_needed(cached,provenance,int(time.time())):
                # Complete hourly candles are reconstructed from the already-fetched M5 data.
                # A gap forces the provider fallback; never manufacture missing candles.
                rebuilt,provenance=rebuild_verified_h1(cached.get("h1",[]),raw["m5"],provenance,int(time.time()))
                recent=(int(time.time())//3600-1)*3600
                # A fresh last bar alone does not repair a gap between the old
                # cache and today's M5 window. Recheck the rebuilt decision
                # segment before skipping the existing native-H1 request slot.
                rebuilt_cache={"h1":rebuilt,"m5":raw["m5"]}
                if (any(b["timestamp"]==recent for b in rebuilt)
                        and not h1_recovery_needed(rebuilt_cache,provenance,int(time.time()))):
                    raw[tf]=rebuilt
                    cached[tf]=raw[tf]
                    continue

            # A throttled primary must not bypass independent rescue providers.
            primary_unavailable_reason=None
            if budget.get("provider_daily_exhausted"):
                primary_unavailable_reason="provider daily API credits exhausted; wait until next UTC day"
            elif time.monotonic() < provider_blocked_until:
                primary_unavailable_reason="provider rate limit active"
            elif time.monotonic() >= deadline:
                primary_unavailable_reason="refresh deadline exceeded"
            if primary_unavailable_reason:
                errors[tf]=primary_unavailable_reason
                raw[tf]=cached.get(tf,[])
            else:
                # Prefer provider remaining credits; use 6/65s only when evidence is absent.
                if budget.get("provider_daily_exhausted") or budget["credits"]>=DAILY_LIMIT-DAILY_RESERVE:
                    errors[tf]="daily request safety budget exhausted; using cached candles"
                    raw[tf]=cached.get(tf,[])
                    primary_unavailable_reason="daily API budget exhausted"
                if not primary_unavailable_reason and minute_quota.delay(time.monotonic())>0:
                    delay=minute_quota.delay(time.monotonic())
                    if time.monotonic()+delay+15 >= deadline:
                        errors[tf]='rate-limit wait exceeds deadline; cached data only'
                        raw[tf]=cached.get(tf,[])
                        primary_unavailable_reason="provider wait exceeds deadline"
                    if not primary_unavailable_reason and delay:time.sleep(delay)
                    if not primary_unavailable_reason:
                        minute_window=time.monotonic()
                        requests_this_minute=0
                if not primary_unavailable_reason:
                    acquisition[tf]["attempted"]=True
                    budget["requests"]+=1  # Count attempts, including provider errors.
                    budget["credits"]+=1  # Reserve at least one credit before any request.
                    try:
                        request_now=int(time.time())
                        minute_quota.reserve(time.monotonic())
                        if bootstrap and tf=="h1":mark_attempt(cached,request_now)
                        rows,credit_header=fetch(session,key,pair,provider,limit,request_now)
                        acquisition[tf].update({"status":"received" if rows else "received_empty",
                            "request_as_of":request_now,"returned_closed_bars":len(rows),
                            "returned_latest_closed":max((b["timestamp"] for b in rows),default=None)})
                        if not rows:
                            errors[tf]="provider returned no completed candles"
                        try: actual_credits=max(1,int(credit_header))
                        except (ValueError,TypeError): actual_credits=1
                        budget["credits"]+=actual_credits-1
                        requests_this_minute+=1
                        merged={r["timestamp"]:r for r in cached.get(tf,[])}
                        merged.update({r["timestamp"]:r for r in rows})
                        provenance=record(provenance,tf,rows,'Twelve Data')
                        # Retain enough D1 for 35 completed weekly candles, while keeping JSON manageable.
                        raw[tf]=sorted(merged.values(),key=lambda r:r["timestamp"])[-500:]
                        cached[tf]=raw[tf]
                    except (requests.RequestException,ValueError,RuntimeError) as exc:
                        requests_this_minute+=1
                        errors[tf]=type(exc).__name__
                        acquisition[tf]["status"]="failed"
                        if isinstance(exc,requests.HTTPError) and exc.response is not None:
                            acquisition[tf]["http_status"]=exc.response.status_code
                            errors[tf]="HTTP "+str(exc.response.status_code)
                            try: actual_credits=max(1,int(exc.response.headers.get("api-credits-request","1")))
                            except (ValueError,TypeError): actual_credits=1
                            budget["credits"]+=actual_credits-1
                        if isinstance(exc,requests.HTTPError) and exc.response is not None and (exc.response.status_code==429 or isinstance(exc,ProviderRateLimit)):
                            try:
                                detail=exc.response.json()
                            except ValueError:
                                detail={}
                            if isinstance(detail,dict) and detail.get("code")==429 and "out of api credits for the day" in str(detail.get("message","")).lower():
                                budget["provider_daily_exhausted"]=True
                                print("TWELVE_DATA_DAILY_EXHAUSTED",json.dumps({"utc_day":budget["utc_day"]}),flush=True)
                            retry_after=retry_after_seconds(exc.response.headers.get('Retry-After'),time.time())
                            provider_blocked_until=time.monotonic()+retry_after
                            cache["_primary_retry_after_until"]=int(time.time())+retry_after
                            errors[tf]='provider rate limit; honor Retry-After; cached data only'
                        raw[tf]=cached.get(tf,[])
            if bootstrap and tf=="h1":
                # A failed bootstrap never launches an independent history rescue.
                continue
            # Independent no-credential rescue; only use completed, missing bars.
            if tf in ("m5","h1") and not yahoo_blocked and yahoo_attempts<YAHOO_MAX_ATTEMPTS and time.monotonic()+12<deadline:
                interval={"m5":300,"h1":3600}[tf]
                last_complete=(now//interval-1)*interval
                if (max((b["timestamp"] for b in raw.get(tf,[])),default=0)<last_complete or (tf=="m5" and missing_recent_m5(raw.get("m5",[]),now))):
                    try:
                        yahoo_attempts+=1
                        rescue=fetch_yahoo(session,pair,tf,now)
                        existing={b["timestamp"]:b for b in raw.get(tf,[])}
                        overlap=[(existing[b["timestamp"]],b) for b in rescue if b["timestamp"] in existing and provenance.get(provenance_key(tf,b["timestamp"]))=="Twelve Data"]
                        threshold=0.03 if name.endswith("JPY") else 0.0003
                        max_diff=max((abs(a[field]-b[field]) for a,b in overlap for field in ("open","high","low","close")),default=None)
                        errors[tf+"_yahoo_comparison"]={"matched_bars":len(overlap),"max_abs_ohlc_diff":max_diff,"threshold":threshold,"passed":False,"reference_provenance_verified":False,"reason":"cached reference may contain Yahoo bars; comparison is diagnostic only"}
                        missing=[b for b in rescue if b["timestamp"] not in existing]
                        existing.update({b["timestamp"]:b for b in missing})
                        provenance=record(provenance,tf,missing,'Yahoo')
                        raw[tf]=sorted(existing.values(),key=lambda b:b["timestamp"])[-500:]
                        cached[tf]=raw[tf]
                        errors[tf+"_yahoo_filled"]=len(missing)
                        print("YAHOO_RESCUE",json.dumps({"pair":name,"timeframe":tf,"filled":len(missing),"attempt":yahoo_attempts}),flush=True)
                    except (requests.RequestException,ValueError,KeyError,TypeError,IndexError) as exc:
                        errors[tf+"_yahoo_error"]=str(exc)
                        print("YAHOO_RESCUE_ERROR",json.dumps({"pair":name,"timeframe":tf,"error":str(exc),"attempt":yahoo_attempts}),flush=True)
                        if isinstance(exc,requests.HTTPError) and exc.response is not None and exc.response.status_code in (403,429):
                            yahoo_blocked=True
            # Repair a missing completed hour before H1 reconstruction.
            last_hour=(now//3600-1)*3600
            if tf=="m5" and not dukascopy_blocked and (max((b["timestamp"] for b in raw.get("m5",[])),default=0)<last_hour+3300 or missing_recent_m5(raw.get("m5",[]),now)) and time.monotonic()+15<deadline:
                try:
                    # Rescue the earliest missing completed M5 candle whose entire
                    # UTC hour is closed; the old code always retried last_hour.
                    missing=missing_recent_m5(raw.get("m5",[]),now)
                    closed_hours=sorted({t//3600*3600 for t in missing if t//3600*3600+3600<=now})
                    rescue_hour=closed_hours[0] if closed_hours else last_hour
                    hour=dt.datetime.fromtimestamp(rescue_hour,dt.timezone.utc)
                    response=session.get(tick_url(name,hour),timeout=(3,8))
                    response.raise_for_status()
                    bars=ticks_to_m5(decode_ticks(response.content,name),hour)
                    if len(bars)==12 and [b["timestamp"] for b in bars]==[rescue_hour+i*300 for i in range(12)]:
                        existing={b["timestamp"]:b for b in raw.get("m5",[])}
                        missing=[b for b in bars if b["timestamp"] not in existing]
                        existing.update({b["timestamp"]:{k:v for k,v in b.items() if k!="tick_count"} for b in missing})
                        provenance=record(provenance,'m5',missing,'Dukascopy bid')
                        raw["m5"]=sorted(existing.values(),key=lambda b:b["timestamp"])[-500:]
                        errors["m5_fallback_filled_bars"]=len(missing)
                        cached["m5"]=raw["m5"]
                        errors["m5_source"]="Dukascopy bid fallback for previous complete hour; provider boundary"
                        boundaries=cached.setdefault("provider_boundaries",[])
                        if not any(x.get("hour")==rescue_hour and x.get("timeframe")=="m5" for x in boundaries):
                            boundaries.append({"provider":"Dukascopy bid","timeframe":"m5","hour":rescue_hour})
                        cached["provider_boundaries"]=boundaries[-48:]
                    else:
                        errors["m5_fallback"]="Dukascopy hour incomplete"
                except (requests.RequestException,lzma.LZMAError,ValueError) as exc:
                    errors["m5_fallback"]=str(exc)
                    if isinstance(exc,requests.HTTPError) and exc.response is not None and exc.response.status_code in (403,429):
                        dukascopy_blocked=True
                        errors["m5_fallback"]="Dukascopy access blocked; skip remaining pairs this run"
        # Also reconstruct after M5 when recovery changed the interval order.
        raw['h1'],provenance=rebuild_verified_h1(raw['h1'],raw['m5'],provenance,int(time.time()))
        cached['h1']=raw['h1']
        # Native provider D1 is not a certified NY17 candle; discard legacy cache.
        cached.pop("d1",None)
        cached.pop("d1_last_confirmed_day",None)
        for tf in acquisition:
            if tf in errors:
                acquisition[tf]["reason"]=errors[tf]
                if not acquisition[tf]["attempted"]:
                    acquisition[tf]["status"]="skipped"
        cached['bar_provenance']={provenance_key(tf,b['timestamp']):provenance.get(provenance_key(tf,b['timestamp']),'unknown') for tf in ('m5','h1') for b in raw[tf]}
        evaluation_now=int(time.time())
        frames={"m5":raw["m5"],"m15":aggregate(raw["m5"],300,900),"h1":raw["h1"],"h4":aggregate(raw["h1"],3600,14400),"d1":[],"w1":[]}
        result["pairs"][name]={tf:{"candles":rows[-100:],"quality":assess(rows,tf,evaluation_now)} for tf,rows in frames.items()}
        result["pairs"][name]["decision_data"]={"raw":{tf:raw[tf] for tf in ("m5","h1","d1")},"provenance":cached['bar_provenance']}
        decision_frames,decision_quality,setup=evaluate_screening(result["pairs"][name],int(time.time()))
        result["pairs"][name]["decision_quality"]=decision_quality
        result["pairs"][name]["acquisition"]=acquisition
        result["pairs"][name]["technical"]={tf:technical(rows) for tf,rows in decision_frames.items() if tf in ("h1","h4","d1","w1")}
        result["pairs"][name]["advisory_indicators"]={tf:advisory_snapshot(decision_frames[tf]) for tf in ("w1","d1","h4","h1","m5")}
        result["pairs"][name]["dinapoli_research"]=dinapoli_diagnostics(decision_frames,setup)
        # Non-gating indicator research from reverified closed candles only.
        result["pairs"][name]["indicator_research"]={tf:research_snapshot(decision_frames[tf]) for tf in ("w1","d1","h4","h1","m15")}

        # Screening and execution are separate stages. H1 selects setups;
        # a current, confirmed M5 trigger is evaluated at decision time.
        # All decision inputs are verified; macro/event promotion is still unimplemented.
        # No structural TP is inferred from the latest close. A confirmed
        # entry requires an independently verified target and fresh M5.
        result["pairs"][name]["setup"]=setup
        result["pairs"][name]["analysis_policy"]={
            "context_timeframes":["d1","h4"],
            "setup_timeframe":"h1",
            "entry_trigger_timeframe":"m5",
            "advisory_timeframes":["w1","d1","h4","h1","m5"],
            "macro_timeframes":["w1","d1"],
            "setup_context_timeframe":"h4",
            "screening_mode":"independent_swing_daytrade_scenario_review",
            "entry_requires_fresh_m5":True,
            "entry_requires_fresh_trigger_timeframe":True,
            "m5_requires_h4_h1_gate_and_multiple_closed_candles":True,
            "chart_review_supported":True,
            "note":"16 pairs x swing/daytrade are assessed independently. A/B/C describe scenario quality; saved prices and RR are references, not order permission."
        }
        checks={tf:assess(rows,tf,evaluation_now) for tf,rows in frames.items()}
        # Retained-data checks are combined with verified decision-data readiness.
        required=("m5","h1","h4","d1")
        ok=all(checks[tf]["ok"] for tf in required)
        # READY must mean the latest completed M5 and H1 bars are actually present.
        # Do not promote stale cache to a tradable signal merely because counts pass.
        freshness={}
        for tf,seconds in (("m5",300),("h1",3600)):
            expected=(evaluation_now//seconds-1)*seconds
            newest=max((b["timestamp"] for b in frames[tf]),default=0)
            freshness[tf]={"expected_last_closed":expected,"actual_last":newest,
                           "latest_closed_present":newest>=expected}
        ok=ok and all(v["latest_closed_present"] for v in freshness.values()) and decision_quality["ready"]
        feed_quality=assess_feed_consistency(provenance,raw)
        mixed_sources=feed_quality["mixed_source_warning"]
        feed_consistent=feed_quality["execution_feed_consistent"]
        result["quality"][name]={"ok":ok,"required_timeframes":list(required),"timeframes":checks,"provider_errors":errors,"closed_candle_freshness":freshness,"mixed_source_warning":mixed_sources,"execution_feed_consistent":feed_consistent,"requires_single_feed_confirmation":not feed_consistent,"signal_eligible":False,"screening_data_ready":ok,"signal_quality_note":"Mixed provider prices: confirm swing and trigger against one consistent feed" if mixed_sources else "Freshness and required history passed"}
        if ok:result["ready_pairs"].append(name)
        result["quality"][name].update({"decision_data_ready":decision_quality["ready"],
            "data_quality_reasons":decision_quality["reasons"],
            "signal_quality_note":"; ".join(decision_quality["reasons"]) if not decision_quality["ready"] else
                "Verified decision data available for discretionary scenario review"})
        print(name,"READY" if ok else "NOT_READY",json.dumps({tf:{"ok":v["ok"],"count":v["count"]} for tf,v in checks.items()}),flush=True)
    # One bounded final M5 catch-up pass: earlier pairs may become stale while
    # the remaining pairs are fetched. Never bypass provider budgets or cooldowns.
    for name,data in result["pairs"].items():
        attempt=data.get("acquisition",{}).get("m5",{})
        first_request=attempt.get("request_as_of")
        catchup_now=int(time.time())
        expected=(catchup_now//300-1)*300
        if not needs_m5_catchup(first_request,catchup_now,data["decision_data"]["provenance"]):
            continue
        if (budget.get("provider_daily_exhausted") or budget["credits"]>=DAILY_LIMIT-DAILY_RESERVE
                or time.monotonic()<provider_blocked_until or time.monotonic()+20>=deadline):
            print("M5_CATCHUP",json.dumps({"pair":name,"status":"skipped","reason":"budget_cooldown_or_deadline"}),flush=True)
            continue
        if minute_quota.delay(time.monotonic())>0:
            delay=minute_quota.delay(time.monotonic())
            if time.monotonic()+delay+20>=deadline:
                print("M5_CATCHUP",json.dumps({"pair":name,"status":"skipped","reason":"rate_window_deadline"}),flush=True)
                continue
            if delay:time.sleep(delay)
            minute_window=time.monotonic()
            requests_this_minute=0
        budget["requests"]+=1
        budget["credits"]+=1
        requests_this_minute+=1
        try:
            request_at=int(time.time())
            pair=next(p for p in PAIRS if p.replace("/","")==name)
            minute_quota.reserve(time.monotonic())
            rows,credit_header=fetch(session,key,pair,"5min",288,request_at)
            try:actual_credits=max(1,int(credit_header))
            except (ValueError,TypeError):actual_credits=1
            budget["credits"]+=actual_credits-1
            raw=data["decision_data"]["raw"]
            merged={b["timestamp"]:b for b in raw["m5"]}
            merged.update({b["timestamp"]:b for b in rows})
            raw["m5"]=sorted(merged.values(),key=lambda b:b["timestamp"])[-500:]
            cache[name]["m5"]=raw["m5"]
            provenance=data["decision_data"]["provenance"]
            provenance=record(provenance,"m5",rows,"Twelve Data")
            data["decision_data"]["provenance"]=provenance
            cache[name]["bar_provenance"]=provenance
            attempt["catchup_request_as_of"]=request_at
            attempt["catchup_returned_latest_closed"]=max((b["timestamp"] for b in rows),default=None)
            print("M5_CATCHUP",json.dumps({"pair":name,"status":"received","rows":len(rows),
                "expected":expected,"returned_latest":attempt["catchup_returned_latest_closed"]}),flush=True)
        except (requests.RequestException,ValueError,RuntimeError) as exc:
            print("M5_CATCHUP",json.dumps({"pair":name,"status":"failed","error_type":type(exc).__name__}),flush=True)
            if isinstance(exc,requests.HTTPError) and exc.response is not None:
                try:actual_credits=max(1,int(exc.response.headers.get("api-credits-request","1")))
                except (ValueError,TypeError):actual_credits=1
                budget["credits"]+=actual_credits-1
            if isinstance(exc,requests.HTTPError) and exc.response is not None and (exc.response.status_code==429 or isinstance(exc,ProviderRateLimit)):
                try:details=exc.response.json()
                except ValueError:details={}
                if isinstance(details,dict) and details.get("code")==429 and "out of api credits for the day" in str(details.get("message","")).lower():
                    budget["provider_daily_exhausted"]=True
                retry_after=retry_after_seconds(exc.response.headers.get("Retry-After"),time.time())
                provider_blocked_until=time.monotonic()+retry_after
                cache["_primary_retry_after_until"]=int(time.time())+retry_after
    # Re-evaluate every pair at a single fresh clock; missing bars stay NOT_READY.
    final_now=int(time.time())
    result["evaluated_at"]=final_now
    result["ready_pairs"]=[]
    if ny is not None:
        ny.synchronize(result)
    for name,data in result["pairs"].items():
        # The published candle view must reflect the same verified catch-up inputs
        # used by the final decision and by independent snapshot validation.
        refreshed_m5=data["decision_data"]["raw"]["m5"]
        data["m5"]={"candles":refreshed_m5[-100:],"quality":assess(refreshed_m5,"m5",final_now)}
        ny_context=ny.context(name,final_now) if ny is not None else None
        verified,quality,setup=evaluate_screening(data,final_now,ny_context=ny_context)
        data["decision_quality"]=quality
        indicator_frames, input_quality = contiguous_indicator_frames(verified, quality)
        data["indicator_input_quality"] = input_quality
        data["monitoring_macro_reference"] = (build_reference(ny.value, name, final_now, ny_context)
            if ny is not None and ny.value is not None else
            unavailable_macro_reference("verified_archive_unavailable", final_now))
        # Publish the verified NY17 macro candles, not the retired native D1 placeholders.
        for macro_tf in ("d1","w1"):
            data[macro_tf]={"candles":verified[macro_tf][-100:],
                            "quality":quality["timeframes"][macro_tf]}
        data["h4_setup_shadow"]=h4_setup_diagnostic(verified)
        data["h4_setup_shadow"]["dinapoli"]= {
            **dma_snapshot(verified["h4"]),
            "confirmed_fibonacci": confirmed_fibonacci(verified["h4"], data["h4_setup_shadow"].get("direction")),
        }
        data["setup_comparison"]=compare_setups(setup,data["h4_setup_shadow"],quality)
        data["m15_entry_shadow"]=m15_entry_shadow(verified,data["h4_setup_shadow"],quality)
        h1_structure=data["technical"].get("h1",{}).get("structure")
        h1_direction={"HH_HL":"long","LH_LL":"short"}.get(h1_structure)
        data["m5_price_action_shadow"]=observe_m5_price_action(verified["m5"],h1_direction)
        data["m5_counterpressure_shadow"]=assess_m5_counterpressure(verified["m5"],h1_direction)
        data["m5_history_diagnostic"]=m5_history_diagnostic(verified["m5"])
        data["m5_rci_momentum_shadow"]=observe_m5_rci(verified["m5"],h1_direction)
        data["h1_rci_shadow"]=h1_rci_shadow(verified["h1"],data["h4_setup_shadow"],quality)
        data["multitimeframe_shadow"]=multitimeframe_shadow(data["h4_setup_shadow"],data["h1_rci_shadow"],data["m15_entry_shadow"],data["setup_comparison"],quality)
        setup["zone_proposal"]=propose_h1_zone(verified["h1"],setup.get("direction"),setup.get("invalidation"))
        data["setup"]=setup
        data["technical"]={tf:technical(indicator_frames[tf]) for tf in ("m5","m15","h1","h4","d1","w1")}
        data["advisory_indicators"]={tf:advisory_snapshot(indicator_frames[tf]) for tf in ("w1","d1","h4","h1","m5")}
        # Reference only: reuse the already validated contiguous indicator frames.
        # No new provider calls, no new entry gates, and no candidate selection change.
        refresh_strategy_indicators(data,verified,indicator_frames,quality,setup)
        q=result["quality"][name]
        q.update({"ok":quality["ready"] and all(quality["timeframes"][tf]["ok"] for tf in ("m5","h1","h4","d1")),"decision_data_ready":quality["ready"],
                  "intraday_monitoring_ready":quality["intraday_monitoring_ready"],
                  "intraday_monitoring_reasons":quality["intraday_monitoring_reasons"],
                  "data_quality_reasons":quality["reasons"],"closed_candle_freshness":quality["closed_candle_freshness"],
                  "retained_timeframes":q["timeframes"],"timeframes":quality["timeframes"]})
        q["screening_data_ready"]=q["ok"]
        if not quality["ready"]:
            q["signal_quality_note"]="; ".join(quality["reasons"])
        if q["ok"]:
            result["ready_pairs"].append(name)
        # Compare each provider request clock with the final verification clock.
        # Diagnostic only: this never changes readiness or the source of a candle.
        timeline={}
        for tf in ("m5","h1","d1"):
            attempt=data.get("acquisition",{}).get(tf,{})
            closed=quality.get("closed_candle_freshness",{}).get(tf,{})
            seconds=INTERVALS[tf]
            request_at=attempt.get("request_as_of")
            expected_at_request=expected_closed_timestamp(tf,request_at) if type(request_at) is int else None
            timeline[tf]={"request_as_of":request_at,
                "request_expected_last_closed":expected_at_request,
                "provider_returned_last_closed":attempt.get("returned_latest_closed"),
                "final_expected_last_closed":closed.get("expected_last_closed"),
                "final_verified_last_closed":closed.get("actual_last"),
                "crossed_close_boundary":(expected_at_request is not None and
                    closed.get("expected_last_closed") is not None and
                    expected_at_request!=closed["expected_last_closed"]),
                "request_to_final_seconds":(final_now-request_at if type(request_at) is int else None)}
        if ny is not None and ny.mode=="adopt":
            timeline["d1"]["request_calendar"]="native_provider_UTC_assumption"
            timeline["d1"]["final_calendar"]="America/New_York 17:00"
            timeline["d1"]["crossed_close_boundary"]=None
        data["freshness_timeline"]=timeline
        print("FRESHNESS_TIMELINE",json.dumps({"pair":name,"evaluated_at":final_now,
            "timeframes":timeline}),flush=True)
        print("FINAL_QUALITY",json.dumps({"pair":name,"evaluated_at":final_now,
              "ready":q["ok"],"intraday_monitoring_ready":quality["intraday_monitoring_ready"],
              "reasons":quality["reasons"],"m5_publication":quality["m5_publication"]}),flush=True)
    # Reporting-only M5/RCI coverage for all configured pairs. Never alter gates.
    m5_coverage_rows=[{"pair":name,
        "history":data.get("m5_history_diagnostic",{}),
        "rci_status":data.get("m5_rci_momentum_shadow",{}).get("status","unverified")}
        for name,data in result["pairs"].items()]
    result["m5_rci_coverage"]={"pairs_total":len(m5_coverage_rows),
        "rci_calculated":sum(x["rci_status"]=="calculated" for x in m5_coverage_rows),
        "history_complete":sum(x["history"].get("status")=="complete" for x in m5_coverage_rows),
        "history_gapped":sum(x["history"].get("status")=="gapped" for x in m5_coverage_rows),
        "history_insufficient":sum(x["history"].get("status")=="insufficient" for x in m5_coverage_rows),
        "history_invalid":sum(x["history"].get("status")=="invalid" for x in m5_coverage_rows),
        "rows":m5_coverage_rows,"advisory_only":True}
    print("M5_RCI_COVERAGE",json.dumps(result["m5_rci_coverage"],ensure_ascii=False),flush=True)
    result['refresh_elapsed_seconds']=round(time.monotonic()-refresh_started,2)
    result["signal_eligible_pairs"]=[name for name,q in result["quality"].items() if q.get("signal_eligible")]
    result["signal_eligible_count"]=len(result["signal_eligible_pairs"])
    result["watchlist"]=build_watchlist(result["pairs"],result["quality"])
    # Independent H4/H1 saved-candle research; does not reuse M5 gate.
    result["scheduled_outlook"]=build_outlook_with_saved_calendar(
        result["pairs"],result["quality"],evaluated_at=final_now)
    from .strategy_report import render_strategy_report, report_records
    report_keys={(r['pair'],r['strategy']) for r in report_records(result['scheduled_outlook'])}
    print("SCHEDULED_CANDIDATES",json.dumps({
        "evaluated_at":result["scheduled_outlook"]["evaluated_at"],
        "grade_counts":result["scheduled_outlook"]["grade_counts"],
        "strategy_candidate_count":result["scheduled_outlook"]["strategy_candidate_count"],
        "candidates":[{
            "pair":c["pair"],"strategy":c["strategy"],"direction":c["direction"],
            "priority":c["priority"],"timing":c["timing_assessment"],"macro":c["macro_context"],
            "price_action":c["price_action"].get("pattern"),
            "rci9":c["rci9_context"].get("movement","unverified"),
            "next_check":c["next_check"]
        } for c in result["scheduled_outlook"]["strategy_candidates"] if (c['pair'],c['strategy']) in report_keys],
        
    },ensure_ascii=False),flush=True)
    assessments=result["scheduled_outlook"]["strategy_assessments"]
    print("SCHEDULED_STRATEGY_SUMMARY",json.dumps({
        "evaluated_at":final_now,"assessment_count":len(assessments),
        "assessment_counts":result["scheduled_outlook"]["assessment_counts"],
        "canonical_assessment_field":"strategy_assessments","advisory_only":True
    },ensure_ascii=False),flush=True)
    for assessment in assessments:
        print("SCHEDULED_STRATEGY_ASSESSMENT",json.dumps({
            "evaluated_at":final_now,"assessment":assessment
        },ensure_ascii=False),flush=True)
    print('SCHEDULED_REPORT',json.dumps({'evaluated_at':final_now,'advisory_only':True,
        'text':render_strategy_report(result)},ensure_ascii=False),flush=True)
    # Publish every saved monitoring row for read-only acceptance, even when
    # latest.json exceeds connector limits. These rows contain no raw candles.
    # Logging must not re-evaluate freshness or change any decision/gate.
    for row in result["scheduled_outlook"]["rows"]:
        q=result["quality"].get(row["pair"],{})
        print("SCHEDULED_PAIR",json.dumps({
            "evaluated_at":final_now,
            "quality":{"ok":q.get("ok"),"reasons":q.get("reasons",[])},
            "outlook":row
        },ensure_ascii=False),flush=True)
    # Compact, audit-friendly W1 coverage summary from independently evaluated
    # per-pair evidence. Never infer NY17 approval from candle count.
    weekly_rows=[]
    for row in result["scheduled_outlook"]["rows"]:
        history=row.get("w1_history",{})
        weekly_rows.append({"pair":row["pair"],"count":history.get("observed_count",0),
            "shortfall":history.get("shortfall",35),
            "verified":history.get("verified",False),
            "d1_verified_source_count":history.get("d1_verified_source_count"),
            "d1_retained_count":history.get("d1_retained_count"),
            "ny17_count":history.get("ny17_observed_w1_count"),
            "ny17_shortfall":history.get("ny17_shortfall"),
            "ny17_independently_eligible":history.get("ny17_independently_eligible",False)})
    result["weekly_coverage"]={"required":35,"rows":weekly_rows,
        "verified_pairs":sum(x["verified"] for x in weekly_rows),
        "complete_count_pairs":sum(x["shortfall"]==0 for x in weekly_rows),
        "ny17_eligible_pairs":sum(x["ny17_independently_eligible"] for x in weekly_rows),
        "ny17_session_certified_by_this_summary":False}
    print("W1_COVERAGE",json.dumps(result["weekly_coverage"]),flush=True)
    # Reporting-only scenarios; never change the watchlist or formal trade gates.
    try:
        result["monitoring_scenarios"]=build_monitoring_scenarios(
            result["pairs"],result["quality"],evaluated_at=final_now)
    except (ValueError,TypeError,KeyError,OverflowError) as exc:
        result["monitoring_scenarios"]={"status":"unavailable","advisory_only":True,
            "error_type":type(exc).__name__}
    print("WATCHLIST",json.dumps({"candidate_count":result["watchlist"]["candidate_count"],"pairs":[x["pair"] for x in result["watchlist"]["candidates"]]}),flush=True)
    result["ready_count"]=len(result["ready_pairs"])
    result["intraday_monitoring"]={"ready_pairs":[name for name,q in result["quality"].items()
        if q.get("intraday_monitoring_ready")],
        "scope":"verified M5/H1/H4 observation only; not macro or trade clearance"}
    print("INTRADAY_MONITORING",json.dumps(result["intraday_monitoring"]),flush=True)
    from .h1_response_evidence import status as evidence_status
    result["h1_response_evidence"]=evidence_status()
    result["all_pairs_ready"]=len(result["ready_pairs"])==(1 if selected else len(PAIRS))
    result["provider_metrics"]={"yahoo_attempts":yahoo_attempts,"dukascopy_circuit_open":dukascopy_blocked,"yahoo_circuit_open":yahoo_blocked}
    result["currency_strength"]=compute_strength(result,now=final_now)
    print("CURRENCY_STRENGTH",json.dumps({k:result["currency_strength"][k] for k in
        ("algorithm","advisory_only","evaluated_at","status","universe","lookback_h1_bars",
         "coverage_pairs","expected_pairs","start_closed_at","end_closed_at",
         "scores","ranking","observations","fit_rmse_log_pct")},ensure_ascii=False),flush=True)
    result["api_budget"]={**budget,"remaining_safe_requests":max(0,DAILY_LIMIT-DAILY_RESERVE-budget["credits"])}
    print("API_BUDGET",json.dumps(result["api_budget"]),flush=True)
    if selected:
        result["on_demand_pair"]=selected
        target=storage_root(ROOT)/"data"/"on_demand"/(selected+".json")
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(result,separators=(",",":")))
        print("ON_DEMAND_OUTPUT",target,flush=True)
    else:
        from .historical_shape_reference import build_references
        result['historical_shape_references'] = build_references(cache, result['scheduled_outlook'], final_now)
        CACHE.write_text(json.dumps(cache,separators=(",",":")))
        OUTPUT.write_text(json.dumps(result,separators=(",",":")))
    print("READY_PAIRS",len(result["ready_pairs"]),"/",len(PAIRS),flush=True)

def main():
    """Default-off publisher; NY storage and selection are explicit opt-ins."""
    from .ny_integration import configured
    ny=configured(storage_root(ROOT),CACHE,OUTPUT)
    if ny is None:return _refresh()
    global fetch,_NY_CAPTURE
    original=fetch
    previous_capture=_NY_CAPTURE
    _NY_CAPTURE=ny
    fetch=ny.wrap_fetch(original,lambda:dt.datetime.fromtimestamp(int(time.time()),dt.timezone.utc))
    try:return _refresh(ny)
    except BaseException:
        # Retain responses already received even if legacy publication fails.
        try:ny.sidecar.update(ny.queue)
        except Exception:pass
        raise
    finally:
        fetch=original
        _NY_CAPTURE=previous_capture


if __name__=="__main__":main()
