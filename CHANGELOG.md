# Changelog

## 0.3.1 — 2026-09-20

Refusals are read by the bit they set, and two of them were misread.

- A reply's error field is matched **bit by bit** (`spec.refusal_for`), not as
  an exact value. The firmware ORs conditions into one field, so a pair such as
  `0x400040` matched nothing and was read as an acceptance — a flaw both
  official apps share.
- `0x100000` is the firmware's post-power-loss gate, `not_ready`: it runs
  before any command but the handshake and refuses everything until the
  machine's restore latch is consumed on its standby screen. It had been one of
  the "busy" codes, and a busy refusal answering a re-send counts as
  acceptance, so three brews were reported as started while the machine ground
  nothing (measured 2026-09-20; the code appears nowhere else in fifteen days
  of logs). Only the codes in `spec.RESEND_MEANS_TAKEN` are read that way now.
- `0x200000` is that gate's second latch, `restore_incomplete`, not a busy
  code. It stays tolerated on a re-send: a brew answered with it went on to
  grind, pour and finish, so its first copy had been taken.
- `0x001000` is the refusal the back-to-home handler sends off the home screen.
  Neither app lists it, so it too read as an acceptance.
- Which refusals may be read as "the first send was taken" is decided **by
  code** now (`spec.taken_on_resend`), not by reason. One reason covers nine
  codes and only `0x800000` is confirmed to be the busy one; another of the
  nine is the power-loss gate refusing on a different screen. An unproven code
  read as acceptance is the whole shape of the bug above.

## 0.3.0 — 2026-09-19

Fixes lost frames, and brews that went ahead after the machine refused a step.

**Changed behaviour:** `brew()` and `write_confirmed()` now raise
`CommandRefused` when the machine refuses a step, and `brew()` raises
`CommandUnanswered` when a step gets no reply. Both used to carry on. Code that
calls them should catch these and report the brew as not started.

- Under load one FFE2 notification can carry a weight reading, a water reading,
  a command echo and a brew event back to back. Only the first frame was
  decoded, so `RD_ENJOY`, the grinder starting, pours and command echoes behind
  it were dropped: a finished brew could time out, and the heater frame could
  be read as the pours beginning while the grinder was still running.
- `split_notification()` walks the frames by the length each one declares, and
  both notify handlers now handle every frame in order. A trailing frame cut
  short at the notification's size limit is dropped.
- A refused command is answered with its own code, just like an accepted one;
  the refusal is an error code in the reply. It was never read, so any reply
  counted as acceptance, and a step with no reply at all was passed over — so
  `execute` could follow a recipe the machine had refused and grind at a stale
  size. `write_confirmed` now raises `CommandRefused` for the codes the official
  app treats as refusals (`spec.REPLY_REFUSALS`), and `brew()` raises
  `CommandUnanswered` for a step that gets no reply, or when replies cannot be
  read at all, rather than falling back to fixed delays. `execute` is only sent
  once the recipe is accepted.
- `read_status_snapshot()` sends its wake-up handshake confirmed and re-sent,
  like any command. A machine asleep can miss the first frame, and the single
  unconfirmed nudge then left a status refresh with nothing to read.
- A client given a Bluetooth device without a name — one a host found by
  address — names it by its address in the logs, not `<BLEDevice>`.
- `spec.FIELDS["brewer_volume_ml"]` is the standalone brewer's range, 30-500 ml,
  from the official app's brewer screen. `build_brewer_standalone_frame` refuses
  a volume outside it: the pour stops when the flow meter reaches the target,
  so a target of zero gives it nothing to stop at.
- A mode-listener session can carry discrete commands: `send_confirmed()` waits
  for the machine's answer and raises `CommandRefused` like a one-shot command,
  so a host holding a session no longer has to open a second link — which tore
  the session down. A session whose link drops, or whose write fails, now ends
  itself as a failure with reason `connection_lost` instead of looking alive
  until its idle timer.

## 0.2.0 — 2026-08-30

Adds `recipe_build`, the layer that turns loose recipe fields into a recipe the
machine will accept.

- `build()` takes whatever a caller has — a recipe read off a web page, or one
  described out loud — and snaps every field onto the grid `spec` defines
  rather than rejecting it, returning the adapted recipe alongside a
  plain-language list of what it changed and the validator's verdict.
- `auto_fill_pours`, `redistribute_pours` and `assemble` are the pieces a
  form-driven recipe editor needs. They previously lived as private methods on
  the Home Assistant integration's options flow, where nothing else could reach
  them — which is why a second, drifting copy of the rules had grown in a
  downstream consumer.
- Machine limits and brewing preferences stay separate. `spec` says a pour may
  pause 0-59 seconds and the validator enforces exactly that; the ten-second
  pause floor, the sixty-second bloom window and the 3.0 ml/s default flow are
  preferences that shape `build`'s defaults only, and `apply_brew_defaults=False`
  turns them off.

## 0.1.3 — 2026-08-27

Documentation only; identical to `0.1.2` as software. A release exists because a
project description on PyPI is fixed at upload and can only be changed by
publishing again.

## 0.1.2 — 2026-08-27

First release.

- BLE protocol: frame encode/decode, ACK-gated send/confirm, packet builders,
  recipe blob encoding
- `spec`: machine constants centralised as the single source of truth, with a
  parity test guarding the values against their pre-refactor snapshot
- Recipe validation, normalisation and scaling
- Arm-gated OTA firmware flashing — see the firmware warning in the README
- Optional cloud account: login, recipe CRUD, firmware version check
- BLE and cloud dependencies are extras, so the package installs alongside Home
  Assistant without disturbing its pinned versions
