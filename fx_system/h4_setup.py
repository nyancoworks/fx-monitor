"""Read-only H4-first setup diagnostic; legacy H1 decisions remain untouched."""
from .core import technical
from .h4_reference_plan import h4_reference_plan

def h4_setup_diagnostic(frames):
    h4=frames.get("h4",[])
    h1=frames.get("h1",[])
    if len(h4)<35 or len(h1)<35:
        return {"stage":"h4_setup","status":"insufficient","direction":None,"entry_confirmed":False}
    macro={tf:technical(frames.get(tf,[])).get("structure","unconfirmed") for tf in ("w1","d1")}
    h4_analysis=technical(h4)
    h4_structure=h4_analysis.get("structure","unconfirmed")
    h1_structure=technical(h1).get("structure","unconfirmed")
    direction={"HH_HL":"long","LH_LL":"short"}.get(h4_structure)
    if direction is None:
        return {"stage":"h4_setup","status":"unconfirmed","direction":None,"h4_structure":h4_structure,
                "macro_structure":macro,"h1_structure":h1_structure,"entry_confirmed":False}
    invalidation_key="confirmed_swing_lows" if direction=="long" else "confirmed_swing_highs"
    swings=h4_analysis.get(invalidation_key,[])
    invalidation=swings[-1]["price"] if swings else None
    reference=h4_reference_plan(h4,h4_analysis,direction,invalidation)
    return {"stage":"h4_setup","status":"watch_only","direction":direction,
            "h4_structure":h4_structure,"macro_structure":macro,"h1_structure":h1_structure,
            "invalidation":invalidation,"entry_confirmed":False,
            "structural_target":reference["structural_target"],
            "reference_rr":reference["reference_rr"],"reference_plan":reference,
            "note":"H4-first shadow diagnostic; no trading grade or order authority"}

