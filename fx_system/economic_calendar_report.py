"""Read-only display of optional saved calendar evidence."""


def calendar_lines(record, format_clock):
    context = record.get("economic_calendar_context")
    if not isinstance(context, dict):
        return []
    if context.get("status") not in ("available", "partial"):
        return ["経済指標：検証済み情報なし"]
    events = context.get("events")
    if not isinstance(events, list):
        return ["経済指標：保存形式未確認"]
    lines = []
    for event in events[:3]:
        if not isinstance(event, dict):
            continue
        currency, timestamp = event.get("currency"), event.get("scheduled_at_utc")
        if not isinstance(currency, str) or type(timestamp) is not int:
            continue
        title = " ".join(str(event.get("title") or "指標名未確認").split())[:64]
        timing = "発表予定" if event.get("timing") == "upcoming" else "発表時間帯"
        try:
            display_clock = format_clock(timestamp)
        except (OverflowError, OSError, ValueError):
            lines.append("経済指標：イベント時刻の保存形式未確認")
            continue
        lines.append(f"経済指標（参考）：{currency} {title}｜{display_clock}｜{timing}")
    if not lines:
        lines.append("経済指標：対象期間に確認できたイベントなし（完全性は別途確認）")
    if len(events) > 3:
        lines.append(f"経済指標：ほか{len(events)-3}件は保存評価を参照")
    attribution = context.get("attribution_url")
    if attribution == "https://www.financecalendar.com":
        lines.append("経済指標データ出典：https://www.financecalendar.com")
    lines.append("経済指標は参考情報。市場反応未評価、A/B/C・売買方向は不変更。")
    return lines
