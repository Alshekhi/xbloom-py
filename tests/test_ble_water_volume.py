"""The water a brew has poured, RD_WATER_VOLUME (40523), and the reserve.

The machine reports the whole brew's poured water as a float in millilitres
times 1000: a measured 500 ml recipe ended at 500000.0 (V12.0D.500).
"""
from __future__ import annotations

import struct

from xbloom import ble, spec


def _volume_frame(raw: float) -> bytes:
    body = b"\x58\x02\x07" + struct.pack("<HI", ble.NOTIFY_WATER_VOLUME, 16) + b"\xc1"
    body += struct.pack("<f", raw)
    return body + struct.pack("<H", ble._crc16(body))


def test_dispensed_water_is_reported_in_millilitres():
    assert ble.decode_notification(_volume_frame(500000.0))["water_ml"] == 500.0


def test_partial_dispense_keeps_one_decimal():
    assert ble.decode_notification(_volume_frame(394862.5))["water_ml"] == 394.9


def test_the_water_reserve_is_270_ml():
    assert spec.WATER_RESERVE_ML == 270
