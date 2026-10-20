"""Describe saved strategy tracks without changing selection or trade authority."""
from __future__ import annotations


def explain_strategy_track(track):
    """Only explain supplied evidence; do not infer prices, expiry or permission."""
    base = track["base_timeframe"].upper()
    trigger = track["trigger_timeframe"].upper()
    direction = track.get("direction")
    levels = track.get("reference_levels", {})
    reference_plan = track.get("reference_plan", {})
    missing = {}
    for key, label in (("invalidation", "無効化価格"),
                       ("structural_target", "構造目標"),
                       ("reference_rr", "参考RR")):
        if levels.get(key) is None:
            missing[key] = (
                f"{base}の構造方向未確認のため{label}を提示できない"
                if direction not in ("long", "short") else
                f"既存の{base}診断から{label}が提供されていない。数値は推定しない")
            if (direction in ("long", "short") and key in ("structural_target", "reference_rr")
                    and reference_plan.get("status") == "unavailable" and reference_plan.get("reason")):
                missing[key] = f"{base}参考計算: {reference_plan['reason']}。{label}は推定しない"
    invalidated = track.get("trigger_status") == "invalidated"
    pattern = (track.get("trigger_status") == "watch_pattern" if trigger == "M15"
               else track.get("price_action", {}).get("status") == "watch_pattern")
    if not track.get("base_verified"):
        wait = f"{base}の確定足品質・構造を確認する"
    elif direction not in ("long", "short"):
        wait = f"{base}の確定高値・安値の方向成立を待つ"
    elif invalidated:
        wait = f"{trigger}診断で無効化を観測。新しい{base}構造と無効化水準を再評価する"
    elif not track.get("trigger_verified"):
        wait = f"{trigger}の確定足品質・鮮度を確認する"
    elif track.get("timing_assessment") == "counter_rebound_wait":
        wait = f"{trigger}の逆行反応が終了し、監視方向へ再開する反応を確定足で確認する"
    elif pattern:
        wait = f"{trigger}参考パターンを観測済み。次の確定足で継続・無効化を再確認する"
    else:
        wait = f"{trigger}確定足で監視方向の価格反応を待つ。足の鮮度だけでは成立としない"
    return {
        "basis": f"{base}構造={track.get('base_structure', 'unconfirmed')}、方向={direction or '未確認'}。{trigger}で反応を確認する監視用の説明",
        "waiting_condition": wait,
        "formation_evidence": "参考パターン観測済み" if pattern and not invalidated else "参考パターン成立は未確認",
        "invalidation": {
            "price": levels.get("invalidation"),
            "observed": invalidated,
            "basis": "既存診断の水準・無効化状態。新しい到達判定やSL注文条件ではない"},
        "expiry": {
            "status": "not_defined",
            "reason": "既存診断に時間失効の規定なし。期限は推定しない",
            "recheck": "新しい確定足で構造・品質・反応を再評価。保存時判断を現在の許可に流用しない"},
        "unavailable_reasons": missing,
        "authority": "saved_monitoring_explanation_only",
    }
