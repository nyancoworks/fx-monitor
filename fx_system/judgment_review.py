"""Explain forecast, scenario and trigger evidence separately; no new signals."""
from copy import deepcopy


def build(record):
    from .technical_scenario import _notes
    from .scenario_conditions import condition_inputs
    tf=record['trigger_timeframe'];clock=record['evaluated_at']
    recent=record.get('trigger_price_review',{})
    verified=recent.get('status')=='observed_reference'
    context=record.get('trigger_structure_input',{})
    structural_ok=(verified and context.get('verified') is True
        and context.get('timeframe')==tf and context.get('evaluated_at')==clock
        and context.get('closed_at')==recent.get('closed_at'))
    side={'HH_HL':'long','LH_LL':'short'}.get(context.get('structure')) if structural_ok else None
    direction=record.get('direction');notes=_notes(record,'trigger') if verified else {}
    sb=notes.get('super_bollinger',{})
    macd=notes.get('dinapoli_macd_preferred_stochastic',{})
    counter=(sb.get('status')=='calculated' and sb.get('centerline_relation')=='opposed'
        or macd.get('status')=='provisional_reference' and macd.get('macd_histogram_relation')=='opposed')
    local=record.get('practical_review',{}).get('entry_status')
    if record.get('expiry',{}).get('status')=='withdrawn':
        state='base_withdrawn';summary='基準足の撤回または経路終了を観測。局所反応で継続しない'
    elif not verified:
        state='unverified';summary='確認足の鮮度・品質が未確認。基準足予測と仕掛け判断を分ける'
    elif local=='paused':
        state='local_setup_failed';summary='局所仕掛けは無効化。基準足終値による大局撤回とは別'
    elif side is not None and direction and side!=direction:
        state='counter_structure';summary='確認足の高安構造は予測と逆。押し戻り継続と局所転換を区別し、基準足転換とは断定しない'
    elif counter:
        state='counter_momentum';summary='確認足のテクニカルは逆行。押し戻りか転換かは未確定で、仕掛け回復待ち'
    elif side==direction and direction:
        state='direction_supported';summary='確認足の構造は予測方向。成立条件の観測・価格余地は別途確認'
    else:
        state='structure_unconfirmed';summary='確認足の構造方向は未確認。局所足だけで大局予測を変更しない'
    shape=None
    inputs=record.get('entry_condition_inputs',{})
    checked=condition_inputs({tf:{'candles':inputs.get('bars')}},
        {'base_verified':record.get('base_quality_verified') is True,
         'trigger_verified':verified,'direction':direction,'trigger_timeframe':tf},clock)
    if checked.get('status')=='verified' and checked.get('closed_at')==recent.get('closed_at'):
        bar=checked['bars'][-1];o,h,l,c=[bar[k] for k in ('open','high','low','close')]
        shape={'closed_at':checked['closed_at'],'body':abs(c-o),
               'upper_wick':h-max(o,c),'lower_wick':min(o,c)-l,
               'meaning':'実体とヒゲの観測量。包み足等の追加シグナルや反転保証ではない'}
    strength=record.get('currency_strength_context',{})
    relation=strength.get('relation','unverified')
    if relation=='opposed':
        structure={'HH_HL':'long','LH_LL':'short'}.get(record.get('base_structure'))
        evolution=record.get('technical_outlook',{}).get('evolution') or {}
        recovering=(evolution.get('momentum') in ('directional_building','directional_stable')
                    and evolution.get('setup_position')=='directional_position_held')
        why=('基準足の方向構造と勢い・DMA位置は予測方向を支持するが、通貨強弱の反転自体は未確認'
             if structure==direction and recovering else
             '通貨強弱に逆らう予測。価格側の持続的回復・転換根拠は未完成で、強弱逆行を解消したとは扱わない')
    else:
        why='通貨強弱は補助背景。整合だけで予測の正しさや仕掛け成立とはしない' if relation=='aligned' else '通貨強弱の方向差は未確認または均衡'
    condition=record.get('scenario_conditions',{})
    stop=record.get('wave_price_plan',{}).get('thesis_invalidation')
    failure={'timeframe':record['reference_timeframe'],'price':stop,
             'relation':'<=' if direction=='long' else '>=' if direction=='short' else None,
             'confirmation':'verified_base_close',
             'meaning':'主予測の撤回条件。反対売買の成立や同一足内の到達順序を保証しない'}
    return {'schema':'contextual_judgment_review_v1','evaluated_at':clock,
        'forecast_confidence':record.get('technical_outlook',{}).get('forecast',{}).get('conviction'),
        'scenario_grade':record.get('grade'),'priority_status':record.get('practical_review',{}).get('status'),
        'forecast_failure':failure,
        'trigger':{'timeframe':tf,'state':state,'summary':summary,
                   'structure':context.get('structure') if structural_ok else 'unverified',
                   'intermediate_context':deepcopy(record.get('intermediate_context',{})),
                   'condition_status':condition.get('status'),'condition_route':condition.get('route'),
                   'candle_shape':shape},
        'currency_strength':{'relation':relation,'movement':strength.get('movement'),
            'material_opposition':strength.get('material_opposition') is True,
            'explanation':why,'summary':strength.get('summary','通貨強弱未確認')},
        'prediction_accuracy':'not_measured', 'is_trade_performance':False}
