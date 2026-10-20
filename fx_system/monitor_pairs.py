"""Single monitor/strength configuration; pinned historical evidence stays separate."""
import json
from pathlib import Path

LEGACY_PAIRS = ('EUR/USD','GBP/USD','USD/JPY','AUD/USD','NZD/USD','USD/CAD','USD/CHF',
                'EUR/JPY','GBP/JPY','AUD/JPY','EUR/GBP','EUR/AUD','AUD/NZD')
PINNED_ORIGINAL_PAIRS = tuple(p.replace('/', '') for p in LEGACY_PAIRS)

def load_pairs(path=None):
    data = json.loads(Path(path or Path(__file__).with_name('monitor_pairs.json')).read_text())
    pairs = data.get('pairs')
    currencies = {'USD','EUR','GBP','JPY','AUD','NZD','CAD','CHF'}
    if (data.get('schema') != 1 or not isinstance(pairs,list) or not pairs or
        any(not isinstance(p,str) or len(p)!=7 or p[3]!='/' or
            p[:3] not in currencies or p[4:] not in currencies or p[:3]==p[4:]
            for p in pairs) or len(set(pairs)) != len(pairs) or
        len({frozenset(p.split('/')) for p in pairs}) != len(pairs)):
        raise ValueError('invalid monitor pair configuration')
    return tuple(pairs)

PAIRS = load_pairs()
PAIR_KEYS = tuple(p.replace('/', '') for p in PAIRS)
