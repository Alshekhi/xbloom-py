"""Recipe assembly — loose fields in, a validated recipe dict out.

Pure module: no host framework, no I/O, so it is trivially testable and
reusable by any bridge (the same shape as `brew_scale.py`).

Two layers live here.

**Low level** — `auto_fill_pours`, `redistribute_pours` and `assemble` are what
a form-driven recipe editor needs: suggest a starting set of pours, move an
existing set onto a new total without flattening its shape, and assemble the
final dict. They were methods on the Home Assistant integration's options flow
until they were lifted here, and keep their exact behaviour.

**High level** — `build` is the entry point for callers holding loose,
possibly-invalid fields rather than a validated draft: a recipe read off a web
page, or one described out loud to a voice agent. It snaps every field onto
the grid `spec` defines, records what it changed in plain language, and hands
the result to `validate_recipe`.

The split matters. `spec` says what the *machine* accepts; a pour may pause
for 0-59 seconds and the validator enforces exactly that. The ten-second
pause floor, the sixty-second bloom window and the 3.0 ml/s flow rate are
*brewing preferences* — they shape defaults and snapping in `build`, and are
deliberately absent from the validator, which would otherwise reject recipes
the machine runs happily. `apply_brew_defaults=False` turns them off.
"""
from __future__ import annotations

import uuid
from copy import deepcopy
from dataclasses import dataclass, field as dataclass_field
from typing import Any

from . import spec
from .recipe_validate import (
    denom_to_ratio_str,
    snap_ratio_denom,
    validate_recipe,
)

# Brewing preferences (not machine limits — see the module docstring).
BLOOM_WINDOW_S = 60.0
"""Target total bloom time: the pour itself plus the pause that follows it."""

MIN_PAUSE_S = 10
"""A pause is either none at all or long enough to matter."""

DEFAULT_POUR_PAUSE_S = 10
DEFAULT_FLOW_RATE = 3.0


@dataclass(frozen=True)
class BuildResult:
    """The outcome of `build`.

    `recipe` is always present, even when `ok` is False, so a caller can show
    the user what it made of their input alongside the reasons it was
    rejected. `adjustments` are human-readable and safe to read aloud.
    """

    ok: bool
    recipe: dict
    adjustments: list[str] = dataclass_field(default_factory=list)
    errors: dict[str, str] = dataclass_field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Low level — the pieces a form-driven recipe editor drives.                  #
# --------------------------------------------------------------------------- #
def auto_fill_pours(draft: dict) -> list[dict]:
    """xbloom-app heuristic — D-20 verbatim."""
    ratio_denom = float(draft["ratio"].split(":", 1)[1])
    total_ml = round(draft["dose_g"] * ratio_denom, 1)
    n = max(1, int(draft["pour_count"]))
    per_volume = round(total_ml / n, 1)
    pours: list[dict] = []
    temp_rng = spec.field("pour_temperature_c")
    for i in range(n):
        # Temperature: start 92°C, descend 1°C per subsequent pour.
        temp = max(temp_rng.min, 92 - i * 1)
        pours.append({
            "id": i,
            "recipe_id": 0,
            "name": "",
            "volume_ml": per_volume,
            "temperature_c": float(temp),
            "pattern": spec.PATTERN_NAME_TO_API["spiral"],
            "flow_rate": DEFAULT_FLOW_RATE,
            "pause_s": 0,
            "agitate_before": 2,     # off (2 per client.py convention)
            "agitate_after": 2,
        })
    # Adjust last pour for rounding drift so volumes sum to total exactly.
    drift = round(total_ml - sum(p["volume_ml"] for p in pours), 1)
    if drift:
        pours[-1]["volume_ml"] = round(pours[-1]["volume_ml"] + drift, 1)
    return pours


def redistribute_pours(
    old_pours: list[dict], *, total_ml: float, pour_count: int,
) -> list[dict]:
    """Move an existing set of pours onto a new total, keeping its shape.

    An earlier version levelled every pour to an even split unconditionally,
    so merely stepping through the edit wizard destroyed a custom
    distribution (a 30 ml bloom + 90 ml second pour became 60/60). Three
    cases now:

    * the total has not moved — leave the pours exactly as they are;
    * the total moved — scale each pour by the same factor, so the shape of
      the recipe survives;
    * the volumes are degenerate (all zero) — fall back to an even split.
    """
    old_total = round(sum(float(p["volume_ml"]) for p in old_pours), 1)
    if abs(total_ml - old_total) <= spec.VOLUME_TOLERANCE_ML:
        new_pours = [dict(p) for p in old_pours]
    elif old_total > 0:
        factor = total_ml / old_total
        new_pours = [
            {**p, "volume_ml": round(float(p["volume_ml"]) * factor, 1)}
            for p in old_pours
        ]
    else:
        per_volume = round(total_ml / max(1, pour_count), 1)
        new_pours = [{**p, "volume_ml": per_volume} for p in old_pours]
    drift = round(total_ml - sum(p["volume_ml"] for p in new_pours), 1)
    if drift:
        new_pours[-1]["volume_ml"] = round(new_pours[-1]["volume_ml"] + drift, 1)
    return new_pours


def assemble(draft: dict, pours: list[dict], *, recipe_id: str | None = None) -> dict:
    """Assemble the final recipe dict to hand to the validator + store."""
    cup_label = draft["cup_type_label"]
    cup_int = spec.CUP_LABEL_TO_API[cup_label]
    ratio_denom = float(draft["ratio"].split(":", 1)[1])
    recipe: dict = {
        "id": recipe_id or f"local-{uuid.uuid4()}",
        "name": draft["name"],
        "dose_g": draft["dose_g"],
        "ratio": draft["ratio"],
        "water_ratio": round(draft["dose_g"] * ratio_denom, 1),
        "grind_size": draft["grind_size"],
        "grinder_size": draft["grind_size"],
        "grinder_size_enabled": 1,
        "grinder_speed_rpm": draft["grinder_speed_rpm"],
        "rpm": draft["grinder_speed_rpm"],
        "pour_count": int(draft["pour_count"]),
        "cup_type": cup_int,
        "cup_type_name": cup_label,
        "bypass_water_enabled": 1 if draft["bypass_water_enabled"] else 2,
        "pours": pours,
        "meta": {"created_locally": True},
    }
    if draft["bypass_water_enabled"]:
        if draft.get("bypass_volume_ml") not in (None, ""):
            recipe["bypass_volume_ml"] = float(draft["bypass_volume_ml"])
        if draft.get("bypass_temp_c") not in (None, ""):
            recipe["bypass_temp_c"] = float(draft["bypass_temp_c"])
    return recipe


# --------------------------------------------------------------------------- #
# High level — loose fields in, snapped and validated out.                    #
# --------------------------------------------------------------------------- #
def bloom_pause_s(volume_ml: float) -> int:
    """Pause after the bloom pour, targeting a `BLOOM_WINDOW_S` total.

    The pour itself takes roughly `volume / flow` seconds, so the pause that
    completes the window is the remainder — never shorter than `MIN_PAUSE_S`.
    """
    pour_time = float(volume_ml) / DEFAULT_FLOW_RATE
    return max(MIN_PAUSE_S, round(BLOOM_WINDOW_S - pour_time))


def _num(value: Any) -> float | None:
    """Coerce to float, or None when the value is not a plain number."""
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt(value: float) -> str:
    """Format a number for an adjustment line — no trailing '.0'."""
    return f"{value:g}"


class _Adjustments:
    """Collects the plain-language record of what `build` changed."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def note(self, line: str) -> None:
        self.lines.append(line)

    def snapped(
        self, label: str, before: float, after: float, unit: str = "",
    ) -> None:
        """Record a value that moved onto the grid; silent when it did not."""
        if abs(before - after) > 1e-9:
            self.note(f"{label} {_fmt(before)}{unit} → {_fmt(after)}{unit}")


def _resolve_cup(raw: Any, adj: _Adjustments) -> str:
    """Accept a cup as an api id or a label; fall back to the default."""
    if isinstance(raw, str) and raw.strip():
        for label in spec.CUP_LABEL_TO_API:
            if label.lower() == raw.strip().lower():
                return label
    else:
        as_int = _num(raw)
        if as_int is not None and int(as_int) in spec.VALID_CUP_TYPES:
            return spec.CUP_API_TO_LABEL[int(as_int)]
        if as_int is None:
            return spec.DEFAULT_CUP_LABEL
    adj.note(f"cup type {raw} → {spec.DEFAULT_CUP_LABEL}")
    return spec.DEFAULT_CUP_LABEL


def _resolve_ratio(raw: Any, adj: _Adjustments) -> str:
    """Accept '1:N' or a bare N; snap to the 0.5 grid. Unparseable passes
    through untouched so the validator can report `ratio_invalid`."""
    if isinstance(raw, str):
        try:
            denom = float(raw.split(":", 1)[1])
        except (ValueError, IndexError):
            return raw
    else:
        denom = _num(raw)
        if denom is None:
            return str(raw)
    snapped = snap_ratio_denom(denom)
    if snapped != denom_to_ratio_str(denom):
        adj.note(f"ratio {denom_to_ratio_str(denom)} → {snapped}")
    return snapped


def _resolve_pattern(raw: Any, index: int, adj: _Adjustments) -> int:
    """Accept a pattern by name or api id; fall back to spiral."""
    spiral = spec.PATTERN_NAME_TO_API["spiral"]
    if isinstance(raw, str):
        api = spec.PATTERN_NAME_TO_API.get(raw.strip().lower())
        if api is not None:
            return api
    else:
        as_int = _num(raw)
        if as_int is not None and int(as_int) in spec.VALID_PATTERN_APIS:
            return int(as_int)
    adj.note(f"pour {index + 1} pattern {raw} → spiral")
    return spiral


def _resolve_pause(
    raw: Any, index: int, volume_ml: float, *,
    apply_brew_defaults: bool, adj: _Adjustments,
) -> int:
    """Snap a pause, or supply the default one when none was asked for.

    A pause the caller did not specify is a default, so it is not reported as
    an adjustment; one they did specify and that had to move is.
    """
    rng = spec.field("pour_pause_s")
    supplied = _num(raw)
    if supplied is None:
        if not apply_brew_defaults:
            return 0
        return bloom_pause_s(volume_ml) if index == 0 else DEFAULT_POUR_PAUSE_S

    pause = int(round(supplied))
    # Zero means "no pause at all" — a real choice, not a short pause.
    if apply_brew_defaults and 0 < pause < MIN_PAUSE_S:
        adj.note(f"pour {index + 1} pause {pause}s → {MIN_PAUSE_S}s (minimum)")
        return MIN_PAUSE_S
    clamped = int(rng.snap(pause))
    if clamped != pause:
        adj.note(f"pour {index + 1} pause {pause}s → {clamped}s")
    return clamped


def _resolve_agitate(raw: Any) -> int:
    """1 = vibrate, 2 = off. Anything else is off."""
    value = _num(raw)
    return 1 if value is not None and int(value) == 1 else 2


def build(
    fields: dict, *, apply_brew_defaults: bool = True,
) -> BuildResult:
    """Turn loose recipe fields into a validated recipe.

    Every numeric field is clamped and snapped onto the grid `spec` defines
    rather than rejected, so a caller working from a web recipe or a spoken
    description gets something brewable back plus a list of what moved. Only
    faults that cannot be snapped away — a missing name, more pours than the
    machine accepts — come back as `errors`.

    `fields` accepts: name, dose_g, ratio ('1:N' or N), grind_size,
    grinder_speed_rpm, cup_type (api id or label), pour_count, pours,
    bypass_water_enabled, bypass_volume_ml, bypass_temp_c, id.
    """
    fields = deepcopy(fields)
    adj = _Adjustments()

    cup_label = _resolve_cup(fields.get("cup_type"), adj)
    cup_api = spec.CUP_LABEL_TO_API[cup_label]
    ratio_str = _resolve_ratio(fields.get("ratio"), adj)

    dose_rng = spec.CUP_DOSE[cup_api]
    dose_raw = _num(fields.get("dose_g"))
    if dose_raw is None:
        dose = dose_rng.default
    else:
        dose = dose_rng.snap(dose_raw)
        adj.snapped("dose", dose_raw, dose, "g")

    grind_rng = spec.field("grind_size")
    grind_raw = _num(fields.get("grind_size"))
    if grind_raw is None:
        grind = grind_rng.default
    else:
        grind = grind_rng.snap(grind_raw)
        adj.snapped("grind size", grind_raw, grind)

    rpm_rng = spec.field("grinder_speed_rpm")
    rpm_raw = _num(fields.get("grinder_speed_rpm"))
    if rpm_raw is None:
        rpm = rpm_rng.default
    else:
        rpm = rpm_rng.snap(rpm_raw)
        adj.snapped("grinder speed", rpm_raw, rpm, " RPM")

    raw_pours = fields.get("pours")
    if isinstance(raw_pours, list) and raw_pours:
        pour_count = len(raw_pours)
    else:
        raw_pours = None
        count = _num(fields.get("pour_count"))
        pour_count = int(count) if count is not None else int(
            spec.field("pour_count").default
        )
        pour_count = max(1, pour_count)

    draft = {
        "name": str(fields.get("name") or "").strip(),
        "dose_g": dose,
        "ratio": ratio_str,
        "grind_size": int(grind),
        "grinder_speed_rpm": int(rpm),
        "pour_count": pour_count,
        "cup_type_label": cup_label,
        "bypass_water_enabled": bool(fields.get("bypass_water_enabled")),
        "bypass_volume_ml": fields.get("bypass_volume_ml"),
        "bypass_temp_c": fields.get("bypass_temp_c"),
    }

    # A malformed ratio cannot be turned into pours; hand the validator the
    # bare recipe so it reports `ratio_invalid` instead of raising here.
    try:
        base = auto_fill_pours(draft)
    except (ValueError, IndexError, TypeError):
        recipe = {**draft, "pours": [], "cup_type": cup_api}
        return BuildResult(False, recipe, adj.lines, {"ratio": "ratio_invalid"})

    total_ml = round(dose * float(ratio_str.split(":", 1)[1]), 1)
    temp_rng = spec.field("pour_temperature_c")
    flow_rng = spec.field("pour_flow_rate")

    # Pass 1 — everything except the pauses, which need the final volumes.
    pours: list[dict] = []
    for i in range(pour_count):
        supplied = raw_pours[i] if raw_pours else {}
        if not isinstance(supplied, dict):
            supplied = {}
        pour = dict(base[i])

        volume = _num(supplied.get("volume_ml"))
        if volume is not None:
            pour["volume_ml"] = volume

        temp = _num(supplied.get("temperature_c"))
        if temp is not None:
            pour["temperature_c"] = temp_rng.snap(temp)
            adj.snapped(f"pour {i + 1} temperature", temp, pour["temperature_c"], "°C")

        flow = _num(supplied.get("flow_rate"))
        if flow is not None:
            pour["flow_rate"] = flow_rng.snap(flow)
            adj.snapped(f"pour {i + 1} flow rate", flow, pour["flow_rate"], " ml/s")

        if supplied.get("pattern") is not None:
            pour["pattern"] = _resolve_pattern(supplied["pattern"], i, adj)
        if supplied.get("agitate_before") is not None:
            pour["agitate_before"] = _resolve_agitate(supplied["agitate_before"])
        if supplied.get("agitate_after") is not None:
            pour["agitate_after"] = _resolve_agitate(supplied["agitate_after"])
        if supplied.get("name"):
            pour["name"] = str(supplied["name"])

        pours.append(pour)

    # Volumes: keep the caller's shape, move the total onto dose x ratio.
    before = [p["volume_ml"] for p in pours]
    pours = redistribute_pours(pours, total_ml=total_ml, pour_count=pour_count)
    if [p["volume_ml"] for p in pours] != before:
        adj.note(f"pour volumes rescaled to {_fmt(total_ml)}ml total")

    # Pass 2 — pauses, now that each pour's final volume is known.
    for i, pour in enumerate(pours):
        supplied = raw_pours[i] if raw_pours else {}
        raw_pause = supplied.get("pause_s") if isinstance(supplied, dict) else None
        pour["pause_s"] = _resolve_pause(
            raw_pause, i, pour["volume_ml"],
            apply_brew_defaults=apply_brew_defaults, adj=adj,
        )
        pour["id"] = i

    recipe = assemble(draft, pours, recipe_id=fields.get("id"))
    errors = validate_recipe(recipe)
    return BuildResult(not errors, recipe, adj.lines, errors)
