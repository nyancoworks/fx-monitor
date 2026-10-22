"""Advisory currency strength from the configured 16-pair H1 graph.

Fit r(base/quote) = strength(base) - strength(quote) by equal-edge least
squares, with zero-sum currency scores. No prices, candles or trade gates change.
"""
from __future__ import annotations
import math
import time
from .monitor_pairs import PAIR_KEYS
from .data_quality import evaluate_pair
from .core import expected_closed_timestamp

CURRENCIES = ("USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF")
LOOKBACK = 24
ALGORITHM = "configured16_h1_log_return_graph_ls_v2"


def _connected(edges):
    reached = {CURRENCIES[0]}
    while True:
        added = {c for a, b in edges if a in reached or b in reached for c in (a, b)}
        if added <= reached:
            return len(reached) == len(CURRENCIES)
        reached |= added


def _fit(contributions, currencies=CURRENCIES):
    # Fix the last currency temporarily to zero, then center this component.
    # The default remains the existing all-eight display calculation.
    n = len(currencies) - 1
    matrix = [[0.0] * (n + 1) for _ in range(n)]
    for pair, row in contributions.items():
        a, b = currencies.index(pair[:3]), currencies.index(pair[3:])
        r = row["_return"]
        for i, sign in ((a, 1), (b, -1)):
            if i == n:
                continue
            matrix[i][i] += 1
            matrix[i][-1] += sign * r
            other = b if i == a else a
            if other != n:
                matrix[i][other] -= 1
    for column in range(n):
        pivot = max(range(column, n), key=lambda i: abs(matrix[i][column]))
        matrix[column], matrix[pivot] = matrix[pivot], matrix[column]
        if abs(matrix[column][column]) < 1e-12:
            raise ValueError("strength graph singular")
        scale = matrix[column][column]
        matrix[column] = [v / scale for v in matrix[column]]
        for i in range(n):
            if i != column:
                factor = matrix[i][column]
                matrix[i] = [v - factor * p for v, p in zip(matrix[i], matrix[column])]
    raw = [row[-1] for row in matrix] + [0.0]
    mean = sum(raw) / len(raw)
    return dict(zip(currencies, (v - mean for v in raw)))


def compute_strength(snapshot, lookback=LOOKBACK, now=None):
    now = int(time.time()) if now is None else int(now)
    if type(lookback) is not int or not 1 <= lookback <= 720:
        raise ValueError("lookback must be 1..720 H1 bars")
    end = expected_closed_timestamp("h1", now)
    start = end - lookback * 3600
    contributions, excluded = {}, {}
    observations = {c: 0 for c in CURRENCIES}
    for pair in PAIR_KEYS:
        data = snapshot.get("pairs", {}).get(pair)
        if not isinstance(data, dict):
            excluded[pair] = "missing_pair"
            continue
        frames, _ = evaluate_pair(data, now)
        bars = frames["h1"]
        if not bars or bars[-1]["timestamp"] != end:
            excluded[pair] = "latest_verified_closed_h1_missing"
            continue
        window = bars[-lookback - 1:]
        if (len(window) != lookback + 1 or
                [b["timestamp"] for b in window] != list(range(start, end + 1, 3600))):
            excluded[pair] = "continuous_verified_h1_window_insufficient"
            continue
        change = 100 * (math.log(window[-1]["close"]) - math.log(window[0]["close"]))
        contributions[pair] = {"_return": change, "log_return_pct": round(change, 8),
                               "start_timestamp": start, "end_timestamp": end}
        for c in (pair[:3], pair[3:]):
            observations[c] += 1
    connected = _connected([(p[:3], p[3:]) for p in contributions])
    scores = _fit(contributions) if connected else {c: None for c in CURRENCIES}
    residuals = []
    for pair, row in contributions.items():
        actual = row.pop("_return")
        fitted = scores[pair[:3]] - scores[pair[3:]] if connected else None
        row["fitted_log_return_pct"] = round(fitted, 8) if connected else None
        row["residual_log_return_pct"] = round(actual - fitted, 8) if connected else None
        if connected:
            residuals.append(actual - fitted)
    ranking = sorted(CURRENCIES, key=lambda c: (-scores[c], c)) if connected else []
    return {"algorithm": ALGORITHM, "advisory_only": True, "evaluated_at": now,
            "status": "complete" if len(contributions) == len(PAIR_KEYS) else
                      "provisional" if connected else "unavailable",
            "universe": "16_pairs", "lookback_h1_bars": lookback,
            "start_timestamp": start, "end_timestamp": end,
            "start_closed_at": start + 3600, "end_closed_at": end + 3600,
            "coverage_pairs": len(contributions), "expected_pairs": len(PAIR_KEYS),
            "connected_all_currencies": connected,
            "scores": {c: round(v, 5) if v is not None else None for c, v in scores.items()},
            "ranking": ranking, "observations": observations,
            "pair_contributions": contributions, "excluded_pairs": excluded,
            "fit_rmse_log_pct": round(math.sqrt(sum(v*v for v in residuals) / len(residuals)), 8)
                                if residuals else None,
            "note": "16監視ペアのH1終値24時間変化を使う相対強弱。全8通貨の接続が必要。"
                    "スコアはゼロ和の対数変化率尺度で、騰落率そのもの・勝率・売買許可ではありません。"
                    "観測数と残差を併記し、28クロス完全指数とは扱いません。"}
