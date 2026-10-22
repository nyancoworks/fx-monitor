"""Scheduled FX directional research from SAVED completed-candle evidence.

Separate from M5 execution timing and independent macro/event clearance,
live executable pricing. No network access or synthetic candles.
"""
from __future__ import annotations
import math
from .monitor_pairs import PAIR_KEYS
from .strategy_explanation import explain_strategy_track
from .rci_track_context import rci_track_context
from .strategy_indicator_context import strategy_indicator_context
from .strategy_scenario_assessment import assess_strategy
from .scenario_price_plan import saved_price_plan, trigger_price_reference
from .price_reaction_observation import observe_saved_reaction
from .scenario_conditions import condition_inputs
from .strategy_strength import build_contexts
from .range_scenario import apply_range

def _dict(x): return x if isinstance(x,dict) else {}
def _price(x): return x if type(x) in (int,float) and math.isfinite(x) and x>0 else None
def _structure(x):
    return x if x in ("HH_HL","LH_LL","mixed","unconfirmed") else "unconfirmed"


def _macro_reference(data, evaluated_at):
    """Reference evidence for explanation, never a trade execution decision."""
    ref = _dict(data.get("monitoring_macro_reference"))
    source = _dict(ref.get("source"))
    if (ref.get("schema") != "monitoring_macro_reference_v1" or
            ref.get("status") != "available" or ref.get("evaluated_at") != evaluated_at or
            ref.get("source_verified_for_reference") is not True or
            ref.get("reference_only") is not True or
            source.get("provider") != "Twelve Data" or source.get("mixed_provider") is not False):
        return {}
    result = {}
    for tf in ("w1", "d1"):
        value = _dict(_dict(ref.get("timeframes")).get(tf))
        end = value.get("last_session_end_utc")
        if (value.get("status") != "observed_reference" or value.get("reference_only") is not True or
                type(end) is not int or end > evaluated_at):
            continue
        result[tf] = {k:value.get(k) for k in (
            "available_candles", "target_calendar_slots", "absent_calendar_slots", "partial_candles",
            "observed_h1", "missing_h1", "coverage_of_nominal_slots", "last_session_end_utc",
            "technical", "super_bollinger", "indicator_research", "dinapoli_dma")}
        result[tf].update(reference_only=True,
                          basis="observed_h1_with_disclosed_gaps")
    return result


def _strategy_tracks(structural, tfs, published, valid_clock, m15, m5_use):
    """Independent review tracks; no execution permission or inferred M5 pattern."""
    direction={"HH_HL":"long","LH_LL":"short"}
    tracks={}
    for name,base,trigger in (("swing","h4","m15"),("daytrade","h1","m5")):
        base_ok=(valid_clock and _dict(tfs.get(base)).get("ok") is True
                 and _dict(published.get(base)).get("ok") is True
                 and _dict(structural.get(base)).get("status")=="ok")
        structure=_structure(_dict(structural.get(base)).get("structure")) if base_ok else "unconfirmed"
        focus=direction.get(structure)
        trigger_ok=(valid_clock and _dict(tfs.get(trigger)).get("ok") is True
                    and _dict(published.get(trigger)).get("ok") is True)
        if trigger=="m15":
            status=m15.get("status") if trigger_ok and m15.get("advisory_only") is True else "unverified"
            if status=="watch_pattern" and m15.get("direction")!=focus:
                status="unverified"
            if status not in ("watch_pattern","waiting","invalidated"):
                status="unverified"
        else:
            # Fresh M5 candles alone do not establish an entry pattern.
            status="candle_current" if trigger_ok and m5_use=="current_reference" else "unverified"
        state=("unassessed" if not base_ok else "waiting_structure" if not focus else
               "watch" if trigger_ok else "waiting_trigger")
        tracks[name]={"base_timeframe":base,"trigger_timeframe":trigger,
                      "base_structure":structure,
                      "direction":focus,"state":state,"trigger_status":status,
                      "base_verified":bool(base_ok),"trigger_verified":bool(trigger_ok),
                      "advisory_only":True}
    return tracks

def _one(pair, data, source_quality, evaluated_at):
    data, source_quality = _dict(data), _dict(source_quality)
    dq = _dict(data.get("decision_quality"))
    tfs = _dict(dq.get("timeframes"))
    published = _dict(source_quality.get("timeframes"))
    structural = _dict(data.get("technical"))
    valid_clock = type(evaluated_at) is int and evaluated_at>0 and dq.get("evaluated_at")==evaluated_at
    # Per-timeframe evidence is verified independently. M5 is deliberately
    # excluded, but missing H1/H4 evidence is never promoted.
    ready = valid_clock and all(
        _dict(tfs.get(tf)).get("ok") is True and
        _dict(published.get(tf)).get("ok") is True and
        _dict(structural.get(tf)).get("status")=="ok"
        for tf in ("h4","h1"))
    h1 = _structure(_dict(structural.get("h1")).get("structure")) if ready else "unconfirmed"
    h4 = _structure(_dict(structural.get("h4")).get("structure")) if ready else "unconfirmed"
    d1_ready=(valid_clock and _dict(tfs.get("d1")).get("ok") is True
              and _dict(published.get("d1")).get("ok") is True
              and _dict(structural.get("d1")).get("status")=="ok")
    d1 = _structure(_dict(structural.get("d1")).get("structure")) if d1_ready else "unconfirmed"
    direction={"HH_HL":"long","LH_LL":"short"}
    h1_dir=direction.get(h1)
    h4_dir=direction.get(h4)
    # A mixed H4 is not necessarily opposed; an opposed H4 blocks actionable
    # monitoring even though H1 might still be an educational directional lead.
    if not ready:
        state, focus, reason = "unassessed",None,"H4/H1の確定足品質・出所・評価時刻が確認できない"
        next_check="検証済みH4/H1確定足の再取得・再評価"
    elif h1_dir is None and h4_dir is None:
        state,focus,reason="skip",None,"H4とH1の高値安値構造がともに方向未確認"
        next_check="H4/H1で方向が確定するまで待つ"
    elif h1_dir and h4_dir and h1_dir != h4_dir:
        state,focus,reason="skip",None,"H4とH1の確定方向が逆"
        next_check="H4/H1の構造が整合するまで待つ"
    elif h4_dir and h1_dir==h4_dir:
        state,focus,reason="directional_watch",h4_dir,"H4とH1の確定高値安値が同方向"
        next_check="H1の支持抵抗・構造無効化・目標を確認し、M15の確定反応を待つ"
    else:
        state,focus,reason="conditional_watch",h1_dir or h4_dir,"一方の時間足の方向のみ確認済み"
        next_check="H4/H1の方向整合を確認する"
    m15 = _dict(_dict(data.get("m15_entry_shadow")))
    m15_diagnostic = {"status": m15.get("status", "missing"),
                      "reason": m15.get("reason", "M15診断データなし")}
    # Explain why an H1-led watch cannot use H4-gated M15 confirmation.
    if focus and m15.get("status") == "not_ready" and m15.get("reason") == "H4 setup not confirmed":
        reason += "。H4セットアップ未成立のためM15確認待ち"
        next_check += "。H4の確定構造とセットアップ成立を再確認"
    elif focus and m15.get("status") == "invalidated" and m15.get("reason") == "H4 invalidation crossed":
        reason += "。M15終値がH4構造無効化水準を突破"
        next_check += "。H4無効化水準と新たな構造を再確認"
    m15_verified=(valid_clock and _dict(tfs.get("m15")).get("ok") is True
                  and _dict(published.get("m15")).get("ok") is True)
    m15_status=m15.get("status") if m15_verified and m15.get("advisory_only") is True else None
    # A detected pattern must belong to the selected direction; a mismatched or
    # invalidated M15 pattern must not improve review priority.
    m15_direction_matches=bool(focus and m15.get("direction")==focus)
    if m15_status=="watch_pattern" and not m15_direction_matches:
        m15_status="unverified"
    if m15_status not in ("waiting","watch_pattern","invalidated"):
        m15_status="unverified"
    m15_delay=m15.get("m15_observation_delay_minutes") if m15_verified else None
    m15_delay=(m15_delay if type(m15_delay) is int and 0<=m15_delay<=15 else None)
    # An older pattern remains useful for review but cannot support top-priority A.
    # D1 context is disclosed without imposing an all-timeframe AND gate.
    d1_dir=direction.get(d1)
    higher_context=("aligned" if focus and d1_dir==focus else
                    "countertrend" if focus and d1_dir and d1_dir!=focus else
                    "unconfirmed")
    if focus and higher_context=="countertrend":
        reason += "。D1は監視方向と逆"
        next_check += "。D1逆行の継続・転換も確認"
    elif focus and not d1_ready:
        reason += "。D1品質未確認"
    # M5 delay is classified relative to its verified completed candle.
    # Stale observations may guide what to check next, never permit execution.
    m5q=_dict(tfs.get("m5"))
    m5pub=_dict(published.get("m5"))
    age=(m5q.get("age_minutes") if valid_clock and type(m5q.get("age_minutes")) in (int,float)
         and math.isfinite(m5q["age_minutes"]) and m5q["age_minutes"]>=0 else None)
    if valid_clock and age is not None and m5pub.get("count",0)>0:
        m5_use=("current_reference" if age<=5 and m5q.get("ok") is True
                and m5pub.get("ok") is True else
                "delayed_reference" if age<=10 else
                "structure_context_only" if age<=15 else "unverified")
    else:
        m5_use="unverified"
    if focus and m5_use in ("delayed_reference","structure_context_only"):
        next_check += "。M5保存時の反応は遅延参考、次の確定足を確認"
    # A verified W1 (35 bars) is useful macro context, never an automatic veto.
    w1q=_dict(tfs.get("w1"))
    w1pub=_dict(published.get("w1"))
    w1tech=_dict(structural.get("w1"))
    w1_ready=(valid_clock and w1q.get("ok") is True and
              w1pub.get("ok") is True and w1q.get("count",0)>=35 and
              w1tech.get("status")=="ok")
    w1_count=w1q.get("count") if type(w1q.get("count")) is int and w1q["count"]>=0 else 0
    w1_missing=max(0,35-w1_count)
    d1_counts=_dict(_dict(dq.get("exclusions")).get("d1"))
    verified_d1=d1_counts.get("decision_count")
    retained_d1=d1_counts.get("retained_count")
    verified_d1=verified_d1 if type(verified_d1) is int and verified_d1>=0 else None
    retained_d1=retained_d1 if type(retained_d1) is int and retained_d1>=0 else None
    ny17=_dict(dq.get("ny17"))
    ny17_count=ny17.get("w1_count")
    ny17_count=ny17_count if type(ny17_count) is int and ny17_count>=0 else None
    ny17_eligible=bool(ny17.get("adoption_ready") is True and
                       ny17.get("provider_session_verified") is True and
                       ny17.get("calendar_ready") is True and
                       ny17_count is not None and ny17_count>=35)
    w1=_structure(w1tech.get("structure")) if w1_ready else "unconfirmed"
    w1_context=("aligned" if focus and direction.get(w1)==focus else
                "countertrend" if focus and direction.get(w1) and direction[w1]!=focus else
                "unconfirmed")
    if focus and w1_context=="countertrend":
        reason += "。W1は監視方向と逆"
    elif focus and not w1_ready:
        reason += "。W1の35本・品質は未確認"
    # Scheduled grades are opportunities to REVIEW, not orders. Preserve formal
    # grade separately; no new price, SL or TP is inferred.
    if state=="directional_watch" and m15_status=="invalidated" and m15_direction_matches:
        state="skip"
        reason += "。M15参考診断で構造無効化"
        next_check="構造無効化後のH4/H1再評価"
    # Unassessed data is not a market rejection: keep the grade visible but
    # distinguish missing evidence from an invalidated trading idea.
    grade_reason=("data_unassessed" if state=="unassessed" else
                  "scenario_rejected" if state=="skip" else
                  "conditional_direction" if state=="conditional_watch" else
                  "direction_confirmed")
    if state in ("unassessed","skip"):
        scheduled_grade="D"
    elif state=="conditional_watch":
        scheduled_grade="C"
    elif higher_context=="aligned" and m15_status=="watch_pattern" and m15_delay==0:
        scheduled_grade="A"
    else:
        scheduled_grade="B"
    # No M15 pattern can turn a directional watch into an order instruction.
    setup=_dict(data.get("setup"))
    levels={}
    if valid_clock and focus and setup.get("direction")==focus:
        levels={"invalidation":_price(setup.get("invalidation")),
                "structural_target":_price(setup.get("structural_target")),
                "reference_rr":_price(setup.get("reference_rr"))}
    # Production scheduled context: visible in every pair's decision explanation.
    # Do not promote an indicator to a grade or execution authorization.
    macro_reference = _macro_reference(data, evaluated_at) if valid_clock else {}
    strategy_tracks=_strategy_tracks(structural,tfs,published,valid_clock,m15,m5_use)
    # A combined pair display must never use the H1 reference for its H4 track.
    for name,source in (("swing",_dict(data.get("h4_setup_shadow"))),
                        ("daytrade",setup)):
        track=strategy_tracks[name]
        matches=(track["base_verified"] and track["direction"] in ("long","short")
                 and source.get("direction")==track["direction"]
                 and (source.get("status")=="watch_only" if name=="swing" else source.get("stage")=="screening"))
        rr=source.get("reference_rr")
        track["reference_levels"]={
            "invalidation":_price(source.get("invalidation")),
            "structural_target":_price(source.get("structural_target")),
            "reference_rr":rr if type(rr) in (int,float) and math.isfinite(rr) else None,
            "executable_price":False} if matches else {}
        track["reference_timeframe"]=track["base_timeframe"]
        if name=="swing" and matches:
            track["reference_plan"]={k:v for k,v in _dict(source.get("reference_plan")).items() if k!="entry_permission"}
        track["saved_reference_close"]=_price(source.get("reference_close")) if matches else None
        own_plan=saved_price_plan(data,track,evaluated_at)
        if own_plan is not None:
            track["reference_plan"]=own_plan
            track["saved_reference_close"]=own_plan['reference_close']
            track["reference_levels"]={k:own_plan.get(k) for k in ('invalidation','structural_target','reference_rr')}
            track["reference_levels"]["executable_price"]=False
        track["trigger_price_reference"]=trigger_price_reference(data,track,evaluated_at)
    strategy_tracks["swing"]["reaction_timestamp"]=m15.get("m15_last_timestamp")
    m5_pattern=_dict(data.get("m5_price_action_shadow"))
    day=strategy_tracks["daytrade"]
    day["reaction_timestamp"]=m5_pattern.get("last_timestamp")
    day["invalidation_observed"]=(day["trigger_verified"] and m5_pattern.get("advisory_only") is True
        and m5_pattern.get("direction")==day["direction"] and m5_pattern.get("status")=="invalidated")
    if (day["direction"] and m5_pattern.get("advisory_only") is True
            and m5_pattern.get("direction")==day["direction"]
            and m5_pattern.get("status") in ("watch_pattern","waiting")):
        day["price_action"]={"status":m5_pattern["status"],
                             "pattern":m5_pattern.get("pattern"),
                             "last_timestamp":m5_pattern.get("last_timestamp"),
                             "reference_high":_price(m5_pattern.get("reference_high")),
                             "reference_low":_price(m5_pattern.get("reference_low")),
                             "observation_only":True}
    else:
        day["price_action"]={"status":"unverified","observation_only":True}

    counter=_dict(data.get("m5_counterpressure_shadow"))
    counter_valid=(day["direction"] and day["trigger_verified"] and
                   counter.get("observation_only") is True and
                   counter.get("direction")==day["direction"] and
                   type(counter.get("last_timestamp")) is int and
                   counter.get("last_timestamp")==day["price_action"].get("last_timestamp"))
    if counter_valid and counter.get("status") in ("counter_rebound","no_counter_rebound"):
        day["counterpressure"]={
            "status":counter["status"],"against_direction":counter.get("against_direction") is True,
            "last_timestamp":counter["last_timestamp"],"observation_only":True}
    else:
        day["counterpressure"]={"status":"unverified","observation_only":True}
    momentum=_dict(data.get("m5_rci_momentum_shadow"))
    momentum_valid=(day["direction"] and day["trigger_verified"] and
                    momentum.get("advisory_only") is True and
                    momentum.get("direction")==day["direction"] and
                    momentum.get("status")=="calculated" and
                    type(momentum.get("last_timestamp")) is int and
                    momentum.get("last_timestamp")==day["price_action"].get("last_timestamp"))
    day["rci_momentum"]=(
        {"status":"calculated","rci":momentum.get("rci",{}),
         "short_term_against_direction":momentum.get("short_term_against_direction"),
         "observation_only":True}
        if momentum_valid else {"status":"unverified","observation_only":True})
    rci9=_dict(_dict(day["rci_momentum"].get("rci")).get("9"))
    day["rci9_context"]=(
        {"movement":rci9["movement"],
         "against_direction":day["rci_momentum"].get("short_term_against_direction") is True,
         "one_bar_observation":True}
        if day["rci_momentum"].get("status")=="calculated" and
           rci9.get("movement") in ("rising","falling","flat")
        else {"movement":"unverified","one_bar_observation":True})
    day["timing_assessment"]=(
        "counter_rebound_wait" if day["counterpressure"].get("against_direction") is True
        else "pattern_observed" if day["price_action"].get("status")=="watch_pattern"
        else "timing_unverified")

    for track in strategy_tracks.values():
        apply_range(data, track, evaluated_at)
        track['price_reaction_observation'] = observe_saved_reaction(data, track, evaluated_at)
        track_direction=track["direction"]
        track["macro_context"]={
            "w1":{"verified":bool(w1_ready),"structure":w1,
                  "relation":("aligned" if track_direction and direction.get(w1)==track_direction
                              else "countertrend" if track_direction and direction.get(w1)
                              else "unconfirmed")},
            "d1":{"verified":bool(d1_ready),"structure":d1,
                  "relation":("aligned" if track_direction and direction.get(d1)==track_direction
                              else "countertrend" if track_direction and direction.get(d1)
                              else "unconfirmed")}}
        other_tf='h1' if track['base_timeframe']=='h4' else 'h4'
        other_verified=(valid_clock and _dict(tfs.get(other_tf)).get('ok') is True
                        and _dict(published.get(other_tf)).get('ok') is True
                        and _dict(structural.get(other_tf)).get('status')=='ok')
        other_structure=_structure(_dict(structural.get(other_tf)).get('structure')) if other_verified else 'unconfirmed'
        track['intermediate_context']={other_tf:{'verified':bool(other_verified),'structure':other_structure,
            'role':'lower_structure_context' if other_tf=='h1' else 'higher_structure_context',
            'relation':'aligned' if track_direction and direction.get(other_structure)==track_direction else
                       'countertrend' if track_direction and direction.get(other_structure) else 'unconfirmed'}}
        track["macro_veto"]=False
        track["macro_reference"]=macro_reference
        track["scenario_explanation"]=explain_strategy_track(track)
        track["rci_observation"]=rci_track_context(data, track, evaluated_at)
        track["indicator_context"]=strategy_indicator_context(data, track)
        track['condition_inputs'] = condition_inputs(data, track, evaluated_at)
    return {
        "strategy_tracks":strategy_tracks,
        "monitoring_macro_reference":macro_reference,
        "pair":pair,"state":state,"direction":focus,
        "explanation":reason,"next_check":next_check,
        "structure":{"d1":d1,"h4":h4,"h1":h1},
        "d1_verified":bool(d1_ready),"d1_context":higher_context,"m15_status":m15_status,
        "m15_observation_delay_minutes":m15_delay,
        "m15_diagnostic":m15_diagnostic,
        "m15_direction_matches":m15_direction_matches,
        "w1_verified":bool(w1_ready),"w1_context":w1_context,"w1_structure":w1,
        "w1_history":{"verified":bool(w1_ready),"observed_count":w1_count,
                      "required":35,"shortfall":w1_missing,
                      "session_contract":"not_established_by_count_alone",
                      "d1_verified_source_count":verified_d1,
                      "d1_retained_count":retained_d1,
                      "ny17_observed_w1_count":ny17_count,
                      "ny17_shortfall":max(0,35-ny17_count) if ny17_count is not None else None,
                      "ny17_independently_eligible":ny17_eligible},
        "scheduled_grade":scheduled_grade,"grade_reason":grade_reason,
        "grade_basis":"review_priority_not_execution",
        "data_status":"insufficient" if not ready else "usable_for_directional_review",
        "m5_required_for_directional_watch":False,
        "m5_timing":{"usage":m5_use,"age_minutes":age,
                     "thresholds_provisional":True},
        "reference_levels":levels,
        "observation_clock":evaluated_at,
        "current_actionability":"unverified",
        "advisory_only":True,
        "limitations":["保存時点のH4/H1構造であり現在の執行価格ではない",
                       "独立した経済指標・スプレッド・イベント検証なし",
                       "正式A/B判定・entry許可は変更しない"]
    }

def build_scheduled_outlook(pairs, quality, *, evaluated_at, economic_calendar=None):
    pairs,quality=_dict(pairs),_dict(quality)
    rows=[]
    for pair in PAIR_KEYS:
        try: rows.append(_one(pair,pairs.get(pair),quality.get(pair),evaluated_at))
        except (ValueError,KeyError,TypeError,AttributeError,OverflowError):
            rows.append(_one(pair,{}, {},evaluated_at))
    strength = build_contexts(pairs, evaluated_at) if type(evaluated_at) is int and evaluated_at > 0 else {}
    for row in rows:
        for strategy, track in row['strategy_tracks'].items():
            track['currency_strength_context'] = strength.get(row['pair'], {}).get(strategy)
    grade_counts={grade:sum(row["scheduled_grade"]==grade for row in rows)
                  for grade in ("A","B","C","D")}
    candidates=sorted(
        ({"pair":row["pair"],"grade":row["scheduled_grade"],
          "direction":row["direction"],"explanation":row["explanation"],
          "grade_reason":row["grade_reason"],
          "next_check":row["next_check"],"m15_status":row["m15_status"],
          "m15_diagnostic":row["m15_diagnostic"],
          "m5_timing":row["m5_timing"],"w1_history":row["w1_history"],
          "strategy_tracks":row["strategy_tracks"],
  "reference_levels":row["reference_levels"],
          }
         for row in rows if row["scheduled_grade"] in ("A","B","C") and row["direction"]),
        key=lambda row:("ABCD".index(row["grade"]),PAIR_KEYS.index(row["pair"])))
    strategy_candidates=[]
    for row in rows:
        for strategy in ("swing","daytrade"):
            track=row["strategy_tracks"][strategy]
            if track.get("direction") not in ("long","short") or track.get("state") not in ("watch","waiting_trigger"):
                continue
            if strategy=="swing" and track.get("trigger_status")=="invalidated":
                continue
            macro=track.get("macro_context",{})
            price_action=track.get("price_action",{}) if strategy=="daytrade" else {}
            trigger_ready=track.get("state")=="watch"
            pattern_confirmed=(price_action.get("status")=="watch_pattern" if strategy=="daytrade"
                               else track.get("trigger_status")=="watch_pattern")
            counter_wait=(strategy=="daytrade" and track.get("timing_assessment")=="counter_rebound_wait")
            priority=("counter_rebound_wait" if counter_wait else
                      "pattern_observed" if trigger_ready and pattern_confirmed else "directional_watch")
            strategy_candidates.append({
                "pair":row["pair"],"strategy":strategy,"direction":track["direction"],
                "priority":priority,"state":track["state"],
                "macro_context":macro,"macro_reference":track.get("macro_reference",{}),
                "base_structure":track.get("base_structure"),
                "trigger_status":track.get("trigger_status"),
                "price_action":price_action,
                "timing_assessment":track.get("timing_assessment","timing_unverified"),
                "counterpressure":track.get("counterpressure",{}),
                "rci_momentum":track.get("rci_momentum",{}),
                "rci9_context":track.get("rci9_context",{}),
                "reference_levels":track.get("reference_levels",{}),
                "reference_timeframe":track["reference_timeframe"],
                "reference_plan":track.get("reference_plan",{}),
                "scenario_explanation":track["scenario_explanation"],
                "rci_observation":track["rci_observation"],
                "indicator_context":track["indicator_context"],
                "next_check":("M15確定足で価格反応を確認" if strategy=="swing" else
                              "M5反発終了・下落再開を確定足で確認" if counter_wait and track["direction"]=="short" else
                              "M5押し目終了・上昇再開を確定足で確認" if counter_wait else
                              "M5確定足で価格反応を確認"),
                })
    strategy_assessments=[assess_strategy(row['pair'],strategy,row['strategy_tracks'][strategy],evaluated_at)
                          for row in rows for strategy in ('swing','daytrade')]
    # The validated raw window is transient. History retains only the compact
    # condition levels and observation evidence, never source candle arrays.
    for row in rows:
        for track in row['strategy_tracks'].values():
            track.pop('condition_inputs', None)
    for row in rows:
        row['strategy_assessments']={r['strategy']:r for r in strategy_assessments if r['pair']==row['pair']}
    review_keys={(a['pair'],a['strategy']) for a in strategy_assessments if a['assessment']=='review'}
    strategy_candidates=[c for c in strategy_candidates if (c['pair'],c['strategy']) in review_keys]
    assessed={(a['pair'],a['strategy']):a for a in strategy_assessments}
    for candidate in strategy_candidates:
        context=assessed[(candidate['pair'],candidate['strategy'])]['currency_strength_context']
        candidate['currency_strength_context']=context
    strategy_candidates.sort(key=lambda c:({"pattern_observed":0,"directional_watch":1,"counter_rebound_wait":2}[c["priority"]],
                                           c['currency_strength_context']['comparison_priority'],
                                           PAIR_KEYS.index(c["pair"]),c["strategy"]))
    outlook = {"schema":"scheduled_outlook_v1","evaluated_at":evaluated_at,
            "grade_counts":grade_counts,"candidate_count":len(candidates),
            "candidates":candidates,"strategy_candidates":strategy_candidates,
            "strategy_candidate_count":len(strategy_candidates),
            "strategy_assessments":strategy_assessments,
            "strategy_assessment_count":len(strategy_assessments),
            "assessment_candidates":[{k:r[k] for k in ('pair','strategy','direction','grade','grade_reason')}
                                     for r in strategy_assessments if r['assessment']=='review'],
            "assessment_counts":{state:sum(r['assessment']==state for r in strategy_assessments)
                                 for state in ('evaluation_pending','skip','review')},
            "canonical_assessment_field":"strategy_assessments",
            "legacy_compatibility":{"scheduled_grade":"Pair A-D is historical display only; use strategy_assessments for independent A/B/C",
                "removal_condition":"Scheduled task and history readers must consume strategy_assessments before pair fields are removed"},
            "advisory_only":True,
            "rows":rows,"counts":{state:sum(r["state"]==state for r in rows)
                for state in ("directional_watch","conditional_watch","skip","unassessed")},
            "note":"Saved H4/H1 directional research, not current M15/M5 entry or execution clearance"}


    if economic_calendar is not None:
        from .economic_calendar_context import enrich_outlook
        return enrich_outlook(outlook, economic_calendar)
    return outlook
