"""Interpret opposing horizons together without changing their saved forecasts."""
from copy import deepcopy


def build(records, clock):
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
    return result


def attach(outlook):
    outlook['pair_context_version']=1
    outlook['pair_market_context']=build(outlook['strategy_assessments'],outlook['evaluated_at'])
    return outlook
