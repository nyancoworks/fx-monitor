"""Synthetic candles shared by non-range integration tests."""
CLOCK = 1800000000


def sample(base='h1', short=False):
    seconds = {'h1': 3600, 'h4': 14400}[base]
    tf = 'm5' if base == 'h1' else 'm15'; trigger = 300 if tf == 'm5' else 900
    bars = [{'timestamp': CLOCK-(20-i)*seconds, 'open': 100, 'high': 104, 'low': 96, 'close': 100}
            for i in range(20)]
    for index, values in ((2, (105,111,99,105)), (10, (105,110,99,105)),
                          (6, (95,101,90,95)), (14, (95,101,91,95))):
        bars[index].update(zip(('open','high','low','close'), values))
    triggers = [{'timestamp': CLOCK-(5-i)*trigger, 'open': 100, 'high': 102, 'low': 98, 'close': 100}
                for i in range(5)]
    triggers[-1].update(open=106,high=109,low=102,close=104) if short else triggers[-1].update(open=94,high=98,low=92,close=96)
    track = {'base_timeframe': base, 'trigger_timeframe': tf, 'base_verified': True,
             'trigger_verified': True, 'direction': None, 'base_structure': 'mixed', 'state': 'waiting_structure'}
    return {base: {'candles': bars}, tf: {'candles': triggers}, 'setup': {'stage':'screening','direction':'long','invalidation':90,'structural_target':110,'reference_rr':1,'reference_close':100}}, track


