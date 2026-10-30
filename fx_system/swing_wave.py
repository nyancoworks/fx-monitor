"""H4 price response for swing maturity; M15 timing cannot supply it."""
import math

METHOD = 'contextual_scenario_review_v9_swing_wave'
SECONDS = 14400


def _price(v):
    return type(v) in (int, float) and math.isfinite(v) and v > 0


def wave_inputs(data, track, clock):
    rows = data.get('h4', {}).get('candles', [])
    return {'evaluated_at': clock, 'quality_verified': track.get('base_verified') is True,
            'bars': [{k: b.get(k) for k in ('timestamp','open','high','low','close')}
                     for b in rows[-4:] if isinstance(b, dict)] if isinstance(rows, list) else []}


def build_wave(record):
    clock=record.get('evaluated_at');direction=record.get('direction')
    inp=record.get('swing_wave_inputs', {})
    inp=inp if isinstance(inp,dict) else {}
    bars=inp.get('bars', [])
    out={'schema':'saved_swing_wave_v1','evaluated_at':clock,'timeframe':'h4',
         'status':'unverified','response':None,'closed_at':None,'level':None,
         'intended_horizon':'multi_session_h4_wave','holding_duration':'not_estimated',
         'summary':'H4の波の確認材料が不足。M15の反応だけでスイングAにしない',
         'not_order_or_profitability':True}
    plan=record.get('reference_plan', {})
    if (record.get('base_quality_verified') is not True or inp.get('quality_verified') is not True
            or inp.get('evaluated_at') != clock or type(clock) is not int
            or direction not in ('long','short')
            or {'HH_HL':'long','LH_LL':'short'}.get(record.get('base_structure')) != direction
            or record.get('reference_timeframe') != 'h4' or record.get('trigger_timeframe') != 'm15'
            or not isinstance(bars,list) or len(bars)!=4):
        return out
    for b in bars:
        if not isinstance(b,dict):return out
        ts=b.get('timestamp');v=[b.get(k) for k in ('open','high','low','close')]
        if type(ts) is not int or ts<=0 or ts%SECONDS or not all(_price(x) for x in v):return out
        o,h,l,c=v
        if not l<=min(o,c)<=max(o,c)<=h:return out
    if any(b['timestamp']-a['timestamp']!=SECONDS for a,b in zip(bars,bars[1:])):return out
    last=bars[-1];closed=last['timestamp']+SECONDS
    if (not 0<=clock-closed<SECONDS or last['timestamp']!=plan.get('reference_close_timestamp')
            or last['close']!=plan.get('reference_close')):return out
    long=direction=='long';sign=1 if long else -1
    # Both alternatives are price-action patterns on one timeframe, not votes
    # or an all-indicator agreement requirement.
    breakout=(max(b['high'] for b in bars[:-1]) if long else min(b['low'] for b in bars[:-1]))
    rejection=(min(b['low'] for b in bars[-3:-1]) if long else max(b['high'] for b in bars[-3:-1]))
    body=sign*(last['close']-last['open'])>0
    break_seen=body and sign*(last['close']-breakout)>0
    retracement=any(sign*(b['close']-b['open'])<0 for b in bars[:-1])
    reject_seen=(body and retracement and sign*(last['low' if long else 'high']-rejection)<=0
                 and sign*(last['close']-rejection)>0)
    response='close_breakout' if break_seen else 'pullback_rejection' if reject_seen else None
    against=sign*(last['close']-last['open'])<0 or sign*(last['close']-bars[-2]['close'])<0
    status='response_confirmed' if response else 'pullback_in_progress' if against else 'response_wait'
    out.update(status=status,response=response,closed_at=closed,
               level=breakout if break_seen else rejection if reject_seen else None,
               summary=('H4確定足で方向への価格反応を確認。M15で仕掛け条件と余地を別確認' if response else
                        'H4は押し戻り中。H4での反応を待ち、M15だけの成立をスイングAにしない' if against else
                        'H4の方向構造はあるが波の再開反応は未確認。H4確定足で反応待ち'))
    return out
