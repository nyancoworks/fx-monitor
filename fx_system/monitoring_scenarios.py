"""Explain existing monitoring evidence; never calculate or authorize a trade.

Teacher names describe the user's reference framework, not reproduced rules.
All observations are scoped to the supplied saved evaluation clock.
"""
from __future__ import annotations

from copy import deepcopy
import math
from .monitor_pairs import PAIR_KEYS
from .watchlist import candidate


LABELS = {"watch": "監視候補", "waiting": "条件待ち",
          "skip": "見送り", "unassessed": "未評価"}
REASONS = {
    "h1_direction_unclear": "H1の確定高値・安値から方向を確認できない",
    "higher_timeframe_conflict": "H4とH1の方向が逆向き",
    "rr_below_minimum": "構造上の目標までの参考RRが1.5未満",
    "structural_invalidation": "構造上の無効化水準を超えた",
    "structural_target_missing": "進行方向の構造上の目標が未確認",
    "stop_distance_review": "構造上の損切り幅の再確認が必要",
    "history_insufficient": "H1またはH4の履歴が不足",
    "data_not_ready": "検証済み判断データが不足または品質不合格",
    "other_structural_rejection": "既存の構造条件を満たしていない",
}
NEXT = {
    "h4_h1_alignment": "H4とH1の確定した高値・安値の方向一致を確認",
    "verified_zone": "押し目・戻りの候補帯を独立に検証（提案帯は未検証）",
    "m5_price_action": "M5確定足で押し目・戻り、または突破後の再試しと追随を確認",
    "m5_verification": "M5の欠損・鮮度・パターン診断を再確認",
}


def _m5_rejection(reason):
    if reason == "structural target RR below minimum":
        return "M5基準の構造目標までの参考RRが最低基準未満"
    return "M5診断で失格（理由要確認）"


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _finite(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def _indicator_notes(data, quality, ready):
    observations = {}
    for timeframe in ("d1", "h4", "h1", "m15", "m5"):
        research = _mapping(_mapping(data.get("indicator_research")).get(timeframe))
        checked = ready and _mapping(_mapping(quality.get("timeframes")).get(timeframe)).get("ok") is True
        rci = _mapping(research.get("rci")) if checked else {}
        band = _mapping(research.get("band_research")) if checked else {}
        observations[timeframe] = {
            "rci": {period: {"value": _finite(rci.get(period)), "role": role}
                    for period, role in (("9", "短期タイミング"), ("26", "中期の勢い"), ("52", "長期の勢い"))},
            "bandwidth_change": _finite(band.get("bandwidth_change")),
            "middle_slope": _finite(band.get("middle_slope")),
            "lagged_close_comparison": band.get("lagged_close_comparison") if band.get("lagged_close_comparison") in ("above", "below", "equal") else None,
            "super_bollinger_chart_parity_verified": False,
        }
    return {"timeframes": observations, "affects_scenario_state": False,
            "limitations": ["RCI直近値から傾き・クロス・張り付き継続を推測しない",
                            "21本前終値との比較は遅行スパン対ローソク足の位置・絡みや正式陽転を検証しない",
                            "ディナポリMACD・ストキャス・DMAとSMA100/200は参考根拠であり、売買許可を生成しない"]}


def _saved_ready(data, quality):
    # A raw retained series or quality.ok alone does not attest decision provenance.
    return quality.get("ok") is True and _mapping(data.get("decision_quality")).get("ready") is True


def _explain(pair, data, quality, evaluated_at, current_freshness):
    data, quality = _mapping(data), _mapping(quality)
    setup = _mapping(data.get("setup"))
    local_clock = _mapping(data.get("decision_quality")).get("evaluated_at")
    valid_clock = (type(evaluated_at) is int and evaluated_at > 0 and
                   type(local_clock) is int and local_clock == evaluated_at)
    valid_nested = isinstance(data.get("setup"), dict) and all(
        key not in setup or isinstance(setup[key], dict)
        for key in ("m5_entry_check", "zone_proposal"))
    ready = _saved_ready(data, quality) and valid_clock and valid_nested
    clean_setup = {**setup, **{key: _mapping(setup.get(key))
                              for key in ("m5_entry_check", "zone_proposal")}}
    # Reuse structural shortlist evidence; legacy permission inputs are ignored.
    adapted = {**data, "setup": clean_setup,
               "decision_quality": {"ready": ready, "evaluated_at": local_clock}}
    row = candidate(pair, adapted, quality)
    qualification = row["method_qualification"]
    basis, missing, exclusions = [], [], []
    direction = row["direction"]
    if not ready:
        state = "unassessed"
        exclusions.append("保存時の評価時計が不正または一致しない" if not valid_clock else
                          "判断入力の構造が不正" if not valid_nested else REASONS["data_not_ready"])
        direction = None
    elif row["status"] != "watch_candidate":
        state = "skip"
        exclusions.append(_m5_rejection(row["m5"]["reason"]) if row["m5"]["status"] == "invalidated" and
                          row["reason_code"] == "other_structural_rejection" else
                          REASONS.get(row["reason_code"], REASONS["other_structural_rejection"]))
    elif row["m5"]["status"] == "invalidated":
        state = "skip"
        exclusions.append(_m5_rejection(row["m5"]["reason"]))
    else:
        basis.append("H1の構造方向と構造目標までの参考RRを既存診断で確認")
        if not qualification["h4_h1_aligned"]:
            missing.append("h4_h1_alignment")
        if not qualification["zone_verified"]:
            missing.append("verified_zone")
        m5 = row["m5"]["status"]
        if m5 == "waiting":
            missing.append("m5_price_action")
        elif m5 != "pattern_detected":
            missing.append("m5_verification")
        else:
            basis.append("既存M5診断でパターンを検出（正式トリガーの検証とは別）")
        state = "waiting" if missing else "watch"
    saved_state = state
    next_conditions = [NEXT[key] for key in missing]
    if saved_state in ("skip", "unassessed"):
        next_conditions.append("次の検証済み確定足で構造・品質を再評価")
    if current_freshness != "fresh":
        next_conditions.append("現在の確定足の鮮度を別途確認")
    # Reporting judgment is deliberately distinct from the historical watchlist:
    # a positive H1 reference RR is NOT sufficient when H4 is mixed or opposed.
    h4 = row["h4_structure"]
    expected = {"long": "HH_HL", "short": "LH_LL"}.get(direction)
    opposite = {"long": "LH_LL", "short": "HH_HL"}.get(direction)
    if not ready:
        decision = "データ未評価（売買見送り）"
        primary_blocker = exclusions[0] if exclusions else REASONS["data_not_ready"]
    elif state == "skip":
        decision = "構造条件不成立（売買見送り）"
        primary_blocker = exclusions[0] if exclusions else "既存の構造条件を満たさない"
    elif h4 == opposite and expected is not None:
        decision = "H4とH1が逆方向（売買見送り）"
        primary_blocker = "H4の確定高値・安値がH1の監視方向と逆"
    elif expected is not None and h4 != expected:
        decision = "H4方向未確認（条件待ち・売買見送り）"
        primary_blocker = ("H4は方向混在" if h4 == "mixed"
                           else "H4方向が確認できない")
    elif missing:
        decision = "H4/H1方向一致・残条件待ち（売買見送り）"
        primary_blocker = next_conditions[0] if next_conditions else "売買条件未確認"
    else:
        decision = "価格構造の監視候補（正式売買許可なし）"
        primary_blocker = "正式売買ゲートの独立確認待ち"
    return {
        "candidate_decision": {
            "action": decision, "primary_blocker": primary_blocker,
            "first_next_check": next_conditions[0] if next_conditions else None,
            "h4_structure": h4, "h1_reference_direction": direction,
            "authority": "explanatory_only"
        },
        "pair": pair, "state": state, "label": LABELS[state],
        "saved_state": saved_state, "evaluated_at": evaluated_at,
        "current_freshness": current_freshness,
        "current_actionability": "stale" if current_freshness == "stale" else "unassessed",
        "direction": direction,
        "direction_label": {"long": "買い方向の監視", "short": "売り方向の監視"}.get(direction, "方向未確認"),
        "basis": basis, "next_conditions": next_conditions,
        "missing_monitoring_conditions": missing, "exclusion_reasons": exclusions,
        "source_reason": row["reason"], "source_reason_code": row["reason_code"],
        "m5_source_reason": row["m5"]["reason"],
        "h4_structure": row["h4_structure"],
        "reference_levels": {"invalidation": row["invalidation"],
                             "target": row["structural_target"], "rr": row["reference_rr"],
                             "executable_price": False},
        "authority": "saved_monitoring_explanation_only",
        "indicator_observations": _indicator_notes(data, quality, ready),
    }


def build_monitoring_scenarios(pairs, qualities, *, evaluated_at, current_freshness="unverified"):
    """Return every configured pair, including missing inputs as unassessed.

    ``fresh`` requires separate caller verification at report time; saved quality
    never implies current freshness. No indicators, event clearance, quote feed,
    macro approval or proprietary trading rules are inferred by this function.
    """
    if current_freshness not in ("fresh", "stale", "unverified"):
        raise ValueError("current_freshness must be fresh, stale, or unverified")
    pairs, qualities = _mapping(pairs), _mapping(qualities)
    rows = []
    for pair in PAIR_KEYS:
        try:
            row = _explain(pair, pairs.get(pair), qualities.get(pair), evaluated_at, current_freshness)
        except (TypeError, ValueError, AttributeError) as exc:
            # Isolate malformed saved diagnostics. Do not expose inputs, URLs,
            # exception text, or infer authority from a partially parsed pair.
            row = _explain(pair, {}, {}, evaluated_at, current_freshness)
            row["exclusion_reasons"] = ["判断入力の型が不正なため当該ペアは未評価"]
            row["error_type"] = type(exc).__name__
        rows.append(row)
    return {
        "schema": "monitoring_scenarios_v1", "evaluated_at": evaluated_at,
        "advisory_only": True,
        "current_freshness": current_freshness, "rows": rows,
        "counts": {state: sum(row["state"] == state for row in rows) for state in LABELS},
        "method_roles": {
            "primary": "確定足の価格構造・無効化・目標・プライスアクションによる条件付きシナリオ",
            "scenario_reference": "小林芳彦氏の売買方針・市場シナリオを参考。本人の正式手法の再現ではない",
            "super_bollinger": "マーフィー氏の考え方を参考。バンド・遅行スパンのチャート一致と正式条件は未検証",
            "rci": "RCI9/26/52は短中長期の勢いの参考。ヒロピー氏・小林氏の正式手法の再現ではない",
            "auxiliary": "ディナポリMACD・ストキャス・DMAとSMA100/200は補助。短期足SMA100/200を判断根拠にしない",
            "authority": "指標の多数決・AND条件を追加せず、正式A/B・entryゲートを変更しない",
        },
        "note": "保存時監視シナリオ。材料・経済指標・執行価格の独立確認と正式売買許可は別",
    }
