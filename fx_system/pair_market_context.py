"""Interpret opposing horizons together without changing their saved forecasts."""
from copy import deepcopy


def build(records, clock, *, version=1):
    if version in (3,4):
        from .standard_technicals import pair_context
        return pair_context(records,clock,version=version)
    pairs={}
    for r in records:pairs.setdefault(r['pair'],{})[r['strategy']]=r
    result=[]
    for pair,tracks in pairs.items():
        if set(tracks)!={'swing','daytrade'}:continue
        s,d=tracks['swing'],tracks['daytrade']
        fs=s.get('technical_outlook',{}).get('forecast',{})
        fd=d.get('technical_outlook',{}).get('forecast',{})
        if (fs.get('status')!='available' or fd.get('status')!='available'
                or s.get('evaluated_at')!=clock or d.get('evaluated_at')!=clock
                or fs.get('direction')==fd.get('direction')):continue
        def background(r,f):
            dma=f.get('background',{}).get('dma',{}).get('25x5',{})
            own='rising' if r.get('direction')=='long' else 'falling'
            side='above' if r.get('direction')=='long' else 'below'
            return (f.get('conviction')!='weak' and dma.get('price_side')==side
                    and dma.get('slope_movement')==own)
        def recovering_against(f):
            dma=f.get('background',{}).get('dma',{})
            movement=dma.get('25x5',{}).get('slope_movement')
            own='rising' if f.get('direction')=='long' else 'falling'
            return (movement in ('rising','falling') and movement!=own
                    and f.get('evolution',{}).get('momentum') in
                    ('counterpressure_easing','counterpressure_mixed'))
        primary=None
        if (background(s,fs) and fs.get('evolution',{}).get('momentum')!='counterpressure_deepening'
                and recovering_against(fd)):primary='swing'
        elif background(d,fd) and fd.get('phase')=='continuation' and not background(s,fs):primary='daytrade'
        # A withdrawn/missing wave cannot become a primary plan just because
        # its indicators still have direction. No forced H4 precedence.
        if primary and (tracks[primary].get('assessment')!='review'
                        or tracks[primary].get('practical_review',{}).get('status')!='technical_watch'):
            primary=None
        direction=lambda r:'買い' if r.get('direction')=='long' else '売り'
        if primary=='swing':
            summary=('H4の遅いDMA方向背景を保つ中で、H1の逆向き予測はDMA傾きとMACD経過が回復側。'
                     +'主監視はスイングの'+direction(s)+'回復、デイトレの'+direction(d)
                     +'は回復失敗時の対案として読む。上位足の調整収束という作業仮説で、再開確定ではない')
            phase='directional_background_with_countermove_recovery'
        elif primary=='daytrade':
            summary=('H4の方向背景が競合する一方、H1は遅いDMA方向背景と継続局面を維持。'
                     +'主監視はデイトレの'+direction(d)+'、スイングの'+direction(s)
                     +'は背景回復待ち。H1の継続だけでH4転換確定とはしない')
            phase='lower_timeframe_continuation_upper_background_conflict'
        else:
            summary='H4とH1の方向仮説が競合し、主方向を選ぶ根拠が不足。単純にレンジや正常な押し戻りと断定せず、両経路の回復・失敗を比較する'
            phase='opposing_hypotheses_unresolved'
        expected_structure='HH_HL' if s.get('direction')=='long' else 'LH_LL'
        if s.get('base_structure')!=expected_structure:
            summary+='。H4の価格構造の方向更新は未確認で、指標背景と区別する'
        range_context=s.get('swing_environment',{}).get('state')=='h4_consolidation'
        if range_context:
            summary='H4は保存SBのもみ合い背景。レンジ逆張りを新設せず、H1の方向シナリオとは時間軸を区別する。'+summary
        result.append({'pair':pair,'evaluated_at':clock,'phase':phase,
            'range_assessment':'h4_consolidation_observed' if range_context else 'range_not_established',
            'preferred_strategy':primary,'summary':summary,
            'plans':{key:{'direction':r.get('direction'),'grade':r.get('grade'),
                         'phase':f.get('phase'),'condition_status':r.get('scenario_conditions',{}).get('status'),
                         'wait':r.get('scenario_conditions',{}).get('summary'),
                         'withdrawal':deepcopy(r.get('invalidation')),
                         'timeframe':r.get('reference_timeframe'),
                         'target':r.get('reference_levels',{}).get('scenario_target')}
                     for key,r,f in (('swing',s,fs),('daytrade',d,fd))},
            'resolution':('主監視側の局所反応に加え、反対側の見通しの回復・撤回を確認する。' if primary else '方向選択待ち。両戦略の局所反応と基準足の見通しの変化・撤回を比較する。')+'片側の撤回だけで他方の成立としない。両方を同時に仕掛ける提案ではない'})
    if version==2:
        for context in result:
            tracks=pairs[context['pair']];s=tracks['swing'];d=tracks['daytrade']
            fs=s['technical_outlook']['forecast'];fd=d['technical_outlook']['forecast']
            def price(x):return f'{x:.8f}'.rstrip('0').rstrip('.') if type(x) in (int,float) and x>0 else '未確認'
            def withdrawal(r):
                x=r.get('invalidation',{}).get('price')
                if type(x) not in (int,float) or x<=0:return r['reference_timeframe'].upper()+'撤回水準未確認（価格を補完しない）'
                return r['reference_timeframe'].upper()+'確定終値'+price(x)+('以下' if r['direction']=='long' else '以上')
            def plan(r):
                w=r.get('wave_price_plan',{});obs=r.get('obstacle_path_review',{}).get('active_obstacle',w.get('first_obstacle')) or {}
                return '途中障害'+price(obs.get('price'))+'、経路目標'+price(r.get('reference_levels',{}).get('scenario_target'))
            def reaction(r):
                c=r.get('scenario_conditions',{})
                return ('局所条件観測済み：' if c.get('status')=='conditions_observed' else '局所確認待ち：' if c.get('status') in ('waiting','awaiting_breakout','awaiting_retest') else '計画再評価：')+str(c.get('summary','確認材料不足'))
            context['evidence']={k:{'phase':f['phase'],'momentum':f.get('evolution',{}).get('momentum'),
                'dma25':deepcopy(f.get('background',{}).get('dma',{}).get('25x5',{})),
                'structure':r.get('base_structure'),'monitoring':r.get('practical_review',{}).get('status')}
                for k,r,f in (('swing',s,fs),('daytrade',d,fd))}
            context['why_wait']='H4：'+fs['primary_path']+'。H1：'+fd['primary_path']+'。局所条件の観測と基準足の方向再開は別'
            context['decision_branches']=[
                {'role':'swing_recovery','summary':'スイングの'+direction(s)+'回復を検討：'+reaction(s)+'。H1逆方向予測の弱まりを確認し、'+withdrawal(d)+'ならそのH1仮説は撤回。H1撤回だけでH4再開とはせず、'+plan(s)+'で反応を確認'},
                {'role':'countermove_continuation','summary':'調整が続く対案：'+reaction(d)+'。H1のDMA位置の回復持続とMACDの'+direction(d)+'側の勢い再開を再評価。'+plan(d)+'を参照し、局所反応だけでH4の方向を反転しない'},
                {'role':'swing_withdrawal','summary':'スイング仮説の撤回：'+withdrawal(s)+'。その場合は旧回復計画を取り下げ、価格構造・SB・DMA・MACD経過を再評価。反対売買の成立を自動認定しない'}]
            context['resolution']=context['why_wait']+'。'+'／'.join(b['summary'] for b in context['decision_branches'])
    return result


def attach(outlook):
    from .standard_technicals import METHOD
    version=4 if any(r.get('method_version')==METHOD for r in outlook['strategy_assessments']) else 2
    outlook['pair_context_version']=version
    outlook['pair_market_context']=build(outlook['strategy_assessments'],outlook['evaluated_at'],version=version)
    return outlook
