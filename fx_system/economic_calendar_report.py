"""Read-only display of optional saved calendar evidence."""


def _text(value):
    return ' '.join(value.split()) if isinstance(value, str) else '未記録'


def _clock(value, format_clock):
    if type(value) is not int:
        return '未確認'
    try:
        return format_clock(value)
    except (OverflowError, OSError, ValueError):
        return '保存形式未確認'


def _event_clock(event, format_clock):
    stamp = event.get('scheduled_at_utc')
    if type(stamp) is int:
        return _clock(stamp, format_clock)
    first, last = event.get('time_window_start_utc'), event.get('time_window_end_utc')
    if type(first) is int and type(last) is int and first <= last:
        return f"発表時間帯 {_clock(first, format_clock)}〜{_clock(last, format_clock)}（正確な時刻未確定）"
    lower, upper = event.get('date_window_start'), event.get('date_window_end')
    if lower and upper:
        return f"出典の日付範囲 {_text(lower)}〜{_text(upper)}（日時未確定）"
    return f"出典の日付 {_text(event.get('date'))}（時刻・JST換算未確定）"


def calendar_lines(record, format_clock):
    context = record.get('economic_calendar_context')
    if not isinstance(context, dict):
        return []
    if context.get('status') not in ('available', 'partial'):
        return ['経済指標：検証済み情報なし']
    events = context.get('events')
    if not isinstance(events, list):
        return ['経済指標：保存形式未確認']
    lines = []
    if type(context.get('observed_at_utc')) is int:
        lines.append(f"経済指標取得：{_clock(context['observed_at_utc'], format_clock)}｜鮮度・網羅性は未検証（取得時刻は出典確認時刻と別）")
    for event in events[:3]:
        if not isinstance(event, dict) or not isinstance(event.get('currency'), str):
            continue
        if type(event.get('scheduled_at_utc')) is not int and 'time_precision' not in event:
            continue
        title = _text(event.get('title') or event.get('name') or '指標名未確認')[:64]
        timing = ('発表予定' if event.get('timing') == 'upcoming' else
                  '日時未確定' if event.get('timing') == 'uncertain' else '発表時間帯')
        provider_status, provider_impact = event.get('provider_status'), event.get('impact')
        status = ({'estimated': '暫定予定', 'rescheduled': '日程変更', 'cancelled': '中止',
                   'released': '提供元は発表済み扱い（実績取得とは別）'}.get(provider_status)
                  if isinstance(provider_status, str) else None)
        impact = ({'high': '高', 'medium': '中', 'low': '低'}.get(provider_impact, '未確認')
                  if isinstance(provider_impact, str) else '未確認')
        lines.append(f"経済指標（参考）：{event['currency']} {title}｜{_event_clock(event, format_clock)}｜{status or timing}｜重要度 {impact}")
        if event.get('time_role'):
            role = ('入札締切（結果発表時刻とは別）' if event['time_role'] == 'auction-close'
                    else _text(event['time_role']))
            lines.append('時刻の意味（提供元）：'+role)
        if event.get('freshness') == 'stale':
            lines.append('出典状態：古い保存情報。最新日程・実績は未確認')
        if type(event.get('last_verified_at_utc')) is int:
            lines.append('提供元記録の出典確認：'+_clock(event['last_verified_at_utc'], format_clock)+'（現在の鮮度保証ではない）')
        if 'actual_raw' in event:
            lines.append(f"実績（保存文字列）：{_text(event.get('actual_raw'))}｜市場予想：{_text(event.get('consensus_raw'))}｜前回：{_text(event.get('prior_raw'))}。単位変換・サプライズ計算なし。保存時点の値で、過去公表時の初報再現ではない")
        if event.get('source_name') or event.get('source_url'):
            lines.append('元出典：'+_text(event.get('source_name'))+' '+_text(event.get('source_url')))
        for key in ('source_license', 'source_rights'):
            metadata = event.get(key)
            if isinstance(metadata, dict):
                # Keep full upstream notices in the saved event and display credit
                # without substituting Finance Calendar's own attribution.
                parts = [_text(metadata[k]) for k in ('attribution', 'attribution_url', 'source_url', 'url', 'terms_url', 'notice')
                         if isinstance(metadata.get(k), str) and metadata[k]]
                if metadata.get('adapted') is True:
                    parts.append('提供元による加工あり')
                if parts:
                    lines.append('元出典の権利・credit：'+'｜'.join(parts))
        credits = event.get('observation_credits')
        if isinstance(credits, list):
            for credit in credits:
                if not isinstance(credit, dict):
                    continue
                for key in ('source_license', 'source_rights'):
                    metadata = credit.get(key)
                    if isinstance(metadata, dict):
                        parts = [_text(metadata[k]) for k in ('spdx', 'url', 'attribution', 'policy', 'vintage_notice')
                                 if isinstance(metadata.get(k), str) and metadata[k]]
                        if parts:
                            lines.append('数値出典のcredit：'+'｜'.join(parts))
    if not events:
        lines.append('経済指標：対象期間に確認できたイベントなし（完全性は別途確認）')
    if len(events) > 3:
        lines.append(f'経済指標：ほか{len(events)-3}件は保存評価を参照')
    if any(isinstance(e, dict) and e.get('timing') == 'uncertain' for e in events[3:]):
        lines.append('非掲載に日時未確定の指標あり。保存評価を参照')
    if context.get('status') == 'partial':
        lines.append('経済指標：参考入力は部分的。空欄・非掲載をイベントなしや安全とは扱わない')
    if context.get('omitted_count') or context.get('warnings'):
        lines.append('経済指標：入力に未収録・形式未確認等の制約あり。保存評価の詳細を参照')
    if context.get('attribution_url') == 'https://www.financecalendar.com':
        lines.append('経済指標データ出典：https://www.financecalendar.com')
    lines.append('経済指標は参考情報。市場反応未評価、A/B/C・売買方向は不変更。')
    return lines
