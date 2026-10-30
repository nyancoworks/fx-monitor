"""Interpret saved indicator roles; no votes, new price levels or grade gates."""


def build_technical_context(record):
    context = record.get('indicator_context', {})
    if (context.get('schema') != 'contextual_indicator_context_v2'
            or context.get('evaluated_at') != record.get('evaluated_at')):
        return None
    support, caution, unknown, frames = [], [], [], {}
    relation = {'aligned':'方向支持','opposed':'逆方向','unconfirmed':'未確認'}
    for role in ('base','trigger'):
        frame = context.get('frames', {}).get(role, {})
        tf = frame.get('timeframe', record.get('reference_timeframe' if role=='base' else 'trigger_timeframe'))
        label = str(tf).upper()
        notes = {n['indicator']:n for n in frame.get('observations', [])}
        band = notes.get('super_bollinger', {})
        app = band.get('application', {})
        center = band.get('centerline_relation','unconfirmed') if band.get('status')=='calculated' else 'unconfirmed'
        lag = app.get('lagging_relation','unconfirmed') if band.get('status')=='calculated' else 'unconfirmed'
        lag_location = band.get('lagging_span_location') if band.get('status')=='calculated' else None
        width = app.get('bandwidth_state','unverified')
        width_label = {'expanding':'帯拡大','contracting':'帯縮小','flat':'帯幅横ばい'}.get(width,'帯幅未確認')
        if lag=='aligned': support.append(label+' SB遅行スパンも構造方向を支持（価格由来の補足）')
        elif lag=='opposed': caution.append(label+' SB遅行スパンが構造方向と逆。方向の持続・転換を再確認')
        elif lag_location=='inside':caution.append(label+' SB遅行は過去ローソク足の内側。方向の持続・転換を価格反応で確認')
        else: unknown.append(label+' SB遅行と過去ローソク足の位置関係は未確認')
        if width=='contracting':
            caution.append(label+' SB帯は縮小。方向への拡大継続を観測した状態とは区別する')
        elif width=='expanding':
            zone = app.get('price_zone')
            with_direction = zone == ('above_upper_1sigma' if record.get('direction')=='long' else 'below_lower_1sigma')
            if with_direction:
                support.append(label+' SB帯拡大と方向側1σ外の終値を観測。次足の継続性は別確認')
        dma = notes.get('standard_fibonacci_and_dma', {}).get('application', {}).get('positions', {})
        fast, background = dma.get('3x3', {}), dma.get('25x5', {})
        for name, value in (('3x3',fast),('7x5',dma.get('7x5',{})),('25x5',background)):
            if value.get('status')!='observed_reference':
                unknown.append(label+' DMA'+name+'の現在足に対応する描画値は未確認')
        selected = background if role=='base' else fast
        selected_name = '25x5' if role=='base' else '3x3'
        dma_relation = selected.get('price_relation','unconfirmed')
        dma_slope = selected.get('slope_relation','unconfirmed')
        dma_label = '同水準' if selected.get('price_side')=='at' else relation.get(dma_relation,'未確認')
        slope_label = '横ばい' if selected.get('slope_movement')=='flat' else relation.get(dma_slope,'未確認')
        lag_label = '過去足の内側' if lag_location=='inside' else relation.get(lag,'未確認')
        if dma_relation=='aligned':
            support.append(label+' 終値はDMA'+selected_name+'の構造方向側。'+('背景の価格位置' if role=='base' else '短期反応の価格位置')+'として参照')
        elif dma_relation=='opposed':
            caution.append(label+' 終値はDMA'+selected_name+'の構造と逆側。'+('背景との競合' if role=='base' else '押し戻り・転換過程')+'を価格反応で確認')
        if dma_slope=='opposed':
            caution.append(label+' DMA'+selected_name+'の傾きは構造と逆。価格位置と傾きの回復を区別して確認')
        macd = notes.get('dinapoli_macd_preferred_stochastic', {})
        momentum = macd.get('macd_histogram_relation','unconfirmed') if macd.get('status')=='provisional_reference' else 'unconfirmed'
        # Existing detailed MACD/Stochastic/RCI evidence remains in the record.
        # Do not count this concise restatement as another independent vote.
        state = ('counterpressure' if dma_relation=='opposed' else
                 'momentum_caution' if momentum=='opposed' else
                 'direction_support' if dma_relation=='aligned' and momentum=='aligned' else 'unverified')
        frames[role] = {'timeframe':tf, 'sb_centerline':center,'sb_lagging':lag,
            'lagging_location':lag_location,
            'bandwidth_state':width,'price_zone':app.get('price_zone','unverified'),
            'dma_positions':{name:{k:value.get(k,'unconfirmed') for k in ('price_relation','slope_relation','price_side','slope_movement')}
                             for name,value in dma.items()},
            'macd_relation':momentum, 'interpretation':state,
            'summary':f'{label}：SB中心線{relation.get(center,"未確認")}・遅行{lag_label}／{width_label}、DMA{selected_name}価格位置{dma_label}・傾き{slope_label}、MACD{relation.get(momentum,"未確認")}'}
    trigger = frames['trigger']
    waiting = (str(trigger['timeframe']).upper()+'の保存された価格反応条件で、DMAに対する価格位置と勢いの変化を再評価（指標の全一致を成立条件に追加しない）'
               if trigger['interpretation'] in ('counterpressure','momentum_caution') else None)
    result = {'schema':'saved_technical_context_v1','evaluated_at':record['evaluated_at'],
        'frames':frames,'summary':frames['base']['summary']+'／'+frames['trigger']['summary'],
        'supporting_evidence':support,'cautions':caution,'uncertainties':unknown,'waiting_note':waiting,
        'changes_price_conditions':False,'indicator_votes':False,'chart_parity_verified':False}
    from .swing_environment import METHOD
    from .swing_horizon import METHOD as HORIZON_METHOD
    from .swing_wave import METHOD as WAVE_METHOD
    from .technical_scenario import METHOD as TECHNICAL_METHOD
    from .technical_evolution import METHOD as EVOLUTION_METHOD
    if record.get('method_version') in (METHOD, HORIZON_METHOD, WAVE_METHOD, TECHNICAL_METHOD,EVOLUTION_METHOD):
        result.update(schema='saved_technical_context_v2', role_basis='fx_monitor_adaptation_not_original_method_replication',
            roles={'environment':'価格構造・SB遅行・σ帯・帯幅',
                   'setup':'支持抵抗・通常Fib・DMA価格位置。投影は構造目標と別',
                   'momentum':'ディナポリMACD・Preferred Stochastic・RCIの支持/逆行/未確認',
                   'confirmation':'保存確定足の価格反応・目標/撤回までの余地'})
    return result


def attach_technical_context(record):
    technical = build_technical_context(record)
    if technical is not None:
        record['technical_context'] = technical
        for field, values in (('reasons',technical['supporting_evidence']),
                              ('opposing_evidence',technical['cautions']),
                              ('uncertainties',technical['uncertainties'])):
            # Preserve the complete observations in technical_context. The
            # existing comparison text needs one relevant addition per role,
            # rather than duplicating every derived clause and exceeding the
            # bounded saved-export size. Original evidence is never truncated.
            chosen = []
            for frame in technical['frames'].values():
                group = [v for v in values if v.startswith(str(frame['timeframe']).upper()+' ')]
                preferred = [v for v in group if 'DMA' in v]
                if group:chosen.append((preferred or group)[0])
            for value in chosen:
                if value not in record[field]:record[field].append(value)
        if (record.get('assessment')=='review' and technical['waiting_note']
                and technical['waiting_note'] not in record['waiting_conditions']):
            record['waiting_conditions'].append(technical['waiting_note'])
    return record
