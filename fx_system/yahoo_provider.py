"""Optional Yahoo Finance FX chart rescue (unofficial, best effort)."""
from __future__ import annotations
import requests

SETTINGS={"m5":("5m","5d",300),"h1":("60m","1mo",3600)}

def fetch_yahoo(session,pair,timeframe,now):
    if timeframe not in SETTINGS:
        raise ValueError("unsupported timeframe")
    if len(pair)!=7 or pair[3]!="/" or not pair.replace("/","").isalpha():
        raise ValueError("invalid FX pair")
    interval,period,seconds=SETTINGS[timeframe]
    symbol=pair.replace("/","")+"=X"
    response=session.get(
        "https://query2.finance.yahoo.com/v8/finance/chart/"+symbol,
        params={"interval":interval,"range":period},
        headers={"User-Agent":"Mozilla/5.0 (compatible; FX-data-check/1.0)"},
        timeout=(3,8))
    response.raise_for_status()
    payload=response.json()["chart"]
    if payload.get("error"):
        raise ValueError("Yahoo chart error")
    result=payload["result"][0]
    times=result.get("timestamp",[])
    quote=result["indicators"]["quote"][0]
    bars=[]
    for i,ts in enumerate(times):
        try:
            timestamp=int(ts)
            if timestamp%seconds or timestamp+seconds>now:
                continue
            o,h,l,c=(float(quote[k][i]) for k in ("open","high","low","close"))
            if not (0<l<=min(o,c)<=max(o,c)<=h):
                continue
            bars.append({"timestamp":timestamp,"open":o,"high":h,"low":l,"close":c})
        except (ValueError,TypeError,IndexError,KeyError):
            continue
    return sorted({b["timestamp"]:b for b in bars}.values(),key=lambda b:b["timestamp"])
