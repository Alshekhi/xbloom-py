"""Commands over a held session, and a session that notices it lost its link.

The machine takes one connection at a time. A host holding a session that
opens a second link for a one-off command tears the session down — so the
command has to travel over the session instead, and still be confirmed: a pour
the machine refused must not read as sent. And a session whose link is gone
must end itself rather than look alive until its idle timer runs out.
"""
from __future__ import annotations

import asyncio
import struct
from unittest.mock import patch

import pytest

from xbloom import ble, mode_listener


def _reply(code: int, error: int | None = None) -> bytes:
    """The machine's answer to `code`: a plain echo, or a refusal carrying
    `error` in payload bytes 12-14."""
    payload = b"" if error is None else bytes(12) + error.to_bytes(3, "big") + b"\x01"
    return (
        bytes([0x58, 0x02, 0x07]) + struct.pack("<H", code)
        + struct.pack("<I", 12 + len(payload)) + b"\xc1" + payload + b"\x00\x00"
    )


class FakeLink:
    """A bleak client: records writes, answers the ones it is told to."""

    def __init__(self):
        self.is_connected = True
        self.writes: list[int] = []
        self.answers: dict[int, int | None] = {}   # code -> error (None = accept)
        self.callback = None
        self.fail_writes = False

    async def start_notify(self, _uuid, callback):
        self.callback = callback

    async def write_gatt_char(self, _uuid, frame, response=False):
        if self.fail_writes:
            raise RuntimeError("Service Discovery has not been performed yet")
        code = ble.frame_command_code(frame)
        self.writes.append(code)
        if code in self.answers:
            asyncio.get_running_loop().call_soon(
                self.callback, None, _reply(code, self.answers[code]),
            )


def _client_class(link: FakeLink):
    class _Client(ble.XBloomBleClient):
        async def __aenter__(self):
            self._client = link
            self._loop = asyncio.get_running_loop()
            return self

        async def __aexit__(self, *_exc):
            return False

    return _Client


async def _held_session(link: FakeLink, phases: list):
    async def _device():
        return object()

    async def _ignore(_event):
        return None

    listener = mode_listener.XBloomModeListener(
        ble_device_resolver=_device,
        mode_name="connect",
        notification_filter=lambda _decoded: None,
        on_event=_ignore,
        on_lifecycle=lambda phase, data: phases.append((phase, data)),
    )
    await listener.start()
    for _ in range(200):
        if any(p == "ready" for p, _ in phases):
            return listener
        await asyncio.sleep(0.01)
    raise AssertionError(f"session never became ready: {phases}")


def _run(test):
    async def go():
        link, phases = FakeLink(), []
        with patch.object(ble, "XBloomBleClient", _client_class(link)), \
             patch.object(mode_listener, "HOLD_TICK_S", 0.01), \
             patch.object(mode_listener, "INITIAL_STATE_TIMEOUT_SEC", 0.05):
            listener = await _held_session(link, phases)
            try:
                await test(listener, link, phases)
            finally:
                await listener.stop()
    asyncio.run(go())


def test_a_command_over_the_session_waits_for_its_answer():
    async def test(listener, link, _phases):
        link.answers[4506] = None
        frame = ble.build_brewer_standalone_frame(3.0, 30.0, 93.0, 0, 2)
        assert await listener.send_confirmed("brew_standalone", frame) is True
    _run(test)


def test_a_refusal_over_the_session_is_raised():
    async def test(listener, link, _phases):
        link.answers[4506] = 0x000040   # water shortage
        frame = ble.build_brewer_standalone_frame(3.0, 30.0, 93.0, 0, 2)
        with pytest.raises(ble.CommandRefused) as err:
            await listener.send_confirmed("brew_standalone", frame)
        assert err.value.reason == "no_water"
    _run(test)


def test_an_unanswered_command_is_not_re_sent_while_awake():
    # A re-send could repeat a pour the machine did start.
    async def test(listener, link, _phases):
        frame = ble.build_brewer_standalone_frame(3.0, 30.0, 93.0, 0, 2)
        with patch.object(ble, "ECHO_TIMEOUT_S", 0.02):
            assert await listener.send_confirmed("brew_standalone", frame) is False
        assert link.writes.count(4506) == 1
    _run(test)


async def _ended_with(phases, reason):
    for _ in range(200):
        if ("failed", {"reason": reason}) in phases:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"session did not end with {reason}: {phases}")


def test_a_session_whose_link_drops_ends_itself():
    async def test(listener, link, phases):
        link.is_connected = False
        await _ended_with(phases, "connection_lost")
        assert not listener.is_running
    _run(test)


def test_a_session_that_can_no_longer_write_ends_itself():
    # The link can still claim to be connected after another connection has
    # taken the machine; the first failed write is what shows it.
    async def test(listener, link, phases):
        link.fail_writes = True
        assert await listener.send_live(ble._build_frame(ble.CMD_TARE)) is False
        await _ended_with(phases, "connection_lost")
    _run(test)
