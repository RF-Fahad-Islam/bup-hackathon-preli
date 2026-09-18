"""Human-readable text built from Directives and Replay numbers (no LLM: always matches the plan)."""
from .directives import Directive
from .replay import Totals


def _hours_text(hours) -> str:
    hs = list(hours)
    runs, start = [], hs[0]
    for a, b in zip(hs, hs[1:] + [None]):
        if b != a + 1:
            runs.append(f"{start:02d}:00-{(a + 1) % 24:02d}:00" if a != start else f"{a:02d}:00-{(a + 1) % 24:02d}:00")
            start = b
    return ", ".join(runs)


def explain(d: Directive) -> str:
    t = d.directive_type
    if t == "no_op":
        text = "Does not affect today's energy schedule; no constraint applied."
    else:
        when = _hours_text(d.hours)
        text = {
            "solar_reduction": f"Usable solar limited to {d.value:g}x of forecast during {when}.",
            "minimum_battery_reserve": f"Battery kept at or above {d.value:g} kWh after each hour in {when}.",
            "no_charge_window": f"Battery charging prohibited during {when}.",
            "no_discharge_window": f"Battery discharging prohibited during {when}.",
            "max_grid_window": f"Grid import capped at {d.value:g} kWh per hour during {when}.",
        }[t]
    if d.source == "tripwire":
        text += " (Degraded mode: language model unavailable, read by pattern fallback.)"
    elif d.reason:
        text += f" Reading: {d.reason}"
    return text


def plan_summary(plan: list[dict], totals: Totals, directives: list[Directive]) -> str:
    charged = sum(p["battery_kwh"] for p in plan if p["battery_action"] == "charge")
    discharged = sum(p["battery_kwh"] for p in plan if p["battery_action"] == "discharge")
    ch_hours = [p["hour"] for p in plan if p["battery_action"] == "charge"]
    dis_hours = [p["hour"] for p in plan if p["battery_action"] == "discharge"]
    applied = sum(d.applies for d in directives)
    parts = [
        f"Cost-optimal plan (linear program) applying {applied} operator directive(s)"
        f" and ignoring {len(directives) - applied} irrelevant note(s).",
    ]
    if ch_hours:
        parts.append(f"Charges {charged:.2f} kWh during {_hours_text(ch_hours)}.")
    if dis_hours:
        parts.append(f"Discharges {discharged:.2f} kWh during {_hours_text(dis_hours)}.")
    parts.append(
        f"Grid import {totals.total_grid_kwh:.2f} kWh (peak {totals.peak_grid_kwh:.2f} kWh), "
        f"cost {totals.total_cost_bdt:.2f} BDT; battery ends at its starting level."
    )
    return " ".join(parts)
