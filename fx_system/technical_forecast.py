"""Role-based directional hypotheses from existing, closed technical observations.

Not an optimized predictor, indicator vote, or reproduction of a named trader.
Structure constrains the price plan; it does not supply the forecast direction.
"""
from copy import deepcopy

METHOD = 'contextual_scenario_review_v12_technical_forecast'


def forecast(record):
    from .technical_scenario import _notes, _movement
    from .technical_evolution import describe
    notes = _notes(record, 'base')
    sb = notes.get('super_bollinger', {})
    app = sb.get('application', {})
    result = {'schema':'technical_direction_forecast_v1', 'evaluated_at':record['evaluated_at'],
              'timeframe':record['reference_timeframe'], 'direction':None,
              'status':'unverified', 'phase':'unverified', 'conviction':'unverified',
              'primary_path':'基準足のテクニカル環境は未確認',
              'alternative_path':'次の確定基準足で環境を再評価',
              'support':[], 'cautions':[], 'timing':{}, 'evolution':None,
              'not_probability_or_order':True}
    if record.get('base_quality_verified') is not True or sb.get('status') != 'calculated':
        return result
    center = {'up':'long', 'down':'short'}.get(sb.get('centerline_direction'))
    zone = app.get('price_zone'); width = app.get('bandwidth_state')
    lag = {'above':'long', 'below':'short'}.get(sb.get('lagging_span_location'))
    if zone not in ('above_upper_1sigma','below_lower_1sigma','inside_1sigma') or width not in ('expanding','contracting','flat'):
        return result
    positions = notes.get('standard_fibonacci_and_dma', {}).get('application', {}).get('positions', {})
    slow = positions.get('25x5', {}); fast = positions.get('3x3', {})
    middle = positions.get('7x5', {})
    side = {'above':'long','below':'short'}
    slow_side = side.get(slow.get('price_side')) if slow.get('status')=='observed_reference' else None
    slow_slope = {'rising':'long','falling':'short'}.get(slow.get('slope_movement')) if slow.get('status')=='observed_reference' else None
    environmental_center = center
    # A flat SB center is not a universal veto: a persistent DMA trend with
    # verified directional momentum can supply a provisional trend hypothesis.
    if center is None and slow_side is not None and slow_slope==slow_side:
        candidate=describe({**record, 'direction':slow_side})
        if candidate['momentum'] in ('directional_building','directional_stable'):
            center=slow_side
    if center is None:
        result.update(status='no_direction', phase='direction_unresolved', conviction='weak',
                      primary_path='SBとDMA背景からトレンド方向を説明できない。レンジ逆張りは行わない')
        return result
    # Interpret momentum relative to the environmental hypothesis, independently
    # of the supplied structural label and of local trigger-candle patterns.
    probe = {**record, 'direction':center}
    evolution = describe(probe)
    direction = center
    phase = 'trend_context'
    # A failed SB environmental lead against the slower DMA background with
    # expanding adverse momentum is a transition hypothesis, not a structure veto.
    if (slow_side is not None and slow_side != center and slow_slope==slow_side
            and evolution['momentum']=='counterpressure_deepening'):
        direction = slow_side
        phase = 'reversal_developing'
        evolution = describe({**record, 'direction':direction})
    own_move = 'rising' if direction=='long' else 'falling'
    own_zone = 'above_upper_1sigma' if direction=='long' else 'below_lower_1sigma'
    fast_side = side.get(fast.get('price_side')) if fast.get('status')=='observed_reference' else None
    momentum = evolution['momentum']
    cautions=[]; support=[]
    if environmental_center is None:
        support.append('DMA25x5の背景位置・傾きと複数足の勢いから暫定トレンドを予測')
        cautions.append('SB中心線に方向がなく、DMA背景からの暫定予測。SB環境の回復は未確認')
    else:
        support.append('SB中心線'+('上向き' if center=='long' else '下向き')+'を環境仮説として参照')
    if direction != center:
        cautions.append('SB中心線と遅いDMA背景が競合。転換仮説であり確定トレンドではない')
        support.append('DMA25x5の価格位置・傾きと拡大する勢いがSB背景からの転換を示唆')
    elif lag == direction and zone == own_zone and width == 'expanding':
        support.append('SB遅行・方向側1σ外・帯拡大はトレンド継続の環境。同一指標の独立票にはしない')
    elif lag is not None and lag != direction:
        cautions.append('SB遅行が環境仮説と逆。押し戻りと転換の両経路を残す')
    if slow_side is None:
        cautions.append('DMA25x5の背景位置は未確認')
    elif slow_side != direction:
        cautions.append('DMA25x5の価格位置が予測方向と逆。背景との競合')
    if slow_slope is not None and slow_slope != direction:
        cautions.append('DMA25x5の傾きが予測方向と逆。位置の回復とトレンド回復を区別')
    if middle.get('status')=='observed_reference' and side.get(middle.get('price_side')) not in (None,direction):
        cautions.append('DMA7x5の価格位置は予測方向と逆。押し戻りの回復経路を確認')
    conflict = direction != center or slow_side is not None and slow_side != direction
    if evolution['status'] != 'available':
        phase='evolution_unverified'
        cautions.append(evolution['summary'])
    elif phase != 'reversal_developing':
        phase = {'counterpressure_deepening':'pullback_deepening',
                 'counterpressure_easing':'pullback_easing',
                 'counterpressure_mixed':'transition',
                 'directional_fading':'pullback_expected',
                 'directional_mixed':'reacceleration_unconfirmed',
                 'neutral':'transition'}.get(momentum,
                     'continuation' if fast_side==direction and evolution['setup_position']=='directional_position_held'
                     else 'recovery_wait')
    if momentum not in ('directional_building','directional_stable'):
        cautions.append(evolution['summary'])
    persistence = evolution.get('persistence', {})
    for p in (26,52):
        movement = _movement(record,p)
        if movement in ('rising','falling') and movement != own_move:
            cautions.append('RCI'+str(p)+'の傾きが予測方向と逆。持続性の弱さを反映')
        if persistence.get(str(p))=='weakening':
            cautions.append('RCI'+str(p)+'は複数足でも持続性が悪化')
    # Timing is described but cannot select direction, rescue a conflict, or
    # promote a one-candle rebound to a completed directional thesis.
    stoch = notes.get('dinapoli_macd_preferred_stochastic', {}).get('preferred_stochastic', {})
    periods = record.get('rci_observation',{}).get('frames',{}).get('base',{}).get('periods',{})
    timing = {'rci':deepcopy(periods), 'preferred_stochastic':deepcopy(stoch),
              'dma3x3_position':fast_side,
              'meaning':'RCI9とストキャスの転換・クロス・張り付きは短期反応。単独の方向反転や局所PAによる昇格はしない'}
    short_movement=_movement(record,9)
    if short_movement in ('rising','falling') and short_movement != own_move:
        cautions.append('RCI9の短期反応は予測方向と逆。基準足の方向を反転せず仕掛けの回復を待つ')
    if stoch.get('k_movement') in ('rising','falling') and stoch['k_movement'] != own_move:
        cautions.append('Preferred Stochasticは短期逆行。位置・クロス・張り付きと反応を再確認')
    structure_direction={'HH_HL':'long','LH_LL':'short'}.get(record.get('base_structure'))
    if structure_direction is not None and structure_direction != direction:
        cautions.append('価格構造は予測方向と逆。転換未確認として扱い、同方向の確認済み波と価格計画を別途確認')
        conflict=True
    elif structure_direction is None:
        cautions.append('価格構造の方向は未確定。指標の方向仮説と構造確認を区別')
    for tf in ('w1','d1'):
        context=record.get('macro_context',{}).get(tf,{})
        if context.get('verified') and context.get('relation')=='countertrend':
            cautions.append(tf+'上位足の構造は予測と逆。伸びの制約と転換失敗に注意')
    names={'continuation':'トレンド継続を主経路とする。ただし途中の構造障害で失速すれば押し戻りへ移行',
           'pullback_deepening':'逆行する勢いが拡大。押し戻り継続・転換リスクを主経路とし、元方向への再開を先取りしない',
           'pullback_easing':'逆行は鈍化。押し戻りの減速を想定するが、再開確定ではなくDMA回復と勢いの再加速を待つ',
           'pullback_expected':'方向側の勢いが減速。直進より調整・もみ合いを先に想定し、回復時に終点再試しを検討',
           'reacceleration_unconfirmed':'勢いの変化が混在。押し戻り・もみ合いを想定し、方向への再加速は未確認',
           'recovery_wait':'勢いは改善または維持するがDMA位置の回復持続は未確認。反発の失敗と継続を見極める',
           'reversal_developing':'遅いDMA背景と勢いから転換方向を予測。ただしSB環境と競合し、転換失敗も主要な反対経路',
           'transition':'継続と転換が競合。方向仮説は暫定で、直近PAだけでは決めない',
           'evolution_unverified':'複数足の勢いを確認できず、方向の環境仮説だけを保持。回復を推測しない'}
    weak = conflict or phase in ('transition','pullback_deepening','evolution_unverified')
    result.update(status='available', direction=direction, phase=phase,
                  conviction='weak' if weak else 'developing' if cautions or phase!='continuation' else 'established',
                  primary_path=names[phase],
                  alternative_path='予測方向へのDMA位置の持続と基準足の勢いが崩れれば、継続想定を取り下げ反対経路を再評価。大局撤回は確認済み波の起点で判定',
                  support=support, cautions=cautions, timing=timing, evolution=evolution,
                  background={'dma':deepcopy(positions),
                              'sma':deepcopy(notes.get('sma_context',{})),
                              'meaning':'DMA7x5は中間の回復、SMA100/200は補助背景。短期足で過大評価しない'})
    return result


def outlook(record):
    f=forecast(record)
    if f['status']=='available' and f['direction'] != record.get('direction'):
        raise ValueError('forecast direction differs from same-input directional hypothesis')
    status = ('unverified' if f['status']!='available' else
              'transition' if f['conviction']=='weak' else
              'continuation' if f['phase']=='continuation' else 'retracement_then_continuation')
    return {'schema':'technical_wave_outlook_v2', 'evaluated_at':record['evaluated_at'],
            'timeframe':record['reference_timeframe'], 'status':status,
            'setup':'resumption_context' if f['phase']=='continuation' else 'timing_wait',
            'path':f['primary_path'], 'alternative_path':f['alternative_path'],
            'cautions':f['cautions'], 'forecast':f, 'evolution':f['evolution'],
            'holding_period':'not_estimated', 'time_exit':'not_defined',
            'intended_horizon':'multi_session_wave' if record['strategy']=='swing' else 'intraday_wave',
            'not_probability_or_order':True}


def prepare_track(data, track, clock):
    """Choose direction BEFORE rebuilding all directional plans and contexts."""
    from .strategy_indicator_context import strategy_indicator_context
    from .rci_track_context import rci_track_context
    tf=track['base_timeframe']
    record={'evaluated_at':clock, 'reference_timeframe':tf, 'base_quality_verified':track['base_verified'],
            'base_structure':track['base_structure'], 'strategy':'swing' if tf=='h4' else 'daytrade',
            'indicator_context':strategy_indicator_context(data,track,evaluated_at=clock),
            'rci_observation':rci_track_context(data,track,clock),
            'base_evolution_inputs':data.get('base_evolution_inputs',{}).get(tf,{}),
            'technical_plan_inputs':{'bar':deepcopy(data.get(tf,{}).get('candles',[{}])[-1])
                                    if data.get(tf,{}).get('candles') else {}}}
    f=forecast(record)
    track['direction']=f['direction']
    track['state']='unassessed' if not track['base_verified'] else 'waiting_structure' if not f['direction'] else 'watch' if track['trigger_verified'] else 'waiting_trigger'
