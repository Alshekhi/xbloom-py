"""Test configuration.

Only `client.py` and `cloud.py` import third-party modules at module scope
(`aiohttp`, plus `cryptography` in `cloud.py`). `ble.py` and `ota.py` defer
their `bleak` imports into the call sites that need them, so every other suite
runs on a bare install with no extras.

`test_cloud.py` exercises real RSA/PKCS#1 v1.5 block sizing. Skip it when its
dependencies are genuinely absent rather than stubbing them — a stubbed crypto
test passes vacuously, which is worse than not running it.

Run the whole suite with `uv sync --all-extras`.
"""
from __future__ import annotations

import importlib.util

_MISSING = [
    name
    for name in ("aiohttp", "cryptography")
    if importlib.util.find_spec(name) is None
]

collect_ignore = ["test_cloud.py"] if _MISSING else []
