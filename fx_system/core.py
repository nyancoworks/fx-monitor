from __future__ import annotations
import datetime as dt
import math

from .monitor_pairs import PAIRS
INTERVALS = {"m5":300,"m15":900,"h1":3600,"h4":14400,"d1":86400,"w1":604800}
MIN_BARS = {"m5":24,"m15":24,"h1":24,"h4":12,"d1":60,"w1":35}
MAX_AGE_MIN = {"m5":15,"m15":30,"h1":90,"h4":300,"d1":2160,"w1":11520}

def expected_closed_timestamp(timeframe, now):
    """Legacy UTC grid, not an attestation of native provider daily sessions."""
    stamp=(int(now)//INTERVALS[timeframe]-1)*INTERVALS[timeframe]
    if timeframe=="d1":
        while dt.datetime.fromtimestamp(stamp,dt.timezone.utc).weekday()>=5:
            stamp-=86400
    return stamp

def parse_row(item, interval_seconds, now):
    try:
        raw = item["datetime"].replace(" ", "T") + "Z"
        stamp = int(dt.datetime.fromisoformat(raw.replace("Z","+00:00")).timestamp())
        values = [float(item[k]) for k in ("open","high","low","close")]
        if stamp % interval_seconds or stamp + interval_seconds > now or not all(math.isfinite(x) and x>0 for x in values):
            return None
        o,h,l,c=values
        if h < max(o,c) or l > min(o,c):
            return None
        return {"timestamp":stamp,"open":o,"high":h,"low":l,"close":c}
    except (ValueError,TypeError,KeyError,OverflowError):
        return None

def aggregate(rows, source_seconds, target_seconds, min_parts=None):
    if target_seconds % source_seconds: raise ValueError("invalid interval ratio")
    required=min_parts or target_seconds//source_seconds
    buckets={}
    for row in rows:
        t=row["timestamp"]//target_seconds*target_seconds
        buckets.setdefault(t,{})[row["timestamp"]]=row
    out=[]
    for t,items in sorted(buckets.items()):
        expected=[t+i*source_seconds for i in range(required)]
        if any(k not in items for k in expected):continue
        group=[items[k] for k in expected]
        out.append({"timestamp":t,"open":group[0]["open"],"high":max(x["high"] for x in group),"low":min(x["low"] for x in group),"close":group[-1]["close"]})
    return out

def weekly(daily, now=None):
    groups={}
    for r in daily:
        date=dt.datetime.fromtimestamp(r["timestamp"],dt.timezone.utc).date()
        monday=date-dt.timedelta(days=date.weekday())
        t=int(dt.datetime.combine(monday,dt.time(),dt.timezone.utc).timestamp())
        groups.setdefault(t,[]).append(r)
    out=[]
    for t,items in sorted(groups.items()):
        if now is not None and t + 7*86400 > now:
            continue  # Current week is not yet complete.
        items.sort(key=lambda x:x["timestamp"])
        # A completed calendar week can legitimately have fewer trading days
        # around holidays. Preserve the candle, but flag missing weekdays.
        weekdays={dt.datetime.fromtimestamp(x["timestamp"],dt.timezone.utc).weekday() for x in items}
        if not weekdays:continue
        out.append({"timestamp":t,"open":items[0]["open"],"high":max(x["high"] for x in items),"low":min(x["low"] for x in items),"close":items[-1]["close"],"weekday_count":len(weekdays),"missing_weekdays":sorted({0,1,2,3,4}-weekdays)})
    return out

def assess(rows,tf,now):
    rows=sorted(rows,key=lambda x:x["timestamp"])
    last=rows[-1]["timestamp"] if rows else None
    age=(now-(last+INTERVALS[tf]))/60 if last is not None else None
    # Measure freshness from the close of the latest completed candle.
    fresh=age is not None and 0<=age<=MAX_AGE_MIN[tf]
    sufficient=len(rows)>=MIN_BARS[tf]
    return {"ok":fresh and sufficient,"fresh":fresh,"structure_sufficient":sufficient,"count":len(rows),"age_minutes":round(age,2) if age is not None else None}

def ema_series(values, period):
    """Legacy JS parity: SMA-seeded EMA, with no values before period-1."""
    if not isinstance(period,int) or period<1:
        raise ValueError("period must be positive integer")
    out=[None]*len(values)
    if len(values)<period:
        return out
    v=sum(values[:period])/period
    out[period-1]=v
    alpha=2/(period+1)
    for i in range(period,len(values)):
        v=values[i]*alpha+v*(1-alpha)
        out[i]=v
    return out


def closed_structure_state(rows, historical_structure, highs, lows):
    """Historical pivots do not attest that their structure remains intact.

    Read only completed inputs. A close breach after pivot confirmation stays
    broken against that same pivot; a bounce alone is not verified recovery.
    This diagnostic never reverses direction or grants entry permission.
    """
    result={"state":"unknown","historical_structure":historical_structure,
            "basis":"completed_close_vs_confirmed_pivot","entry_permission":False}
    if not rows or historical_structure not in ('HH_HL','LH_LL'):
        return result
    pivots=lows if historical_structure=='HH_HL' else highs
    if not pivots:return result
    pivot=pivots[-1]
    positions=[i for i,r in enumerate(rows) if r['timestamp']==pivot['timestamp']]
    if not positions or positions[0]+2>=len(rows):return result
    confirmed=rows[positions[0]+2]['timestamp']
    subsequent=rows[positions[0]+3:]
    broken=[r for r in subsequent if (r['close']<pivot['price'] if historical_structure=='HH_HL' else r['close']>pivot['price'])]
    latest=rows[-1]
    result.update({"state":"broken" if broken else "at_boundary" if latest['close']==pivot['price'] else "intact",
                   "pivot_timestamp":pivot['timestamp'],"confirmation_bar_timestamp":confirmed,
                   "evaluated_bar_timestamp":latest['timestamp'],
                   "break_bar_timestamp":broken[0]['timestamp'] if broken else None,
                   "recovery_verified":False if broken else None})
    return result


def technical(rows):
    """Completed-candle ATR(14) and confirmed 2-left/2-right swings.
    Advisory indicators only: not an A/B entry signal.
    """
    r=sorted(rows,key=lambda x:x["timestamp"])
    if len(r)<15:
        return {"status":"insufficient","count":len(r),"required":15}
    tr=[max(r[i]["high"]-r[i]["low"],abs(r[i]["high"]-r[i-1]["close"]),abs(r[i]["low"]-r[i-1]["close"])) for i in range(1,len(r))]
    atr=sum(tr[-14:])/14
    highs=[{"timestamp":r[i]["timestamp"],"price":r[i]["high"]} for i in range(2,len(r)-2) if all(r[i]["high"]>r[j]["high"] for j in (i-2,i-1,i+1,i+2))]
    lows=[{"timestamp":r[i]["timestamp"],"price":r[i]["low"]} for i in range(2,len(r)-2) if all(r[i]["low"]<r[j]["low"] for j in (i-2,i-1,i+1,i+2))]
    structure="unconfirmed"
    if len(highs)>=2 and len(lows)>=2:
        h0,h1=highs[-2:];l0,l1=lows[-2:]
        structure="HH_HL" if h1["price"]>h0["price"] and l1["price"]>l0["price"] else "LH_LL" if h1["price"]<h0["price"] and l1["price"]<l0["price"] else "mixed"
    return {"status":"ok","count":len(r),"atr14":atr,"confirmed_swing_highs":highs[-2:],"confirmed_swing_lows":lows[-2:],"structure":structure,
            "historical_swing_structure":structure,"closed_bar_structure":closed_structure_state(r,structure,highs,lows),
            "basis":"completed_candles","advisory_only":True}


def screen_setup(frames, now):
    """Conservative H1 setup screening, not an execution instruction.

    H4/D1 supply context; confirmed H1 pivots establish structure and
    invalidation. M5 is intentionally reserved for a separate entry check.
    """
    h1=frames.get("h1",[])
    h4=frames.get("h4",[])
    if len(h1)<35 or len(h4)<15:
        return {"grade":"C","stage":"screening","reason":"insufficient H1/H4 history","entry_confirmed":False}
    h=technical(h1)
    higher=technical(h4)
    structure=h.get("structure")
    direction={"HH_HL":"long","LH_LL":"short"}.get(structure)
    if not direction:
        return {"grade":"C","stage":"screening","reason":"H1 confirmed swing direction unclear","entry_confirmed":False}
    swings=h["confirmed_swing_lows"] if direction=="long" else h["confirmed_swing_highs"]
    if not swings:
        return {"grade":"C","stage":"screening","reason":"H1 invalidation swing missing","entry_confirmed":False}
    invalidation=swings[-1]["price"]
    close=h1[-1]["close"]
    risk=(close-invalidation) if direction=="long" else (invalidation-close)
    if risk<=0:
        return {"grade":"D","stage":"screening","direction":direction,"reason":"H1 invalidation breached","entry_confirmed":False}
    atr=h["atr14"]
    if atr<=0 or risk>3*atr:
        return {"grade":"C","stage":"screening","direction":direction,"reason":"H1 stop distance needs review","invalidation":invalidation,"entry_confirmed":False}
    higher_direction={"HH_HL":"long","LH_LL":"short"}.get(higher.get("structure"))
    # Issue57 user-approved long-candidate suppression only. Historical H4
    # structure is retained, but never treated as intact after a close breach.
    # Do not turn an invalidated long into a short or promote C into A/B.
    if direction=='long' and higher.get('closed_bar_structure',{}).get('state')=='broken':
        return {"grade":"C","stage":"screening","direction":None,
                "historical_direction":"long","h4_structure":higher.get('structure'),
                "h4_closed_bar_structure":higher['closed_bar_structure'],
                "reason":"H4 confirmed-close structure invalidated; long candidate suppressed",
                "entry_confirmed":False}
    if higher_direction and higher_direction!=direction:
        return {"grade":"C","stage":"screening","direction":direction,
                "invalidation":invalidation,"h4_structure":higher.get("structure"),
                "reason":"H4 opposes H1; context and risk require review",
                "entry_confirmed":False}
    # A structural target must be a confirmed H1/H4 pivot beyond the reference
    # price, not a synthetic RR multiple or arbitrary projected price.
    target_key="confirmed_swing_highs" if direction=="long" else "confirmed_swing_lows"
    candidates=[p["price"] for analysis in (h,higher)
                for p in analysis.get(target_key,[])
                if (p["price"]>close if direction=="long" else p["price"]<close)]
    if not candidates:
        return {"grade":"C","stage":"screening","direction":direction,
                "invalidation":invalidation,"reference_close":close,
                "reason":"No confirmed structural target ahead of reference price",
                "entry_confirmed":False}
    target=min(candidates) if direction=="long" else max(candidates)
    reward=(target-close) if direction=="long" else (close-target)
    rr=reward/risk
    if rr<1.5:
        return {"grade":"C","stage":"screening","direction":direction,
                "invalidation":invalidation,"structural_target":target,
                "reference_rr":round(rr,2),
                "reason":"Confirmed structural target offers RR below 1.5",
                "entry_confirmed":False}
    return {"grade":"C","stage":"screening","direction":direction,
            "reference_close":close,"invalidation":invalidation,
            "risk_distance":round(risk,8),"h1_atr14":atr,
            "h4_structure":higher.get("structure"),
            "structural_target":target,"reference_rr":round(rr,2),
            "reason":"H1 structure and structural RR checked; waiting zone, macro and event clearance unverified",
            "entry_confirmed":False}


def confirm_m5_entry(setup, m5, now, min_rr=1.5):
    """Legacy-compatible M5 pattern diagnostic, independent of canonical A/B/C.

    Require multiple completed bars, a genuine pullback and renewed direction,
    or break/retest/hold/follow-through. This compatibility result does not
    classify the independent swing/daytrade scenarios or authorize execution.
    """
    diagnostic_ready=(setup.get("stage")=="screening" and setup.get("direction") in ("long","short") and isinstance(setup.get("invalidation"),(int,float)) and isinstance(setup.get("structural_target"),(int,float)))
    if not diagnostic_ready and setup.get("grade") not in ("A_candidate","B"):
        return {"grade":"C","entry_confirmed":False,"reason":"H1 structural setup insufficient for M5 diagnostic"}
    if len(m5) < MIN_BARS["m5"]:
        return {"grade":"C","entry_confirmed":False,"reason":"M5 history insufficient"}
    rows=sorted(m5,key=lambda r:r["timestamp"])
    last=rows[-1]
    if last["timestamp"]+300>now or now-(last["timestamp"]+300)>MAX_AGE_MIN["m5"]*60:
        return {"grade":"C","entry_confirmed":False,"reason":"M5 completed candles stale"}
    if any(b["timestamp"]-a["timestamp"]!=300 for a,b in zip(rows[-5:-1],rows[-4:])):
        return {"grade":"C","entry_confirmed":False,"reason":"M5 trigger sequence contains gaps"}
    direction=setup.get("direction")
    if direction not in ("long","short"):
        return {"grade":"C","entry_confirmed":False,"reason":"H1 direction unavailable"}
    a,b,d,e=rows[-4:]
    # Pullback reversal requires a counter-direction candle followed by two
    # directional closes, including a close through the counter candle extreme.
    if direction=="long":
        pullback=(a["close"]<a["open"] and d["close"]>d["open"] and
                  e["close"]>e["open"] and d["close"]>a["close"] and
                  e["close"]>a["high"] and e["close"]>d["close"])
        # Break, return to the broken level, hold, and subsequent follow-through.
        level=a["high"]
        retest=(b["close"]>level and d["low"]<=level and d["close"]>=level and
                e["close"]>max(b["close"],d["high"]))
    else:
        pullback=(a["close"]>a["open"] and d["close"]<d["open"] and
                  e["close"]<e["open"] and d["close"]<a["close"] and
                  e["close"]<a["low"] and e["close"]<d["close"])
        level=a["low"]
        retest=(b["close"]<level and d["high"]>=level and d["close"]<=level and
                e["close"]<min(b["close"],d["low"]))
    if not (pullback or retest):
        return {"grade":"C","entry_confirmed":False,"reason":"M5 multi-candle pullback or break/retest/follow-through not confirmed"}
    entry=e["close"]
    sl=setup.get("invalidation")
    tp=setup.get("structural_target")
    if not isinstance(sl,(int,float)) or (entry<=sl if direction=="long" else entry>=sl):
        return {"grade":"D","entry_confirmed":False,"reason":"H1 structural invalidation missing or breached"}
    if not isinstance(tp,(int,float)):
        return {"grade":"C","entry_confirmed":False,"reason":"M5 pattern detected but structural TP unverified","pattern":"pullback" if pullback else "break_retest"}
    risk=abs(entry-sl)
    reward=(tp-entry) if direction=="long" else (entry-tp)
    rr=reward/risk
    if rr<min_rr:
        return {"grade":"D","entry_confirmed":False,"reason":"structural target RR below minimum","rr":round(rr,2)}
    # Keep the compatibility grade unchanged; canonical strategy assessment is
    # computed separately from this pattern observation.
    return {"grade":"C","entry_confirmed":False,"pattern":"pullback" if pullback else "break_retest",
            "entry":entry,"sl":sl,"tp":tp,"rr":round(rr,2),
            "reason":"M5 reference pattern detected; independent scenario assessment is reported separately"}


def ny17_frames(study, now):
    """Distinct NY-close schema; never route these candles through UTC D1 parsing.

    Input must be freshly reconstructed from the validated private H1 archive.
    The timestamp is session OPEN, while closedness uses the explicit NY end.
    """
    from zoneinfo import ZoneInfo
    ny=ZoneInfo("America/New_York")
    frames={"d1":[],"w1":[]}
    for tf in frames:
        previous=-1
        for bar in study[tf]:
            if tf=="d1":
                day=dt.date.fromisoformat(bar["trading_date_ny"])
                end=int(dt.datetime.combine(day,dt.time(17),ny).timestamp())
                start=end-86400
                if day.weekday()>4 or bar["h1_count"]!=24 or bar["session_start_utc"]!=start or bar["session_end_utc"]!=end:
                    raise ValueError("invalid NY daily session")
            else:
                monday=dt.date.fromisoformat(bar["week_start_ny"])
                end=int(dt.datetime.combine(monday+dt.timedelta(days=4),dt.time(17),ny).timestamp())
                start=int(dt.datetime.combine(monday,dt.time(17),ny).timestamp())-86400
                if monday.weekday()!=0 or bar["d1_count"]!=5 or bar["close_utc"]!=end:
                    raise ValueError("invalid NY weekly session")
            values=[bar["ohlc"][k] for k in ("open","high","low","close")]
            if start<=previous or end>now or not all(type(v) in (int,float) and math.isfinite(v) and v>0 for v in values):
                raise ValueError("invalid NY candle")
            o,h,l,c=values
            if l>min(o,c) or h<max(o,c):raise ValueError("invalid NY OHLC")
            frames[tf].append(dict(timestamp=start,session_end_utc=end,open=o,high=h,low=l,close=c))
            previous=start
    return frames
