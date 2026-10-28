"""Network-free final indicator preparation shared by production and tests."""
from .dinapoli_research import dma_snapshot, confirmed_fibonacci
from .dinapoli_indicator_reference import indicator_reference
from .indicator_research import research_snapshot, super_bollinger_context


TIMEFRAMES = ('w1','d1','h4','h1','m15','m5')


def dinapoli_diagnostics(frames, setup):
    return {tf:{**dma_snapshot(frames[tf]),
                'confirmed_fibonacci':confirmed_fibonacci(frames[tf],setup.get('direction'))}
            for tf in TIMEFRAMES}


def refresh_strategy_indicators(data, verified, indicator_frames, quality, setup):
    """Only reuse caller-verified candles, preserving existing NY17 semantics."""
    data['indicator_research']={tf:research_snapshot(indicator_frames[tf]) for tf in TIMEFRAMES}
    data['super_bollinger_context']={tf:super_bollinger_context(verified[tf],timeframe=tf,
        calendar=quality['timeframes'][tf].get('calendar')) for tf in TIMEFRAMES}
    data['dinapoli_research']=dinapoli_diagnostics(indicator_frames,setup)
    data['dinapoli_indicator_reference']={tf:indicator_reference(indicator_frames[tf]) for tf in TIMEFRAMES}
    data['indicator_context_version']=2
