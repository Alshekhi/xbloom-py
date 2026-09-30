"""The machine packs several frames into one FFE2 notification.

Under load the link coalesces frames: a single notification can carry a weight
reading, a water reading, a command echo and a brew event back to back. Each
frame declares its own total length (bytes 5-8, LE), so they can be walked.
Decoding only the first frame silently dropped everything behind it — RD_ENJOY,
the grinder starting, pours and command echoes all went missing that way.

The two fixtures below are real notifications captured from a machine.
"""
from __future__ import annotations

import asyncio

from xbloom import ble

# Weight / water readings with RD_ENJOY (40512) in third position.
PACKED_ENJOY = bytes.fromhex(
    "5802074b9e10000000c1007c924827f3"
    "580207155010000000c17b347743da07"
    "580207409e0c000000c1f7f4"
    "580207155010000000c17b347743da07"
    "5802074b9e10000000c1007c924827f3"
    "580207155010000000c17b347743da07"
    "5802074b9e10000000c1007c924827f3"
    "580207155010000000c17b347743da07"
    "5802074b9e10000000c1007c924827f3"
)

# The execute echo (8002), the grinder starting (40502) and gear reports,
# ending partway through a weight frame — the notification's size limit cut it.
PACKED_GRIND_START_TRUNCATED = bytes.fromhex(
    "5802074b9e10000000c100000000fd32"
    "580207155010000000c10000000016b5"
    "580207421f0c000000c1c5c2"
    "580207369e0c000000c176bd"
    "5802074b9e10000000c100000000fd32"
    "580207155010000000c10000000016b5"
    "580207399e10000000c1570000002245"
    "5802074b9e10000000c100000000fd32"
    "580207155010000000c10000000016b5"
    "580207399e10000000c1560000009959"
    "580207571f10000000c11e0000007542"
    "5802074b9e10000000c100000000fd32"
    "580207155010000000c10000000016b5"
    "580207399e10000000c155000000547c"
    "5802074b9e10000000c100000000fd32"
    "580207155010000000c10000"
)


def _codes(frames: list[bytes]) -> list[int]:
    return [ble.frame_command_code(f) for f in frames]


def test_split_walks_every_frame_in_a_packed_notification():
    frames = ble.split_notification(PACKED_ENJOY)
    assert _codes(frames) == [
        40523, 20501, 40512, 20501, 40523, 20501, 40523, 20501, 40523,
    ]
    assert b"".join(frames) == PACKED_ENJOY


def test_split_drops_only_an_incomplete_trailing_frame():
    frames = ble.split_notification(PACKED_GRIND_START_TRUNCATED)
    assert _codes(frames) == [
        40523, 20501, 8002, 40502, 40523, 20501, 40505,
        40523, 20501, 40505, 8023, 40523, 20501, 40505, 40523,
    ]


def test_split_leaves_a_single_frame_alone():
    frame = PACKED_ENJOY[:16]
    assert ble.split_notification(frame) == [frame]


def test_split_keeps_a_lone_frame_whose_length_cannot_be_walked():
    # A frame whose length field does not describe it is still decoded as one
    # frame, exactly as before splitting existed.
    frame = bytes.fromhex("580207429e0000000000c10000")
    assert ble.split_notification(frame) == [frame]


def _client_on_running_loop(events: list[dict]) -> ble.XBloomBleClient:
    async def on_event(decoded: dict) -> None:
        events.append(decoded)

    c = ble.XBloomBleClient("XBLOOM TEST", on_event=on_event)
    c._loop = asyncio.get_running_loop()
    c._notify_active = True
    return c


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


def test_enjoy_behind_other_frames_completes_the_brew():
    async def go():
        c = _client_on_running_loop([])
        c._on_notify(None, PACKED_ENJOY)
        assert await c.wait_for_completion(timeout=0.1) is True
    asyncio.run(go())


def test_every_packed_frame_reaches_the_host_in_order():
    async def go():
        events: list[dict] = []
        c = _client_on_running_loop(events)
        c._on_notify(None, PACKED_GRIND_START_TRUNCATED)
        await _settle()
        cmds = [e["cmd"] for e in events]
        assert cmds[:4] == [40523, 20501, 8002, 40502]
        assert cmds.count(40505) == 3
    asyncio.run(go())


def test_an_echo_behind_other_frames_releases_its_waiter():
    async def go():
        c = _client_on_running_loop([])
        waiter = ble._Reply()
        c._echo_waiters[8002] = waiter
        c._on_notify(None, PACKED_GRIND_START_TRUNCATED)
        await asyncio.wait_for(waiter.event.wait(), timeout=0.1)
        assert waiter.refusal is None
    asyncio.run(go())


def test_a_device_found_by_address_is_logged_by_its_address():
    # A host that finds the machine by address before its name is known hands
    # over a BLEDevice with no name; "<BLEDevice>" said nothing about which.
    from types import SimpleNamespace

    from xbloom import ble

    device = SimpleNamespace(name=None, address="AA:BB:CC:00:00:01")
    assert ble.XBloomBleClient(device)._name == "AA:BB:CC:00:00:01"


# Seen live 2026-09-30: a notification ending with the first four bytes of a
# weight frame, and the next beginning with the rest of it.
WEIGHT = bytes.fromhex("580207155010000000c10000000016b5")
WATER = bytes.fromhex("5802074b9e10000000c100000000fd32")


def test_a_frame_split_between_two_notifications_is_joined():
    frames = ble.NotificationAssembler()
    assert _codes(frames.feed(WATER + WEIGHT[:4])) == [40523]
    assert frames.feed(WEIGHT[4:] + WATER) == [WEIGHT, WATER]


def test_the_split_can_fall_anywhere_in_the_frame():
    for cut in range(1, len(WEIGHT)):
        frames = ble.NotificationAssembler()
        assert frames.feed(WATER + WEIGHT[:cut]) == [WATER]
        assert frames.feed(WEIGHT[cut:]) == [WEIGHT], cut


def test_a_frame_longer_than_two_notifications_is_joined():
    frames = ble.NotificationAssembler()
    assert frames.feed(WEIGHT[:3]) == []
    assert frames.feed(WEIGHT[3:9]) == []
    assert frames.feed(WEIGHT[9:]) == [WEIGHT]


def test_the_truncated_capture_is_completed_by_the_next_notification():
    frames = ble.NotificationAssembler()
    assert len(frames.feed(PACKED_GRIND_START_TRUNCATED)) == 15
    assert frames.feed(bytes.fromhex("000016b5")) == [WEIGHT]


def test_a_start_that_is_never_completed_does_not_spoil_what_follows():
    # The checksum decides: bytes that do not join into a valid frame are
    # dropped, and the next notification is read on its own.
    frames = ble.NotificationAssembler()
    frames.feed(WATER + WEIGHT[:4])
    assert frames.feed(WATER) == [WATER]


def test_a_new_link_starts_on_a_fresh_frame():
    frames = ble.NotificationAssembler()
    frames.feed(WATER + WEIGHT[:4])
    frames.reset()
    assert frames.feed(WEIGHT[4:]) == [WEIGHT[4:]]


def test_a_lone_frame_that_cannot_be_walked_is_still_decoded_whole():
    frame = bytes.fromhex("580207429e0000000000c10000")
    assert ble.NotificationAssembler().feed(frame) == [frame]
