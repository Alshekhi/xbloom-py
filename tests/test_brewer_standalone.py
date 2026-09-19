"""The standalone brewer pours until its flow meter reaches the target volume.

A target of zero leaves the pour with no volume to stop at, so the frame
builder refuses anything outside the range the official app's brewer screen
offers (BrewerActivity's volume slider, 30-500 ml).
"""
from __future__ import annotations

import pytest

from xbloom import ble, spec


def _frame(volume_ml: float) -> bytes:
    return ble.build_brewer_standalone_frame(3.0, volume_ml, 93.0, 0, 2)


def test_the_brewer_range_is_the_apps():
    r = spec.FIELDS["brewer_volume_ml"]
    assert (r.min, r.max, r.step) == (30, 500, 1)


@pytest.mark.parametrize("volume_ml", [0, 29, 501])
def test_a_volume_outside_the_range_is_refused(volume_ml):
    with pytest.raises(ValueError):
        _frame(volume_ml)


@pytest.mark.parametrize("volume_ml", [30, 120, 500])
def test_a_volume_inside_the_range_builds(volume_ml):
    assert ble.frame_command_code(_frame(volume_ml)) == ble.CMD_BREWER_START
