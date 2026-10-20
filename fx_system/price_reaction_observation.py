"""Explain existing saved M15/M5 diagnostics; never establish scenario formation."""
import math


def _price(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def observe_saved_reaction(data, track, evaluated_at):
    tf = track['trigger_timeframe']; seconds = {'m15': 900, 'm5': 300}[tf]
    result = {'status': 'unverified', 'timeframe': tf, 'evaluated_at': evaluated_at,
              'basis': 'verified_saved_candles_and_existing_diagnostic_v1',
              'advisory_only': True, 'scenario_formation_confirmed': False}
    def unavailable(reason):
        return {**result, 'reason': reason}
    direction = track.get('direction')
    if (track.get('base_verified') is not True or track.get('trigger_verified') is not True
            or direction not in ('long', 'short') or type(evaluated_at) is not int):
        return unavailable('Direction or saved candle quality unverified')
    frame = data.get(tf)
    rows = frame.get('candles', []) if isinstance(frame, dict) else []
    if not isinstance(rows, list) or len(rows) < 4:
        return unavailable('Four saved candles unavailable')
    window = rows[-4:]
    for bar in window:
        if not isinstance(bar, dict):
            return unavailable('Candle invalid')
        stamp = bar.get('timestamp')
        values = [bar.get(k) for k in ('open', 'high', 'low', 'close')]
        if type(stamp) is not int or stamp <= 0 or stamp % seconds or not all(map(_price, values)):
            return unavailable('Candle clock or prices invalid')
        o, h, l, c = values
        if not l <= min(o, c) <= max(o, c) <= h:
            return unavailable('Candle OHLC inconsistent')
    if any(b['timestamp']-a['timestamp'] != seconds for a, b in zip(window, window[1:])):
        return unavailable('Candle window not contiguous')
    latest = window[-1]; stamp = latest['timestamp']; closed_at = stamp+seconds
    if not 0 <= evaluated_at-closed_at < seconds:
        return unavailable('Reaction candle stale or future')
    diagnostic = data.get('m15_entry_shadow' if tf == 'm15' else 'm5_price_action_shadow', {})
    if not isinstance(diagnostic, dict):
        return unavailable('Diagnostic unavailable')
    diagnostic_stamp = diagnostic.get('m15_last_timestamp' if tf == 'm15' else 'last_timestamp')
    high = max(b['high'] for b in window[:-1]); low = min(b['low'] for b in window[:-1])
    breakout = latest['close'] > high if direction == 'long' else latest['close'] < low
    rejection = tf == 'm5' and (
        latest['close'] > latest['open'] and latest['low'] < min(b['low'] for b in window[-3:-1])
        if direction == 'long' else
        tf == 'm5' and latest['close'] < latest['open'] and latest['high'] > max(b['high'] for b in window[-3:-1]))
    pattern = 'three_bar_close_breakout' if breakout else 'two_bar_rejection' if rejection else None
    expected_status = 'watch_pattern' if pattern else 'waiting'
    if (diagnostic.get('advisory_only') is not True or diagnostic.get('direction') != direction
            or diagnostic_stamp != stamp or type(diagnostic_stamp) is not int
            or diagnostic.get('status') != expected_status or diagnostic.get('pattern') != pattern
            or not _price(diagnostic.get('reference_high')) or not _price(diagnostic.get('reference_low'))
            or diagnostic['reference_high'] != high or diagnostic['reference_low'] != low):
        return unavailable('Existing diagnostic and saved candle window disagree')
    return {**result, 'status': 'observed_reference' if pattern else 'not_observed',
            'direction': direction, 'pattern': pattern, 'closed_at': closed_at,
            'window_started_at': window[0]['timestamp'],
            'saved_open': latest['open'], 'saved_high': latest['high'],
            'saved_low': latest['low'], 'saved_close': latest['close'],
            'prior_three_high': high, 'prior_three_low': low,
            'prior_two_high': max(b['high'] for b in window[-3:-1]),
            'prior_two_low': min(b['low'] for b in window[-3:-1]),
            'breakout_observed': breakout, 'rejection_observed': bool(rejection),
            'reason': 'Existing reference pattern only; future candles need a new window'}


def reaction_description(observation):
    """Plain explanation retaining exact prices; no inferred future trigger."""
    r = observation if isinstance(observation, dict) else {}
    if (r.get('status') not in ('observed_reference', 'not_observed')
            or r.get('timeframe') not in ('m5', 'm15')
            or r.get('direction') not in ('long', 'short')
            or r.get('advisory_only') is not True
            or r.get('scenario_formation_confirmed') is not False
            or any(not _price(r.get(k)) for k in ('saved_close', 'prior_three_high',
                                                 'prior_three_low', 'prior_two_high', 'prior_two_low'))
            or any(type(r.get(k)) is not bool for k in ('breakout_observed', 'rejection_observed'))):
        return '価格反応の具体的な観測は未確認です。'
    def price(key):
        return f"{r[key]:.8f}".rstrip('0').rstrip('.')
    long = r['direction'] == 'long'
    level = price('prior_three_high' if long else 'prior_three_low')
    crossing = '上回る' if long else '下回る'
    sentences = [f"保存終値{price('saved_close')}。直前3本の{'高値' if long else '安値'}{level}を{crossing}動きは"
                 + ('観測済み。' if r['breakout_observed'] else '未観測。')]
    if r['timeframe'] == 'm5':
        opposite = price('prior_two_low' if long else 'prior_two_high')
        sentences.append(f"直前2本の{'安値' if long else '高値'}{opposite}を一度{'下回り' if long else '上回り'}、"
                         + f"{'始値より高く' if long else '始値より低く'}引ける反発は"
                         + ('観測済み。' if r['rejection_observed'] else '未観測。'))
    sentences.append('保存された足の参考観測です。シナリオ成立・注文価格ではありません。次の足では比較する直前の足も変わります。')
    return ''.join(sentences)
