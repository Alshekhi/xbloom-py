"""The low-water switch report, RD_ErrorLackOfWater (40522).

The machine sends it on every change of its low-water switch, in both
directions, and once on connect. Its first payload byte is the switch:
1 while there is water, 0 once it runs low. Both fixtures are real
notifications from one recipe brew on V12.0D.500.
"""
from __future__ import annotations

from xbloom import ble

WATER_OK = bytes.fromhex("5802074a9e10000000c101000000d77b")
WATER_LOW = bytes.fromhex("5802074a9e10000000c1000000006c67")


def test_water_ok_is_reported_as_enough_water():
    decoded = ble.decode_notification(WATER_OK)
    assert decoded["cmd"] == ble.NOTIFY_LACK_OF_WATER == 40522
    assert decoded["water_enough"] == 1


def test_water_low_is_reported_as_not_enough_water():
    decoded = ble.decode_notification(WATER_LOW)
    assert decoded["cmd"] == ble.NOTIFY_LACK_OF_WATER
    assert decoded["water_enough"] == 0
