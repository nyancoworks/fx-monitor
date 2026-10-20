"""Expose existing timeframe-specific RCI observations without changing decisions."""
from copy import deepcopy


def _dict(value):
    return value if isinstance(value, dict) else {}


def rci_track_context(data, track, evaluated_at):
    frames = {}
    for role, flag in (("base", "base_verified"), ("trigger", "trigger_verified")):
        tf = track[role + "_timeframe"]
        if tf == "m5":
            # Reuse the existing M5 diagnostic; do not calculate a second version.
            momentum = _dict(track.get("rci_momentum")) if track.get(flag) is True else {}
            frames[role] = {
                "timeframe": tf,
                "status": momentum.get("status", "unverified"),
                "source": "existing_m5_rci_momentum",
                "periods": deepcopy(momentum.get("rci", {})),
                "limitation": "M5の極端水準継続本数はこの既存診断では未提供",
            }
            continue
        research = _dict(_dict(data.get("indicator_research")).get(tf))
        observation = _dict(research.get("rci_observation"))
        stamp = observation.get("last_timestamp")
        usable = (track.get(flag) is True and type(stamp) is int and
                  type(evaluated_at) is int and
                  stamp + {"h4":14400,"h1":3600,"m15":900}[tf] <= evaluated_at and
                  isinstance(observation.get("periods"),dict))
        frames[role] = {
            "timeframe": tf,
            "status": "observed_reference" if usable else "unverified",
            "last_timestamp": stamp if usable else None,
            "periods": deepcopy(observation.get("periods", {})) if usable else {},
            "reason": ("同じ時間足の保存済み参考計算。観測本数と経過時間は別"
                       if usable else "当該時間足の品質またはRCI履歴観測が未確認"),
            "extreme_level_basis": observation.get("extreme_level_basis") if usable else None,
        }
    return {"frames": frames, "affects_selection": False,
            "interpretation": "傾き・転換・クロス・極端水準の継続は観測の説明であり、単独の反転や売買許可ではない"}
