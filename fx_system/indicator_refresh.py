"""Current production indicators; retired interpreters only restore old saves."""
from .standard_technicals import prepare


def refresh_strategy_indicators(data, verified, indicator_frames, quality, setup):
    prepare(data,verified,indicator_frames,quality)
