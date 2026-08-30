"""Tests for the recipe builder (xbloom/recipe_build.py).

Two layers are covered:

* the low-level helpers a form-driven editor drives — `auto_fill_pours`,
  `redistribute_pours`, `assemble` — whose behaviour must not change, since
  the Home Assistant integration's recipe wizard calls them;
* `build`, the loose-fields entry point, which snaps every field to the spec
  grid and reports what it changed.
"""
from __future__ import annotations

from xbloom import recipe_build, spec
from xbloom.recipe_validate import validate_recipe


def _vols(pours: list[dict]) -> list[float]:
    return [p["volume_ml"] for p in pours]


def _minimal(**over) -> dict:
    """Smallest field set a caller can supply."""
    return {"name": "Test", "dose_g": 18.0, "ratio": "1:16", **over}


# --------------------------------------------------------------------------- #
# auto_fill_pours — the xBloom-app heuristic (D-20), moved verbatim.           #
# --------------------------------------------------------------------------- #
def test_auto_fill_total_is_dose_times_ratio() -> None:
    pours = recipe_build.auto_fill_pours(
        {"dose_g": 18.0, "ratio": "1:16", "pour_count": 3}
    )
    assert sum(_vols(pours)) == 288.0


def test_auto_fill_splits_evenly() -> None:
    pours = recipe_build.auto_fill_pours(
        {"dose_g": 20.0, "ratio": "1:15", "pour_count": 3}
    )
    assert _vols(pours) == [100.0, 100.0, 100.0]


def test_auto_fill_absorbs_rounding_drift_into_the_last_pour() -> None:
    pours = recipe_build.auto_fill_pours(
        {"dose_g": 18.0, "ratio": "1:16", "pour_count": 7}
    )
    assert sum(_vols(pours)) == 288.0
    assert pours[-1]["volume_ml"] != pours[0]["volume_ml"]


def test_auto_fill_temperature_descends_one_degree_per_pour() -> None:
    pours = recipe_build.auto_fill_pours(
        {"dose_g": 18.0, "ratio": "1:16", "pour_count": 4}
    )
    assert [p["temperature_c"] for p in pours] == [92.0, 91.0, 90.0, 89.0]


def test_auto_fill_temperature_never_goes_below_the_spec_floor() -> None:
    pours = recipe_build.auto_fill_pours(
        {"dose_g": 18.0, "ratio": "1:16", "pour_count": 90}
    )
    floor = spec.field("pour_temperature_c").min
    assert min(p["temperature_c"] for p in pours) == floor


def test_auto_fill_uses_the_spiral_pattern_api_id() -> None:
    pours = recipe_build.auto_fill_pours(
        {"dose_g": 18.0, "ratio": "1:16", "pour_count": 1}
    )
    assert pours[0]["pattern"] == spec.PATTERN_NAME_TO_API["spiral"]


def test_auto_fill_leaves_pause_at_zero() -> None:
    """The Configure wizard's own default — the bloom formula is a `build`
    policy, not part of the app heuristic."""
    pours = recipe_build.auto_fill_pours(
        {"dose_g": 18.0, "ratio": "1:16", "pour_count": 3}
    )
    assert [p["pause_s"] for p in pours] == [0, 0, 0]


# --------------------------------------------------------------------------- #
# redistribute_pours — preserve a custom distribution across an edit.          #
# --------------------------------------------------------------------------- #
_CUSTOM = [
    {"volume_ml": 30.0, "temperature_c": 92.0, "pattern": 3, "flow_rate": 3.0,
     "pause_s": 40, "agitate_before": 2, "agitate_after": 2},
    {"volume_ml": 90.0, "temperature_c": 91.0, "pattern": 2, "flow_rate": 3.0,
     "pause_s": 10, "agitate_before": 2, "agitate_after": 2},
]


def test_redistribute_is_a_no_op_when_the_total_has_not_moved() -> None:
    out = recipe_build.redistribute_pours(_CUSTOM, total_ml=120.0, pour_count=2)
    assert _vols(out) == [30.0, 90.0]


def test_redistribute_scales_proportionally_when_the_total_moved() -> None:
    """A 30/90 shape must survive a dose change, not be flattened to 60/60."""
    out = recipe_build.redistribute_pours(_CUSTOM, total_ml=240.0, pour_count=2)
    assert _vols(out) == [60.0, 180.0]


def test_redistribute_falls_back_to_an_even_split_when_volumes_are_degenerate() -> None:
    zeros = [{**p, "volume_ml": 0.0} for p in _CUSTOM]
    out = recipe_build.redistribute_pours(zeros, total_ml=200.0, pour_count=2)
    assert _vols(out) == [100.0, 100.0]


def test_redistribute_absorbs_drift_into_the_last_pour() -> None:
    out = recipe_build.redistribute_pours(_CUSTOM, total_ml=289.0, pour_count=2)
    assert sum(_vols(out)) == 289.0


def test_redistribute_carries_every_other_field_through_untouched() -> None:
    out = recipe_build.redistribute_pours(_CUSTOM, total_ml=240.0, pour_count=2)
    assert out[0]["pause_s"] == 40
    assert out[1]["pattern"] == 2


# --------------------------------------------------------------------------- #
# assemble — the final dict shape.                                            #
# --------------------------------------------------------------------------- #
_DRAFT = {
    "name": "Assembled",
    "dose_g": 18.0,
    "ratio": "1:16",
    "grind_size": 50,
    "grinder_speed_rpm": 90,
    "pour_count": 3,
    "cup_type_label": "Omni dripper",
    "bypass_water_enabled": False,
}


def test_assemble_round_trips_through_the_validator() -> None:
    pours = recipe_build.auto_fill_pours(_DRAFT)
    recipe = recipe_build.assemble(_DRAFT, pours)
    assert validate_recipe(recipe) == {}


def test_assemble_mirrors_the_doubled_field_names() -> None:
    """The machine blob reads `grinder_size`/`rpm`; the validator reads
    `grind_size`/`grinder_speed_rpm`. Both must be present."""
    recipe = recipe_build.assemble(_DRAFT, recipe_build.auto_fill_pours(_DRAFT))
    assert recipe["grind_size"] == recipe["grinder_size"] == 50
    assert recipe["grinder_speed_rpm"] == recipe["rpm"] == 90


def test_assemble_computes_water_ratio_as_total_millilitres() -> None:
    recipe = recipe_build.assemble(_DRAFT, recipe_build.auto_fill_pours(_DRAFT))
    assert recipe["water_ratio"] == 288.0


def test_assemble_maps_the_cup_label_to_its_api_id() -> None:
    recipe = recipe_build.assemble(_DRAFT, recipe_build.auto_fill_pours(_DRAFT))
    assert recipe["cup_type"] == spec.CUP_LABEL_TO_API["Omni dripper"]
    assert recipe["cup_type_name"] == "Omni dripper"


def test_assemble_marks_bypass_off_as_two() -> None:
    recipe = recipe_build.assemble(_DRAFT, recipe_build.auto_fill_pours(_DRAFT))
    assert recipe["bypass_water_enabled"] == 2


def test_assemble_carries_bypass_fields_when_enabled() -> None:
    draft = {**_DRAFT, "bypass_water_enabled": True,
             "bypass_volume_ml": 30, "bypass_temp_c": 92}
    recipe = recipe_build.assemble(draft, recipe_build.auto_fill_pours(draft))
    assert recipe["bypass_water_enabled"] == 1
    assert recipe["bypass_volume_ml"] == 30.0
    assert recipe["bypass_temp_c"] == 92.0


# --------------------------------------------------------------------------- #
# build — loose fields in, validated recipe + adjustments out.                 #
# --------------------------------------------------------------------------- #
def test_build_accepts_the_minimal_field_set() -> None:
    res = recipe_build.build(_minimal())
    assert res.ok
    assert res.errors == {}
    assert validate_recipe(res.recipe) == {}


def test_build_defaults_grind_and_rpm_from_the_spec() -> None:
    res = recipe_build.build(_minimal())
    assert res.recipe["grind_size"] == spec.field("grind_size").default
    assert res.recipe["grinder_speed_rpm"] == spec.field("grinder_speed_rpm").default


def test_build_accepts_a_numeric_ratio() -> None:
    res = recipe_build.build(_minimal(ratio=16))
    assert res.ok
    assert res.recipe["ratio"] == "1:16"


def test_build_snaps_an_off_grid_ratio_and_reports_it() -> None:
    res = recipe_build.build(_minimal(ratio="1:16.3"))
    assert res.ok
    assert res.recipe["ratio"] == "1:16.5"
    assert any("ratio" in a for a in res.adjustments)


def test_build_snaps_a_dose_above_the_cup_range_and_reports_it() -> None:
    """Omni dripper tops out at 18 g."""
    res = recipe_build.build(_minimal(dose_g=25.0, cup_type=2))
    assert res.ok
    assert res.recipe["dose_g"] == 18.0
    assert any("dose" in a for a in res.adjustments)


def test_build_snaps_grind_size_out_of_range_and_reports_it() -> None:
    res = recipe_build.build(_minimal(grind_size=95))
    assert res.ok
    assert res.recipe["grind_size"] == spec.field("grind_size").max
    assert any("grind" in a for a in res.adjustments)


def test_build_snaps_rpm_to_the_nearest_step_and_reports_it() -> None:
    res = recipe_build.build(_minimal(grinder_speed_rpm=95))
    assert res.ok
    assert res.recipe["grinder_speed_rpm"] in (90, 100)
    assert any("RPM" in a or "rpm" in a for a in res.adjustments)


def test_build_records_no_adjustments_when_every_value_is_already_valid() -> None:
    res = recipe_build.build(
        _minimal(grind_size=50, grinder_speed_rpm=90, cup_type=2)
    )
    assert res.adjustments == []


# ── temperature: the RT/BP sentinels the TypeScript copy got wrong ──────────
def test_build_accepts_a_room_temperature_pour_untouched() -> None:
    """20 °C is the app's "RT" sentinel, not an out-of-range value."""
    res = recipe_build.build(
        _minimal(pours=[{"volume_ml": 144, "temperature_c": 20},
                        {"volume_ml": 144, "temperature_c": 20}])
    )
    assert res.ok
    assert [p["temperature_c"] for p in res.recipe["pours"]] == [20.0, 20.0]
    assert res.adjustments == []


def test_build_snaps_a_temperature_above_boiling_point_and_reports_it() -> None:
    res = recipe_build.build(
        _minimal(pours=[{"volume_ml": 144, "temperature_c": 105},
                        {"volume_ml": 144}])
    )
    assert res.recipe["pours"][0]["temperature_c"] == 98.0
    assert any("temp" in a.lower() for a in res.adjustments)


# ── brewing defaults: Mansour's rules, not machine limits ───────────────────
def test_build_defaults_every_flow_rate_to_three() -> None:
    res = recipe_build.build(_minimal(pour_count=3))
    assert [p["flow_rate"] for p in res.recipe["pours"]] == [3.0, 3.0, 3.0]


def test_build_applies_the_bloom_pause_formula_to_the_first_pour() -> None:
    """max(10, round(60 - volume/3.0)) — a 60 s bloom window."""
    res = recipe_build.build(
        _minimal(pours=[{"volume_ml": 56.2}, {"volume_ml": 231.8}])
    )
    assert res.recipe["pours"][0]["pause_s"] == 41


def test_build_floors_the_bloom_pause_at_ten_seconds() -> None:
    res = recipe_build.build(
        _minimal(pours=[{"volume_ml": 200}, {"volume_ml": 88}])
    )
    assert res.recipe["pours"][0]["pause_s"] == 10


def test_build_defaults_later_pours_to_a_ten_second_pause() -> None:
    res = recipe_build.build(_minimal(pour_count=3))
    assert [p["pause_s"] for p in res.recipe["pours"][1:]] == [10, 10]


def test_build_lifts_a_short_pause_to_the_ten_second_minimum() -> None:
    res = recipe_build.build(
        _minimal(pours=[{"volume_ml": 144, "pause_s": 4},
                        {"volume_ml": 144, "pause_s": 10}])
    )
    assert res.recipe["pours"][0]["pause_s"] == 10
    assert any("pause" in a for a in res.adjustments)


def test_build_preserves_an_explicit_zero_pause() -> None:
    """0 means "no pause at all" — a legitimate choice, not a short pause."""
    res = recipe_build.build(
        _minimal(pours=[{"volume_ml": 144, "pause_s": 0},
                        {"volume_ml": 144, "pause_s": 0}])
    )
    assert [p["pause_s"] for p in res.recipe["pours"]] == [0, 0]
    assert res.adjustments == []


def test_build_caps_a_pause_above_the_machine_maximum() -> None:
    res = recipe_build.build(
        _minimal(pours=[{"volume_ml": 144, "pause_s": 120},
                        {"volume_ml": 144}])
    )
    assert res.recipe["pours"][0]["pause_s"] == spec.field("pour_pause_s").max


def test_build_without_brew_defaults_leaves_pauses_at_zero() -> None:
    res = recipe_build.build(_minimal(pour_count=2), apply_brew_defaults=False)
    assert [p["pause_s"] for p in res.recipe["pours"]] == [0, 0]


# ── volumes ────────────────────────────────────────────────────────────────
def test_build_preserves_supplied_volumes_that_already_sum_correctly() -> None:
    res = recipe_build.build(
        _minimal(pours=[{"volume_ml": 88}, {"volume_ml": 200}])
    )
    assert _vols(res.recipe["pours"]) == [88.0, 200.0]
    assert res.adjustments == []


def test_build_rescales_supplied_volumes_that_do_not_sum_and_reports_it() -> None:
    """Keep the caller's 1:3 shape, move the total onto dose x ratio."""
    res = recipe_build.build(
        _minimal(pours=[{"volume_ml": 36}, {"volume_ml": 108}])
    )
    assert sum(_vols(res.recipe["pours"])) == 288.0
    assert _vols(res.recipe["pours"]) == [72.0, 216.0]
    assert any("volume" in a for a in res.adjustments)


def test_build_derives_pour_count_from_the_supplied_pours() -> None:
    res = recipe_build.build(
        _minimal(pours=[{"volume_ml": 96}, {"volume_ml": 96}, {"volume_ml": 96}])
    )
    assert res.recipe["pour_count"] == 3


def test_build_accepts_a_pattern_by_name() -> None:
    res = recipe_build.build(
        _minimal(pours=[{"volume_ml": 144, "pattern": "circular"},
                        {"volume_ml": 144}])
    )
    assert res.recipe["pours"][0]["pattern"] == spec.PATTERN_NAME_TO_API["circular"]


def test_build_falls_back_to_spiral_for_an_unknown_pattern_and_reports_it() -> None:
    res = recipe_build.build(
        _minimal(pours=[{"volume_ml": 144, "pattern": 9},
                        {"volume_ml": 144}])
    )
    assert res.recipe["pours"][0]["pattern"] == spec.PATTERN_NAME_TO_API["spiral"]
    assert any("pattern" in a for a in res.adjustments)


# ── cup type ───────────────────────────────────────────────────────────────
def test_build_accepts_a_cup_type_by_label() -> None:
    res = recipe_build.build(_minimal(cup_type="Tea", dose_g=3.0))
    assert res.recipe["cup_type"] == spec.CUP_LABEL_TO_API["Tea"]


def test_build_falls_back_to_the_default_cup_and_reports_it() -> None:
    res = recipe_build.build(_minimal(cup_type=99))
    assert res.recipe["cup_type"] == spec.CUP_LABEL_TO_API[spec.DEFAULT_CUP_LABEL]
    assert any("cup" in a for a in res.adjustments)


def test_build_locks_an_xpod_dose_to_fifteen_grams() -> None:
    res = recipe_build.build(_minimal(cup_type=1, dose_g=20.0))
    assert res.recipe["dose_g"] == 15.0


# ── failures the builder must not paper over ───────────────────────────────
def test_build_rejects_a_missing_name() -> None:
    res = recipe_build.build({"dose_g": 18.0, "ratio": "1:16"})
    assert not res.ok
    assert "name" in res.errors


def test_build_rejects_more_pours_than_the_machine_accepts() -> None:
    res = recipe_build.build(
        _minimal(pours=[{"volume_ml": 28.8} for _ in range(12)])
    )
    assert not res.ok
    assert "pour_count" in res.errors


def test_build_reports_errors_using_the_validator_keys() -> None:
    res = recipe_build.build({"dose_g": 18.0, "ratio": "1:16"})
    assert res.errors["name"] == "name_required"


def test_build_never_mutates_the_caller_input() -> None:
    pours = [{"volume_ml": 36, "pause_s": 4}]
    fields = _minimal(pours=pours)
    recipe_build.build(fields)
    assert pours == [{"volume_ml": 36, "pause_s": 4}]
    assert fields["dose_g"] == 18.0


def test_build_rejects_a_single_pour_above_the_machine_volume_cap() -> None:
    """One pour tops out at 240 ml, so 288 ml cannot be poured in one go."""
    res = recipe_build.build(_minimal(pours=[{"volume_ml": 288}]))
    assert not res.ok
    assert res.errors["pours.0.volume_ml"] == "volume_out_of_range"
