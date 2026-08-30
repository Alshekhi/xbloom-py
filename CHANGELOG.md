# Changelog

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
