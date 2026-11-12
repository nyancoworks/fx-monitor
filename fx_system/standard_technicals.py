"""Standard-only technical profile. Historical interpreters are separate readers."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo
import math
import json
from functools import lru_cache
from .indicator_research import super_bollinger_context,rci_series,_rci_observation
from .scenario_conditions import condition_inputs,describe_conditions
from .strategy_strength import interpret

METHOD='contextual_scenario_review_v13_standard_technicals'
SECONDS={'m5':300,'m15':900,'h1':3600,'h4':14400,'d1':86400,'w1':604800}
PROFILE={'super_bollinger':[21,21],'macd':[12,26,9],'sma':[50,200],'rci':[9,26,52],'fibonacci':'standard'}
NY_CLOSE_PROFILE={**PROFILE,'macd_signal':'EMA9','h4_calendar':'mt4_ny_close_h4_v1'}

def ema(values,period):
    out=[None]*len(values)
    if len(values)<period:return out
    current=sum(values[:period])/period;out[period-1]=current
    for i in range(period,len(values)):
        current+=(values[i]-current)*2/(period+1);out[i]=current
    return out


def macd(closes):
    fast,slow=ema(closes,12),ema(closes,26)
    line=[a-b if a is not None and b is not None else None for a,b in zip(fast,slow)]
    start=next((i for i,x in enumerate(line) if x is not None),len(line))
    signal=[None]*start+ema(line[start:],9)
    return [{'line':a,'signal':b,'histogram':a-b if a is not None and b is not None else None}
            for a,b in zip(line,signal)]


def _calculate_frame(rows,tf,clock,verified,calendar=None,calculation_version=1):
    if type(calculation_version) is not int or calculation_version not in (1,2,3):raise ValueError("unsupported calculation version")
    out={'timeframe':tf,'evaluated_at':clock,'calendar':calendar,'verified':verified is True,'status':'unverified','bars':[]}
    if calculation_version in (2,3):out['calculation_version']=calculation_version
    if not isinstance(rows,list) or not rows:return out
    if any(not isinstance(b,dict) or type(b.get('timestamp')) is not int
           or not all(type(b.get(k)) in (int,float) and math.isfinite(b[k]) and b[k]>0 for k in ('open','high','low','close'))
           or not b['low']<=min(b['open'],b['close'])<=max(b['open'],b['close'])<=b['high'] for b in rows):return out
    # Caller supplies a verified contiguous suffix (including NY17 session semantics).
    if any(b['timestamp']<=a['timestamp'] for a,b in zip(rows,rows[1:])):return out
    c=[b['close'] for b in rows];m=macd(c)
    smas={str(p):{'value':sum(c[-p:])/p if len(c)>=p else None,
                    'previous':sum(c[-p-1:-1])/p if len(c)>p else None} for p in (50,200)}
    for v in smas.values():
        v['slope']='up' if v['value'] is not None and v['previous'] is not None and v['value']>v['previous'] else 'down' if v['value'] is not None and v['previous'] is not None and v['value']<v['previous'] else 'flat' if v['previous'] is not None else 'unverified'
    sb_calendar=calendar
    if calculation_version==3 and tf=='h4' and calendar=='mt4_ny_close_h4_v1':
        from .mt4_calendar import CONTINUITY
        sb_calendar=CONTINUITY
    sb=super_bollinger_context(rows,timeframe=tf,calendar=sb_calendar)
    previous_sb=super_bollinger_context(rows[:-1],timeframe=tf,calendar=sb_calendar)
    if sb.get('status')=='calculated' and previous_sb.get('status')=='calculated':
        delta=sb['bandwidth_3sigma']-previous_sb['bandwidth_3sigma']
        sb['bandwidth_state']='expanding' if delta>0 else 'contracting' if delta<0 else 'flat'
    out.update(status='available' if verified and len(c)>=35 else 'unverified',
        closed_at=rows[-1].get('session_end_utc',rows[-1]['timestamp']+SECONDS[tf]),bars=[{k:b[k] for k in ('timestamp','open','high','low','close','session_end_utc') if k in b} for b in rows],
        super_bollinger=sb,sma=smas,
        macd={'parameters':[12,26,9],'ema_seed':'full_verified_prefix_sma','observations':m[-3:]},
        rci={str(p):_rci_observation(rci_series(c,p)) for p in (9,26,52)})
    return out


@lru_cache(maxsize=128)
def _cached_frame(payload,tf,clock,verified,calendar,calculation_version):
    return _calculate_frame(json.loads(payload),tf,clock,verified,calendar,calculation_version)


def frame(rows,tf,clock,verified,calendar=None,calculation_version=1):
    return deepcopy(_cached_frame(json.dumps(rows,sort_keys=True,separators=(',',':'),allow_nan=False),tf,clock,verified,calendar,calculation_version))


def prepare(data,verified,indicator_frames,quality):
    clock=quality.get('evaluated_at')
    data['standard_technical_version']=1
    data['standard_technical_frames']={tf:frame(indicator_frames[tf],tf,clock,
        quality.get('timeframes',{}).get(tf,{}).get('ok') is True,
        quality.get('timeframes',{}).get(tf,{}).get('calendar'),calculation_version=3) for tf in SECONDS}
    # No retired indicator observations survive in a newly generated market view.
    for key in ('advisory_indicators','indicator_research','dinapoli_research','dinapoli_indicator_reference',
                'span_model_version','span_model_inputs','forecast_wave_inputs','base_evolution_inputs',
                'indicator_context_version','h4_setup_shadow','setup_comparison','multitimeframe_shadow'):
        data.pop(key,None)


def bollinger_regime(sb):
    """FX Monitor interpretation of lagging-span and closing-price positions."""
    lag = sb.get('lagging_span', {}).get('location')
    close = sb.get('last_close')
    middle = sb.get('centerline')
    bands = sb.get('bands', {})
    one, two = bands.get('1', {}), bands.get('2', {})
    values = (close, middle, one.get('lower'), one.get('upper'), two.get('lower'), two.get('upper'))
    if (sb.get('status') != 'calculated' or lag not in ('above', 'below', 'inside')
            or not all(type(v) in (int, float) and math.isfinite(v) for v in values)):
        return None, 'unverified'
    if lag == 'inside':
        return None, 'range' if one['lower'] <= close <= one['upper'] else 'transition'
    long = lag == 'above'
    trend = 'long' if long else 'short'
    if (close < middle if long else close > middle):
        return ('short' if long else 'long'), 'correction'
    outside_two = close > two['upper'] if long else close < two['lower']
    outside_one = close > one['upper'] if long else close < one['lower']
    if outside_two and sb.get('bandwidth_state') == 'expanding':
        return trend, 'expanding_trend'
    return trend, 'trend' if outside_one else 'gradual_trend'


def forecast(f,structure, *, structure_state=None, bollinger_regimes=False, setup_synthesis=False):
    sb=f.get('super_bollinger',{});m=f.get('macd',{}).get('observations',[])
    hist=[x.get('histogram') for x in m]
    direction={'up':'long','down':'short'}.get(sb.get('centerline_direction'))
    status=f.get('status')=='available' and sb.get('status')=='calculated' and len(hist)==3 and all(type(h) in (int,float) for h in hist)
    center=direction;basis='sb_environment'
    regime = None
    if bollinger_regimes:
        direction, regime = bollinger_regime(sb)
        basis = 'sb_regime'
        status = status and regime != 'unverified'
    slow=f.get('sma',{}).get('50',{});rows=f.get('bars',[])
    slow_direction=('long' if slow.get('slope')=='up' and slow.get('value') is not None and rows and rows[-1]['close']>slow['value'] else
                    'short' if slow.get('slope')=='down' and slow.get('value') is not None and rows and rows[-1]['close']<slow['value'] else None)
    # A recovering price/medium background with directional momentum may
    # challenge SB. This is a reversal hypothesis, not a vote or proven turn.
    if not bollinger_regimes and status and slow_direction and slow_direction!=center:
        candidate=[(1 if slow_direction=='long' else -1)*v for v in hist]
        if candidate[-1]>0 and candidate[0]<candidate[1]<candidate[2]:
            direction=slow_direction;basis='sma50_macd_reversal_hypothesis'
    sign=1 if direction=='long' else -1
    h=[sign*v for v in hist] if status and direction else []
    momentum=('neutral' if h[-1]==0 else 'counterpressure_deepening' if h[-1]<0 and h[0]>h[1]>h[2] else
              'counterpressure_easing' if h[-1]<0 and h[0]<h[1]<h[2] else
              'counterpressure_mixed' if h[-1]<0 else
              'directional_building' if h[0]<h[1]<h[2] else
              'directional_fading' if h[0]>h[1]>h[2] else 'directional_mixed') if h else 'unverified'
    phase={'counterpressure_deepening':'pullback_deepening','counterpressure_easing':'pullback_easing',
           'counterpressure_mixed':'pullback_unsettled','directional_fading':'pullback_expected',
           'directional_building':'continuation','neutral':'momentum_neutral','directional_mixed':'reacceleration_unconfirmed'}.get(momentum,'unverified')
    texts={'pullback_deepening':'MACDの逆行が拡大。調整継続を先に想定し、回復を先取りしない',
           'pullback_easing':'MACD逆行が鈍化。調整の減速を想定するが再開確定ではない',
           'pullback_unsettled':'MACDは逆行側で変化が混在。調整収束は未確認',
           'pullback_expected':'方向側MACDが減速。押し戻り・もみ合いを先に想定',
           'continuation':'方向側MACDの勢いが改善。途中障害の反応と継続を監視',
           'reacceleration_unconfirmed':'方向側MACDの変化が混在。再加速を断定しない','momentum_neutral':'MACDヒストグラムは中立。方向再開の勢いは未確認','unverified':'方向や勢いの主要材料不足'}
    cautions=[];support=[];material=[]
    if regime is not None:
        label = {'unverified':'判定材料不足','range':'レンジ','transition':'移行中',
                 'correction':'調整波','trend':'トレンド','gradual_trend':'緩やかなトレンド',
                 'expanding_trend':'バンド拡大を伴うトレンド'}[regime]
        support.append('SB局面：'+label)
    if center:support.append('SB中心線'+sb['centerline_direction']+'を環境として参照（予測方向と一致するとは限らず、独立票にはしない）')
    if sb.get('status')=='calculated':
        support.append('SB遅行は過去足の'+str(sb.get('lagging_span',{}).get('location'))+'、帯幅は'+str(sb.get('bandwidth_state','unverified'))+'。位置と拡がりを一つの環境として読む')
    short=f.get('rci',{}).get('9',{})
    if direction and short.get('movement')==('falling' if sign==1 else 'rising'):
        cautions.append('RCI9は短期逆行。調整進行と反応のタイミングを確認し、大局方向を単独で変えない')
    for period in ('26','52'):
        if direction and f.get('rci',{}).get(period,{}).get('extreme_run',{}).get('zone')==('upper' if sign==1 else 'lower'):
            support.append('RCI'+period+'は方向側の極端域。張り付きは持続性の参考で、逆張り理由にはしない')
    sma=f.get('sma',{})
    close=f.get('bars',[{}])[-1].get('close') if f.get('bars') else None
    for p in ('50','200'):
        v=sma.get(p,{}).get('value')
        if v is None:cautions.append('SMA'+p+'は履歴不足。補助背景の不足として扱う')
        elif direction and sign*(close-v)<0:
            cautions.append('価格はSMA'+p+'の方向反対側。中長期背景との競合を確認');material.append('sma'+p+'_opposed')
    for p in ('26','52'):
        r=f.get('rci',{}).get(p,{})
        if direction and r.get('movement')==('falling' if sign==1 else 'rising'):
            cautions.append('RCI'+p+'が予測方向に逆行。傾き・転換・張り付きの解消を監視');material.append('rci'+p+'_opposed')
    structural={'HH_HL':'long','LH_LL':'short'}.get(structure)
    broken = structural is not None and structure_state == 'broken'
    if broken:
        prior = '上昇' if structural == 'long' else '下降'
        opposite = '下降' if structural == 'long' else '上昇'
        cautions.append(f'{f["timeframe"].upper()}の旧{prior}構造は確定終値で崩れた。新しい{opposite}構造の確定は待ち')
        material.append('structure_broken')
    elif structural and direction and structural!=direction:
        cautions.append('価格構造は方向仮説と逆。転換と一時調整を再評価');material.append('structure_opposed')
    elif not structural:
        cautions.append('価格構造の方向更新は未確認');material.append('structure_unconfirmed')
    if momentum!='directional_building':
        cautions.append(texts[phase]);material.append('momentum_unconfirmed')
    reversal=basis=='sma50_macd_reversal_hypothesis'
    if reversal:
        phase='reversal_developing';texts[phase]='SMA50の位置・傾きと通常MACDの方向側改善から転換を仮説化。SB背景と競合し、転換完了とはしない'
        cautions.append(texts[phase]);material.append('sb_background_conflict')
    structure_conflict = bool(structural and direction and structural != direction)
    if broken:
        structure_conflict = structural == direction
    weak = reversal or structure_conflict
    if setup_synthesis and direction and h:
        line = m[-1].get('line')
        if type(line) in (int, float) and math.isfinite(line):
            if sign * line < 0:
                material.append('macd_zero_line_opposed')
                cautions.append('MACD本線はゼロラインの方向反対側')
                rci26 = f.get('rci', {}).get('26', {})
                rci52 = f.get('rci', {}).get('52', {})
                opposing_zone = 'lower' if sign == 1 else 'upper'
                if h[-1] < 0 and (
                        rci26.get('movement') == ('falling' if sign == 1 else 'rising')
                        or rci52.get('extreme_run', {}).get('zone') == opposing_zone):
                    weak = True
                    material.append('setup_momentum_opposed')
                    cautions.append('MACDと中長期RCIが逆行。H1セットアップの継続を再評価')
            elif sign * line > 0 and h[-1] > 0:
                support.append('MACD本線とシグナルの関係が方向を支持')
        for period in ('50', '200'):
            average = sma.get(period, {})
            value = average.get('value')
            if value is not None and close is not None:
                slope = average.get('slope')
                if sign * (close - value) > 0 and slope == ('up' if sign == 1 else 'down'):
                    support.append(f'終値とSMA{period}の傾きが方向を支持')
    if regime == 'correction':
        material.append('sb_correction')
    return {'schema':'standard_direction_forecast_v1','status':'available' if status and direction else 'no_direction' if status else 'unverified',
        'direction':direction,'direction_basis':basis,'phase':phase,'conviction':'weak' if weak else 'developing',
        'primary_path':texts[phase],'alternative_path':'SB方向背景と価格構造が崩れれば継続仮説を取り下げる。短期RCIや局所反応だけで反転しない',
        'support':support,'cautions':cautions,'material_cautions':material,'background':{'sma':deepcopy(sma)},
        'evolution':{'status':'available' if h else 'unverified','momentum':momentum},
        'timing':{'rci':deepcopy(f.get('rci',{}))},'timeframe':f['timeframe'],'evaluated_at':f['evaluated_at']}


def wave(rows,direction):
    out={'status':'unverified','thesis_invalidation':None,'local_setup_failure':None,'first_obstacle':None,
         'retest_objective':None,'extension_zone':None,'pullback_zone':None,'reference_close':rows[-1]['close'] if rows else None,
         'reference_close_timestamp':rows[-1]['timestamp'] if rows else None,'path_stage':'unverified',
         'obstacles':[],'reason':'確認済みの波の起終点が不足。価格を補完しない'}
    if not direction or len(rows)<5:return out
    highs=[{'price':b['high'],'timestamp':b['timestamp']} for i,b in enumerate(rows) if 2<=i<len(rows)-2 and all(b['high']>rows[j]['high'] for j in (i-2,i-1,i+1,i+2))]
    lows=[{'price':b['low'],'timestamp':b['timestamp']} for i,b in enumerate(rows) if 2<=i<len(rows)-2 and all(b['low']<rows[j]['low'] for j in (i-2,i-1,i+1,i+2))]
    sign=1 if direction=='long' else -1;starts,ends=(lows,highs) if sign==1 else (highs,lows)
    # Earliest still-unbroken confirmed structural origin; no DMA/SMA cycle,
    # distance/RR optimization or rolling projection target.
    viable=[p for p in starts if any(e['timestamp']>p['timestamp'] and sign*(e['price']-p['price'])>0 for e in ends)
            and all(sign*(b['close']-p['price'])>0 for b in rows if b['timestamp']>=p['timestamp'])]
    if not viable:return out
    start=viable[0];end=max((e for e in ends if e['timestamp']>start['timestamp']),key=lambda e:sign*e['price'])
    c=rows[-1]['close'];width=sign*(end['price']-start['price']);ext=[start['price']+sign*width*x for x in (1.272,1.618)]
    ahead=[p for p in ends if sign*(p['price']-c)>0]
    stop=[p for p in starts if sign*(c-p['price'])>0]
    out.update(obstacles=ends,status='objective_reached' if sign*(c-ext[1])>=0 else 'available',thesis_invalidation=start['price'],
        local_setup_failure=stop[-1]['price'] if stop else None,
        first_obstacle=min(ahead,key=lambda p:sign*(p['price']-c)) if ahead else None,
        retest_objective=end,pullback_zone={'shallow':end['price']-sign*width*.382,'deep':end['price']-sign*width*.618,'kind':'standard_fibonacci_retracement_reference'},extension_zone={'near':ext[0],'far':ext[1],'kind':'standard_fibonacci_conditional_projection'},
        start_pivot=start,end_pivot=end,anchor_basis='earliest_unbroken_confirmed_price_structure_in_verified_history',
        reason='確認済み価格構造の未撤回起点からの波。保有履歴内の参考で真のトレンド起点とは断定しない')
    return out


def assess(pair,strategy,track,clock):
    r={'pair':pair,'strategy':strategy,'evaluated_at':clock,'method_version':METHOD,
       'standard_technical_version':2,'technical_entry_version':1,'bollinger_regime_version':1,'standard_inputs':deepcopy(track['standard_inputs']),
       'currency_strength_context':deepcopy(track.get('currency_strength_context')),
       'macro_context':deepcopy(track.get('macro_context',{})),
       'execution_authority':'none','advisory_only':True,'reference_timeframe':track['base_timeframe'],
       'trigger_timeframe':track['trigger_timeframe']}
    if track['trigger_timeframe'] in ('m15', 'm5'):
        r['multi_timing_version'] = 2 if strategy == 'swing' and 'h1_setup' in track['standard_inputs'] else 1
    if track['base_timeframe'] == 'h4':
        r['structure_interpretation_version'] = 1
        if 'h1_setup' in track['standard_inputs']:
            r['swing_setup_version'] = 1
            r['setup_synthesis_version'] = 1
            r['swing_objective_version'] = 1
    return refresh(r)


def refresh(r):
    if r.get('method_version')!=METHOD or type(r.get('standard_technical_version')) is not int or r['standard_technical_version'] not in (1,2):
        raise ValueError('unsupported standard technical profile')
    if 'technical_entry_version' in r and (type(r['technical_entry_version']) is not int or r['technical_entry_version']!=1):
        raise ValueError('unsupported technical entry interpretation')
    i=r['standard_inputs'];base=i['base'];trigger=i['trigger'];clock=r['evaluated_at'];tf=r['reference_timeframe'];tt=r['trigger_timeframe']
    if i['evaluated_at']!=clock or base['evaluated_at']!=clock or trigger['evaluated_at']!=clock:raise ValueError('standard input clocks mismatch')
    if 'multi_timing_version' in r and (type(r['multi_timing_version']) is not int
            or r['multi_timing_version'] not in (1, 2) or tt not in ('m15', 'm5')):
        raise ValueError('unsupported multi-technical timing version')
    setup = i.get('h1_setup')
    timing = i.get('m5_timing')
    extra_frames = tuple((name, fdata) for name, fdata in (('h1', setup), ('m5', timing))
                         if fdata is not None)
    for tfname,fdata in ((tf,base),(tt,trigger),*extra_frames):
        if extra_frames and (fdata.get('timeframe') != tfname or fdata.get('evaluated_at') != clock):
            raise ValueError('standard timeframe context mismatch')
        version=fdata.get('calculation_version',1)
        if type(version) is not int or version not in (1,2,3):raise ValueError('unsupported saved calculation version')
        if fdata.get('bars') and frame(fdata['bars'],tfname,clock,fdata['verified'],fdata.get('calendar'),fdata.get('calculation_version',1))!=fdata:
            raise ValueError('standard frame calculations differ from retained full-prefix candles')
    r['technical_order_version']=1
    r['technical_profile']=deepcopy(PROFILE)
    if base.get('calculation_version',1)!=trigger.get('calculation_version',1):raise ValueError('mixed calculation profiles')
    if base.get('calculation_version') in (2,3):
        r['technical_profile'].update(macd_signal='EMA9',h4_calendar='mt4_ny_close_h4_v1')
    r['base_quality_verified']=base.get('verified') is True
    from .core import technical
    structure = technical(base.get('bars', []))
    if i['structure'] != structure.get('structure','unconfirmed'):
        raise ValueError('standard price structure mismatch')
    state = None
    if 'structure_interpretation_version' in r:
        version = r['structure_interpretation_version']
        if type(version) is not int or version != 1 or tf != 'h4':
            raise ValueError('unsupported structure interpretation')
        evidence = {}
        if base.get('verified') is True and 0 < base.get('closed_at', 0) <= clock:
            evidence = structure.get('closed_bar_structure', {})
        state = evidence.get('state', 'unknown')
        r['base_structure_state'] = {'state': state,
            'pivot_timestamp': evidence.get('pivot_timestamp'),
            'break_bar_timestamp': evidence.get('break_bar_timestamp')}
    regime_version = r.get('bollinger_regime_version')
    if 'bollinger_regime_version' in r and (type(regime_version) is not int or regime_version != 1):
        raise ValueError('unsupported Bollinger regime interpretation')
    r['base_structure'] = i['structure']
    background = forecast(base, i['structure'], structure_state=state,
                          bollinger_regimes=regime_version == 1)
    f = background
    direction = f['direction']
    setup_opposed = False
    h1_primary = 'swing_setup_version' in r
    synthesis = 'setup_synthesis_version' in r
    if synthesis and (type(r['setup_synthesis_version']) is not int
                      or r['setup_synthesis_version'] != 1 or not h1_primary):
        raise ValueError('unsupported setup synthesis interpretation')
    if h1_primary:
        if (type(r['swing_setup_version']) is not int or r['swing_setup_version'] != 1
                or r['strategy'] != 'swing' or tf != 'h4' or setup is None):
            raise ValueError('unsupported swing setup interpretation')
        setup_structure = technical(setup.get('bars', []))
        f = forecast(setup, setup_structure.get('structure', 'unconfirmed'),
                     structure_state=setup_structure.get('closed_bar_structure', {}).get('state'),
                     bollinger_regimes=True, setup_synthesis=synthesis)
        setup_fresh = setup.get('verified') is True and 0 <= clock - setup.get('closed_at', 0) < SECONDS['h1']
        if not setup_fresh:
            f.update(status='unverified', direction=None, primary_path='H1セットアップは確定足未確認')
        direction = f['direction']
        if f['status'] != 'available':
            direction = None
            f['direction'] = None
        if f['status'] == 'no_direction':
            f['primary_path'] = 'H1セットアップの方向は未確定'
        h4_side = {'long': '買い方向', 'short': '売り方向'}.get(background['direction'], '方向未確定')
        note = f'H4の背景：{h4_side}。{background["primary_path"]}'
        if direction and background['direction'] and direction != background['direction']:
            f['cautions'].append(note+'。H1のセットアップと逆方向')
            f['material_cautions'].append('h4_background_opposed')
        else:
            f['support'].append(note)
    elif setup is not None:
        setup_view = forecast(setup, 'unconfirmed', bollinger_regimes=True)
        setup_ready = setup.get('verified') is True and 0 <= clock-setup.get('closed_at', 0) < SECONDS['h1']
        setup_side = setup_view['direction'] if setup_ready and setup_view['status'] == 'available' else None
        setup_opposed = bool(direction and setup_side and direction != setup_side)
        if setup_side:
            side = '買い' if setup_side == 'long' else '売り'
            note = f'H1セットアップ：{side}方向。{setup_view["primary_path"]}'
            if setup_opposed:
                f['cautions'].append(note+'。H4と競合し再評価')
                f['material_cautions'].append('h1_setup_opposed')
            else:
                f['support'].append(note)
        elif setup_ready:
            f['cautions'].append('H1セットアップの方向は未確定')
        else:
            f['cautions'].append('H1セットアップは確定足未確認')
    r['direction'] = direction
    sign = 1 if direction == 'long' else -1
    if timing is not None and timing.get('verified') is True and 0 <= clock-timing.get('closed_at', 0) < SECONDS['m5']:
        from .technical_entry import turn_observed
        rci = timing.get('rci', {}).get('9', {})
        if turn_observed(rci.get('value'), rci.get('previous'), direction):
            f['support'].append('M5のRCI9反転を仕掛けタイミングの補足として観測')
    for name in ('w1','d1'):
        context=r.get('macro_context',{}).get(name,{})
        if context.get('verified') is not True or (context.get('super_bollinger') or {}).get('status')!='calculated':f['cautions'].append(name.upper()+'上位背景は資料不足')
        elif setup is not None and bollinger_regime(context['super_bollinger'])[1] == 'range':
            f['support'].append(name.upper()+'はSBレンジ局面')
        elif (context.get('super_bollinger') or {}).get('centerline_direction')==('down' if direction=='long' else 'up'):
            f['cautions'].append(name.upper()+'上位SB背景が予測方向と競合。伸びの制約に注意');f['material_cautions'].append(name+'_background_opposed')
    p=wave(base.get('bars',[]),direction);rows=base.get('bars',[]);recent=trigger.get('bars',[])
    active=(len(rows)>=2 and p.get('retest_objective') and all(sign*(b['close']-p['retest_objective']['price'])>0 for b in rows[-2:]) and (not h1_primary or background['direction']==direction) and background['evolution']['momentum']=='directional_building')
    target=(p['retest_objective']['price'] if p.get('retest_objective') and sign*(p['retest_objective']['price']-p['reference_close'])>0 else
            p['extension_zone']['near'] if active and sign*(p['extension_zone']['near']-p['reference_close'])>0 else p['extension_zone']['far'] if active else None)
    if 'swing_objective_version' in r:
        if (type(r['swing_objective_version']) is not int
                or r['swing_objective_version'] != 1 or not h1_primary):
            raise ValueError('unsupported swing objective interpretation')
        objective = p.get('retest_objective')
        if (objective and target == objective['price'] and not active
                and base.get('verified') is True and trigger.get('verified') is True):
            pivot_index = next(i for i, bar in enumerate(rows)
                               if bar['timestamp'] == objective['timestamp'])
            confirmation_bar = rows[pivot_index + 2]
            confirmed_at = confirmation_bar.get('session_end_utc',
                                                 confirmation_bar['timestamp'] + SECONDS[tf])
            reached = next((bar for bar in recent
                            if confirmed_at <= bar['timestamp']
                            and bar['timestamp'] + SECONDS[tt] <= clock
                            and sign * (bar['close'] - target) >= 0), None)
            if reached:
                p['completed_retest'] = {'price': target,
                                         'closed_at': reached['timestamp'] + SECONDS[tt]}
                target = None
                f['cautions'].append('前回の節目目標は確認足終値で到達済み。新しい価格計画待ち')
    p['path_stage']='withdrawn' if p['status']=='objective_reached' else 'retest' if target is not None and not active else 'extension_active' if active else 'extension_wait'
    if 'completed_retest' in p:
        p['path_stage'] = 'completed_retest_wait'
    r['wave_price_plan']=p
    quality=(base.get('status')=='available' and base.get('verified') is True and rows and 0<=clock-base.get('closed_at',0)<SECONDS[tf])
    r['assessment']='evaluation_pending' if not quality else 'skip' if f['status']=='no_direction' else 'evaluation_pending' if f['status']!='available' or p['status']=='unverified' else 'skip' if p['status']!='available' else 'review'
    r['reference_levels']={'invalidation':p['thesis_invalidation'],'scenario_target':target,'structural_target':(p['first_obstacle'] or {}).get('price'),'executable_price':False}
    r['reference_plan']={'reference_close':p['reference_close'],'reference_close_timestamp':p['reference_close_timestamp'],'scenario_target':target,'invalidation':p['thesis_invalidation']}
    r['invalidation']={'price':p['thesis_invalidation'],'scope':'base_wave_thesis','observed':False}
    r.pop('skip_reason',None)
    if r['assessment']=='skip':r['skip_reason']='direction_unconfirmed' if f['status']=='no_direction' else 'base_wave_objective_reached'
    r['expiry']={'status':'withdrawn' if p['status']=='objective_reached' else 'reference_recheck','time_expiry':{'status':'not_defined'},'withdrawal_conditions':[{'condition':'base_wave_invalidation','price':p['thesis_invalidation'],'relation':'<=' if sign==1 else '>=','basis_timeframe':tf,'confirmation':'verified_saved_base_close'}] if p['thesis_invalidation'] else []}
    r['market_phase']='transition_context' if f['conviction']=='weak' else 'pullback_wait' if f['phase']!='continuation' else 'directional_structure_wait'
    r['entry_condition_inputs']=condition_inputs({tt:{'candles':recent}},{'base_verified':quality,'trigger_verified':trigger.get('verified') is True,'direction':direction,'trigger_timeframe':tt},clock)
    if r.get('technical_entry_version')==1:
        from .technical_entry import describe as technical_conditions,candle_reference
        if r.get('multi_timing_version') == 2:
            r['timing_context'] = ('pullback' if h1_primary and f['phase'] in (
                'pullback_deepening', 'pullback_easing', 'pullback_unsettled', 'pullback_expected')
                else 'standard')
        r['scenario_conditions']=technical_conditions(r)
        r['candle_reference']=candle_reference(r)
    else:
        r['scenario_conditions']=describe_conditions(r,r['entry_condition_inputs'])
    fresh=trigger.get('verified') is True and recent and 0<=clock-trigger.get('closed_at',0)<SECONDS[tt]
    price=recent[-1]['close'] if fresh else None;stop=p['thesis_invalidation']
    # Read ahead obstacles at trigger close; old/passed levels are not front barriers.
    front=(p['first_obstacle'] or {}).get('price')
    if fresh:
        ahead=[a for a in p.get('obstacles',[]) if sign*(a['price']-price)>0]
        front=min(ahead,key=lambda a:sign*(a['price']-price))['price'] if ahead else None
        r['reference_levels']['structural_target']=front
    if r.get('technical_entry_version')==1:
        original=p.get('first_obstacle')
        r['price_path_context']={'original_obstacle':deepcopy(original),'current_front':front,
            'passed_level':original['price'] if original and fresh and sign*(price-original['price'])>0 else None,
            'scope':'confirmed_levels_and_close_positions_not_candle_patterns'}
    else:
        from .obstacle_path import describe as describe_obstacle
        r['obstacle_path_review']=describe_obstacle({'direction':direction,'reference_timeframe':tf,'trigger_timeframe':tt,
            'evaluated_at':clock,'base_quality_verified':bool(quality),'entry_condition_inputs':r['entry_condition_inputs'],
            'trigger_price_reference':{'status':'observed_reference' if fresh else 'unverified','timeframe':tt,
                'evaluated_at':clock,'closed_at':trigger.get('closed_at'),'close':price},
            'technical_plan_inputs':{'highs' if sign==1 else 'lows':p.get('obstacles',[])}},p)
        reaction=r['obstacle_path_review']
        if reaction['status']=='available' and r.get('technical_entry_version')!=1:
            f['cautions'].append(reaction['summary'])
            if reaction['reaction']=='breakout_failed' or reaction['passed_level'] is not None:
                f['material_cautions'].append('obstacle_reaction_requires_followup')
    p.pop('obstacles',None)  # Derived pivot list is reproducible from retained candles.
    risk=sign*(price-stop) if fresh and stop else None;reward=sign*(target-price) if fresh and target else None
    room=sign*(front-price) if front and fresh else reward
    defined=r['scenario_conditions']['status'] in ('waiting','awaiting_breakout','awaiting_retest','conditions_observed')
    events=[e for e in r.get('economic_calendar_context',{}).get('events',[]) if e.get('impact')=='high' and e.get('time_precision')=='minute' and type(e.get('scheduled_at_utc')) is int and base.get('closed_at',clock)<=e['scheduled_at_utc']<=(clock//3600+1)*3600 and not e.get('timing_conflict') and e.get('status') not in ('cancelled','canceled')]
    local=p.get('local_setup_failure')
    local_paused=bool(r['assessment']=='review' and r['standard_technical_version']==2 and fresh and local and sign*(price-local)<=0)
    status=('evaluation_pending' if r['assessment']=='evaluation_pending' else 'direction_watch' if r['assessment']=='skip' else
            'event_recheck' if events else 'price_plan_recheck' if 'completed_retest' in p else 'technical_recheck' if f['conviction']=='weak' or f['phase']=='pullback_deepening' or setup_opposed else
            'entry_recheck' if local_paused else 'price_plan_recheck' if not risk or risk<=0 or not reward or reward<=0 or not room or room<=0 else 'entry_recheck' if not defined else 'technical_watch')
    r['grade']='C' if r['assessment']=='review' and f['conviction']=='weak' else 'A' if status=='technical_watch' and f['phase']=='continuation' and not f['material_cautions'] else 'B' if r['assessment']=='review' else None
    r['grade_reason']=f['primary_path']+'。'+{'technical_watch':'保存条件の反応と価格経路を監視','technical_recheck':'勢い・構造の再評価待ち','price_plan_recheck':('到達済みの節目に代わる価格計画待ち' if 'completed_retest' in p else '未確認の拡張や通過済み目標を追わず価格計画を再評価'),'entry_recheck':'局所条件を再評価','event_recheck':'発表後に再評価','direction_watch':'旧経路終了、新しい構造待ち','evaluation_pending':'方向・確定波の主要材料不足'}[status]
    r['practical_review']={'schema':'standard_practical_review_v1','status':status,'summary':r['grade_reason'],'reference_margin_sufficient':bool(risk and reward and reward>risk),'events':events}
    if r['standard_technical_version']==2:
        r['practical_review']['entry_status']='paused' if local_paused else 'timing_reference' if fresh else 'unverified'
        if local_paused:
            r['grade_reason']='確認足終値が局所セットアップ停止水準を通過。大局撤回とは別に仕掛けを再評価'
            r['practical_review']['summary']=r['grade_reason']
    r['trigger_price_review']={'status':'observed_reference' if fresh else 'unverified','saved_close':price,'closed_at':trigger.get('closed_at'),'risk_distance':risk,'reward_distance':reward,'first_obstacle_reward':room,'reference_rr':round(reward/risk,2) if risk and risk>0 and reward and reward>0 else None,'formation_rr':None,'costs_included':False,'basis':'geometry_not_entry_risk'}
    r['currency_strength_context']=interpret(r.get('currency_strength_context'),r['pair'],r['strategy'],direction,clock)
    r['technical_outlook']={'forecast':f,'path':f['primary_path'],'alternative_path':f['alternative_path'],'evolution':f['evolution'],'cautions':f['cautions'],'status':'transition' if f['conviction']=='weak' else 'continuation' if f['phase']=='continuation' else 'retracement_then_continuation'}
    r['reasons']=f['support']+[f['primary_path'],p['reason']];r['opposing_evidence']=f['cautions'];r['waiting_conditions']=[r['scenario_conditions']['summary']];r['formation_conditions']=r['waiting_conditions'][:]
    r['uncertainties']=['実際の成立価格・費用・到達時間は未確認'];r['scenario_explanation']={'waiting_condition':r['scenario_conditions']['summary']}
    return r


def pair_row(pair,data,source_quality,clock):
    frames=data['standard_technical_frames'];tracks={}
    for strategy,base,trigger in (('swing','h4','m15'),('daytrade','h1','m5')):
        b=deepcopy(frames[base]);t=deepcopy(frames[trigger])
        for name,entry in ((base,b),(trigger,t)):
            if source_quality.get('timeframes',{}).get(name,{}).get('ok') is not True:
                entry['verified']=False;entry['status']='unverified'
        from .core import technical
        structure=technical(b.get('bars',[])).get('structure','unconfirmed');f=forecast(b,structure)
        tracks[strategy]={'standard_technical_version':1,'assessment_method':METHOD,
            'base_timeframe':base,'trigger_timeframe':trigger,'reference_timeframe':base,
            'base_structure':structure,'direction':f['direction'],'base_verified':b.get('verified'),
            'trigger_verified':t.get('verified'),'state':'watch' if b.get('status')=='available' else 'unassessed',
            'trigger_status':'candle_current','standard_inputs':{'evaluated_at':clock,'base':deepcopy(b),'trigger':deepcopy(t),'structure':structure},
            'reference_plan':{},'reference_levels':{},'scenario_explanation':{},'rci_observation':{},'indicator_context':{},
            'macro_context':{tf:{'verified':frames[tf]['verified'],'super_bollinger':frames[tf].get('super_bollinger'),'sma':frames[tf].get('sma')} for tf in ('w1','d1')}}
        if strategy == 'swing':
            for key, name in (('h1_setup', 'h1'), ('m5_timing', 'm5')):
                extra = deepcopy(frames[name])
                if source_quality.get('timeframes', {}).get(name, {}).get('ok') is not True:
                    extra.update(verified=False, status='unverified')
                tracks[strategy]['standard_inputs'][key] = extra
    return {'pair':pair,'strategy_tracks':tracks,'direction':None,
        'state':'conditional_watch' if any(t['base_verified'] for t in tracks.values()) else 'unassessed',
        'scheduled_grade':'D','legacy_pair_rank_status':'retired_use_canonical32',
        'explanation':'標準指標による32戦略の独立判断を参照','grade_reason':'旧ペア総合順位は使用しない',
        'next_check':'各戦略の保存条件・主監視と対案を確認','m15_status':'reference_only',
        'm15_diagnostic':{},'m5_timing':{'usage':'reference_only'},'reference_levels':{},
        'w1_history':{'verified':frames['w1']['verified'],'observed_count':len(frames['w1'].get('bars',[]))},
        'advisory_only':True,'observation_clock':clock}



def _saved_distance_line(record):
    def valid_price(value):
        return type(value) in (int, float) and math.isfinite(value) and value > 0

    recent = record.get('trigger_price_review', {})
    price, closed = recent.get('saved_close'), recent.get('closed_at')
    clock = record.get('evaluated_at')
    timeframe = record['trigger_timeframe']
    if (recent.get('status') != 'observed_reference' or not valid_price(price)
            or type(closed) is not int or type(clock) is not int
            or closed <= 0 or not 0 <= clock - closed < SECONDS[timeframe]):
        return '残り値幅：確認足の保存終値または確定時刻を確認できない'

    direction = 1 if record['direction'] == 'long' else -1
    pip = Decimal('0.01' if record['pair'].endswith('JPY') else '0.0001')
    levels = record['reference_levels']

    def distance(key):
        level = levels.get(key)
        if not valid_price(level):
            return '水準未確認'
        remaining = direction * (Decimal(str(level)) - Decimal(str(price))) / pip
        if remaining == 0:
            return '到達済み'
        if remaining < 0:
            return '通過済み'
        if remaining >= Decimal('0.05'):
            return f"{remaining.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)} pips"
        if remaining >= Decimal('0.005'):
            return f"{remaining.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)} pips"
        return '0.01 pips未満'

    jst = datetime.fromtimestamp(closed, ZoneInfo('Asia/Tokyo'))
    return (f'残り値幅：保存{timeframe.upper()}終値 {price}（{jst:%m/%d %H:%M JST}）'
            f'｜手前の節目 {distance("structural_target")}｜波の目標 {distance("scenario_target")}')


def render_lines(r, *, presentation_version=1):
    if type(presentation_version) is not int or presentation_version not in (1,2,3):
        raise ValueError('unsupported report presentation version')
    f=r['technical_outlook']['forecast'];p=r['wave_price_plan'];c=r['scenario_conditions']
    fmt=lambda x:f'{x:.8f}'.rstrip('0').rstrip('.') if type(x) in (int,float) and x>0 else '未確認'
    lines = ['',r['pair']+' '+r['strategy']+'｜'+('買い' if r['direction']=='long' else '売り')+'｜'+str(r['grade']),
        '見通し：'+f['primary_path'],'根拠：'+'／'.join(r['reasons']),
        '懸念：'+'／'.join(r['opposing_evidence']),
        ('局所条件観測済み：' if c['status']=='conditions_observed' else '待つ条件：')+c['summary'],
        '大局撤回：'+r['reference_timeframe'].upper()+'確定終値 '+fmt(p['thesis_invalidation'])+('以下' if r['direction']=='long' else '以上'),
        '途中障害：'+fmt(r['reference_levels']['structural_target'])+'／経路目標：'+fmt(r['reference_levels']['scenario_target']),
        '通常Fib押し戻り参考域：'+fmt((p.get('pullback_zone') or {}).get('shallow'))+'～'+fmt((p.get('pullback_zone') or {}).get('deep')),
        '通常Fib条件付き拡張：'+fmt((p.get('extension_zone') or {}).get('near'))+'～'+fmt((p.get('extension_zone') or {}).get('far'))+'（確定支持抵抗ではない）',
        '局所停止参考：'+fmt(p['local_setup_failure'])+'。大局撤回と別。実際の成立価格・損失幅・費用は未確定',
        *((['ローソク足の補足：'+r['candle_reference']['summary']]) if r.get('candle_reference',{}).get('status') in ('observed','not_observed') else []),
        '使用指標：SB、通常MACD12/26/9、通常Fib、SMA50/200、RCI9/26/52']
    if presentation_version == 1:
        return lines
    paused = r.get('practical_review',{}).get('entry_status') == 'paused'
    state = ('経路終了・再評価' if r.get('expiry',{}).get('status') == 'withdrawn' else
             '局所停止・再評価' if paused else
             '局所条件観測済み' if c['status'] == 'conditions_observed' else
             '条件待ち' if c['status'] == 'waiting' else '条件確認不可・再評価')
    title = (r['pair'][:3]+'/'+r['pair'][3:]+'｜'+
             ('スイング' if r['strategy']=='swing' else 'デイトレード')+'｜'+
             ('買い' if r['direction']=='long' else '売り')+str(r['grade'])+'｜'+state)
    stop = p['local_setup_failure']
    stop_line = ('局所停止：'+r['trigger_timeframe'].upper()+'確定終値 '+fmt(stop)+
                 ('以下' if r['direction']=='long' else '以上') if stop is not None else
                 '局所停止：水準未確認')
    stop_line += '。仕掛けを再評価する水準で、大局撤回と別。成立価格・損失幅・費用は未確定'
    background = []
    if r['strategy'] == 'swing' and r['trigger_timeframe'] == 'h1':
        d1 = r.get('macro_context', {}).get('d1', {})
        sb = d1.get('super_bollinger') or {}
        slope = sb.get('centerline_direction') if d1.get('verified') and sb.get('status') == 'calculated' else None
        direction = {'up':'上向き', 'down':'下向き', 'flat':'横ばい'}.get(slope, '未確認')
        background.append('D1環境：スーパーボリンジャー中心線 '+direction+'｜H4の波：'+f['primary_path'])
    return ['', title, *background, '確認足 '+r['trigger_timeframe'].upper()+'｜'+lines[5],
            stop_line, lines[6], lines[7],
            *([_saved_distance_line(r)] if presentation_version == 3 else []), *lines[2:5], *lines[8:10], *lines[11:]]


def pair_context(records,clock, *, version=3):
    grouped={}
    for r in records:grouped.setdefault(r['pair'],{})[r['strategy']]=r
    result=[]
    for pair,tracks in grouped.items():
        if set(tracks)!={'swing','daytrade'}:continue
        s,d=tracks['swing'],tracks['daytrade'];fs=s.get('technical_outlook',{}).get('forecast',{});fd=d.get('technical_outlook',{}).get('forecast',{})
        if any(f.get('status')!='available' for f in (fs,fd)) or fs['direction']==fd['direction']:continue
        if any(r.get('method_version')!=METHOD or r.get('evaluated_at')!=clock for r in (s,d)):continue
        def backing(r,f):
            v=f['background']['sma']['50'];close=r['reference_plan']['reference_close'];direction=r['direction']
            if 'swing_setup_version' in r:
                bars = r['standard_inputs']['h1_setup']['bars']
                close = bars[-1]['close'] if bars else None
            return close is not None and v['value'] is not None and v['slope']==('up' if direction=='long' else 'down') and (close>v['value'] if direction=='long' else close<v['value'])
        primary=None
        if backing(s,fs) and fd['evolution']['momentum'] in ('counterpressure_easing','counterpressure_mixed') and fs['phase']!='pullback_deepening':primary='swing'
        elif backing(d,fd) and fd['phase']=='continuation' and not backing(s,fs):primary='daytrade'
        if primary and tracks[primary]['practical_review']['status']!='technical_watch':primary=None
        plans={k:{'direction':r['direction'],'grade':r['grade'],'phase':r['technical_outlook']['forecast']['phase'],
                  'condition_status':r['scenario_conditions']['status'],'wait':r['scenario_conditions']['summary'],
                  'withdrawal':r['invalidation'],'timeframe':r['reference_timeframe'],'target':r['reference_levels']['scenario_target']} for k,r in tracks.items()}
        resolution=fs.get('timeframe','h4').upper()+'（スイング）：'+fs['primary_path']+'／H1（デイトレ）：'+fd['primary_path']+'。' if 'swing_setup_version' in s else 'H4：'+fs['primary_path']+'／H1：'+fd['primary_path']+'。'
        for key in ('swing','daytrade'):
            p=plans[key];x=p['withdrawal']['price'];price=f'{x:.8f}'.rstrip('0').rstrip('.') if x else '未確認'
            if version == 4:
                strategy_label = 'スイング' if key == 'swing' else 'デイトレード'
                role = '主監視' if primary == key else '対案' if primary else '比較経路'
                label = f'{strategy_label}（{role}）の確認：'
            else:
                label = 'スイング回復の確認：' if key == 'swing' else '短期調整継続の対案：'
            resolution+=label+p['wait']+'。'+p['timeframe'].upper()+'確定終値'+price+('以下' if p['direction']=='long' else '以上')+'で当該仮説を撤回。'
        resolution+='局所条件の観測や片側撤回だけで他方成立としない。SMA50/200の背景、MACD経過、RCI26/52の持続を再評価し、障害と目標で反応を確認する'
        result.append({'pair':pair,'evaluated_at':clock,'preferred_strategy':primary,
            'phase':'recovery_hypothesis' if primary=='swing' else 'lower_timeframe_continuation' if primary else 'opposing_hypotheses_unresolved',
            'range_assessment':'range_not_established',
            'summary':('主監視は'+('スイング' if primary=='swing' else 'デイトレード')+'、逆方向は対案。' if primary else '主方向は未確定。')+'SBの方向背景と通常MACD・SMA50/200・RCIの経過を比較。逆方向だけでレンジとは断定しない',
            'plans':plans,'resolution':resolution})
    return result
