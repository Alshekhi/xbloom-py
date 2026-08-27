# xbloom-py

Async Python library for [xBloom Studio](https://xbloom.com) coffee brewers:
the BLE protocol, recipe validation, over-the-air firmware updates, and the
optional cloud account API.

Unofficial, and not affiliated with or endorsed by xBloom. See
[Disclaimer](#disclaimer).

## Install

```bash
pip install xbloom-py            # pure-python core: spec, recipes, validation
pip install "xbloom-py[ble]"     # + local Bluetooth control
pip install "xbloom-py[cloud]"   # + cloud account, recipe sync, firmware check
pip install "xbloom-py[all]"     # everything
```

Import as `xbloom`:

```python
from xbloom import spec, recipe_validate
```

Dependencies are declared with lower bounds only and no upper pins, so the
package drops into an environment that already pins these without fighting it.

## What is in it

| Module | Needs | What it does |
|---|---|---|
| `spec` | — | Machine constants: ranges, enums, pattern and unit maps. The single source of truth. |
| `recipe_validate` | — | Validate and normalise recipe dictionaries. |
| `brew_scale` | — | Scale a recipe's dose and water. |
| `models` | — | Recipe and reading dataclasses. |
| `exceptions` | — | `XBloomError`, `XBloomAPIError`. |
| `ble` | `[ble]` at runtime | Frame encoding/decoding, ACK-gated send/confirm, packet builders. |
| `ota` | `[ble]` at runtime | Validated, arm-gated firmware flashing. **Read [Firmware updates](#firmware-updates) first.** |
| `mode_listener` | `[ble]` at runtime | Live knob and scale event stream. |
| `client` | `[cloud]` | Share-link recipe fetching. |
| `cloud` | `[cloud]` | Account login, recipe CRUD, firmware version check. |

`ble`, `ota` and `mode_listener` import their Bluetooth dependencies lazily, so
they can be imported for packet construction with no extras installed.

## Status

`0.x` — the API is settling. `1.0.0` follows once a second consumer has proven
the module boundaries.

## Development

```bash
uv sync --all-extras
uv run pytest
```

The suite runs without extras too; `test_cloud.py` is skipped when `aiohttp`
and `cryptography` are absent.

## Firmware updates

**Read this before you use `ota`.** Firmware flashing is the one thing in this
library that can permanently damage your machine. Use it only if you accept
that.

`ota` verifies the update's MD5 before anything is sent, and every block is
acknowledged by the machine as it is written. That makes a bad flash unlikely —
it does not make it impossible. **Bluetooth is a wireless link, and a wireless
link can drop.** If it drops in the middle of a firmware write, the machine can
be left unbootable, with no way to recover it over BLE.

If you choose to use it:

- Keep the machine powered and close to the Bluetooth adapter for the whole flash.
- Never start a flash during a brew.
- Don't kill the process, or let the host sleep, while one is running.

**You do this entirely at your own risk.** This is unofficial software talking
to an undocumented protocol that was worked out by inspection, and it is not
endorsed by or connected to xBloom in any way. The authors and contributors
accept **no responsibility and no liability** for any damage to your machine,
loss of warranty, or any other loss arising from using this library — the
firmware updater above all. If that isn't a risk you want to take, don't import
`ota`; everything else works without it.

## Disclaimer

This is an independent, community project. It is **not affiliated with,
authorized, or endorsed by xBloom**. "xBloom" is used only to say which machine
this talks to. It communicates with the machine over its local BLE protocol,
worked out for interoperability, which may change at any time with a firmware
update and break this library without warning.

The software is provided **as is, without warranty of any kind**, express or
implied. You use it at your own risk, and the authors and contributors are not
liable for any damage, loss, or injury resulting from its use. See the
[Firmware updates](#firmware-updates) section for the risk that matters most.

## License

MIT
