"""The frames a recipe brew sends when it is paused and resumed.

Both fixtures are real notifications captured mid-brew, right after the
machine echoed a pause (40518) and a resume (40524).
"""
from __future__ import annotations

from xbloom import ble

PAUSED = bytes.fromhex("580207439e10000000c13bdf0f40b406")
RESUMED = bytes.fromhex("580207449e0c000000c1819b")


def test_a_paused_brew_is_reported():
    assert ble.decode_notification(PAUSED)["cmd"] == ble.NOTIFY_BREW_PAUSED == 40515


def test_a_resumed_brew_is_reported():
    assert ble.decode_notification(RESUMED)["cmd"] == ble.NOTIFY_BREW_RESUMED == 40516
