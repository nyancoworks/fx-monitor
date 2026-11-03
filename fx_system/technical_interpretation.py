"""Read trend, pullback and timing context without accumulating vetoes."""


def refine(record, forecast):
    from .technical_scenario import _notes, _movement
    if forecast.get('status')!='available':return forecast
    direction=forecast['direction'];sign=1 if direction=='long' else -1
    notes=_notes(record,'base');sb=notes.get('super_bollinger',{})
    positions=notes.get('standard_fibonacci_and_dma',{}).get('application',{}).get('positions',{})
    slow=positions.get('25x5',{})
    center={'up':'long','down':'short'}.get(sb.get('centerline_direction'))
    slow_side={'above':'long','below':'short'}.get(slow.get('price_side')) if slow.get('status')=='observed_reference' else None
    structural={'HH_HL':'long','LH_LL':'short'}.get(record.get('base_structure'))
    e=forecast.get('evolution') or {}
    supported=(center==direction and slow_side==direction
               and structural in (None,direction) and e.get('status')=='available')
    # A directional SB environment and slow DMA position can remain intact
    # through a correction. Short oscillators or cloud position alone cannot
    # turn such a correction into a completed reversal or a weak direction.
    if supported:
        momentum=e['momentum']
        phase={'counterpressure_deepening':'pullback_deepening',
               'counterpressure_easing':'pullback_easing',
               'counterpressure_mixed':'pullback_unsettled',
               'directional_fading':'pullback_expected',
               'directional_mixed':'reacceleration_unconfirmed',
               'neutral':'pullback_unsettled'}.get(momentum,
                  'continuation' if e.get('setup_position')=='directional_position_held' else 'recovery_wait')
        span=forecast.get('span_model',{}).get('base',{})
        if phase=='continuation' and span.get('state') in ('cloud_failure','background_conflict','pullback_in_cloud','cloud_break_unconfirmed','first_recovery'):
            phase='pullback_unsettled'
        paths={
            'continuation':'方向背景と勢いの継続を主経路とし、途中障害での反応と押し戻りの有無を監視する',
            'recovery_wait':'方向背景は維持。DMA位置の回復持続を待ち、短期反発だけで再開を確定しない',
            'pullback_expected':'方向側MACDの減速から押し戻り・もみ合いを先に想定。RCIとストキャスの反応、DMA位置の回復から再開を見極める',
            'reacceleration_unconfirmed':'方向側の勢いはあるが変化が混在。押し戻りの収束と再加速を待ち、直進継続を断定しない',
            'pullback_deepening':'背景方向は維持するがMACDの逆行が拡大。押し戻りの進行を想定し、再開を先取りせず勢いの鈍化と位置回復を待つ',
            'pullback_easing':'背景方向を維持し、MACD逆行の鈍化から押し戻り減速を想定。DMA位置と短期反応の回復を待ち、鈍化だけで再開確定とはしない',
            'pullback_unsettled':'SBと遅いDMAの方向背景は維持。勢い・雲位置には調整の材料があり、押し戻りの収束と方向側への回復を監視する'}
        forecast['phase']=phase
        if phase in paths:forecast['primary_path']=paths[phase]
        forecast['conviction']=('established' if phase=='continuation' and not forecast['cautions']
                                else 'developing')
        short=_movement(record,9)
        if short==('falling' if sign==1 else 'rising'):
            forecast['support'].append('RCI9の短期逆行は、残る方向背景の中で押し戻りの進行として読む。位置回復前に仕掛けを先取りせず、独立票にも数えない')
    # Explicitly use sustained oscillator positioning, without interpreting
    # directional pinning as an automatic contrarian reversal signal.
    periods=forecast.get('timing',{}).get('rci',{})
    for period in ('26','52'):
        p=periods.get(period,{})
        zone=p.get('extreme_run',{}).get('zone')
        if _movement(record,int(period)) in ('rising','falling','flat') and zone==('upper' if sign==1 else 'lower'):
            forecast['support'].append('RCI'+period+'は方向側の極端域。トレンド持続の参考として、傾き・張り付きの解消を観察する（独立票ではない）')
    return forecast
