# Changelog

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
