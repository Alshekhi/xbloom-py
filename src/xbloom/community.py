"""XBloomCommunityClient — read-only client for xBloom's community recipe hub.

The hub is the recipe library behind ``collective.xbloom.com`` and the xBloom
app's community section (the site recognises ``?device=xbloomApp`` and hands a
chosen recipe back to the app by its ``tableId``). It is served by its own
backend, ``collective-api.xbloom.com``, which shares nothing with the account
API in ``cloud.py``: a different login, a different RSA key, a ``Token``
header instead of credentials inside an encrypted body.

Everything here works **without signing in** — confirmed against the live
service 2026-11-07:

  * ``communityRecipe/recipe/criteria`` — the filter vocabulary as
    ``{name, value}`` pairs (origins, varietals, processes, roasts, flavors,
    machines, cup types, coffee types).
  * ``communityRecipe/index/page`` — the paged search.
  * ``communityRecipe/recipe/detail`` with ``type: 1`` — one recipe with its
    pours. ``type: 2`` answers "This requires you to log in first".

Likes, saves and a member's own shared recipes need the hub's login and are
not covered.

To brew a hub recipe, take its ``share_url`` to :class:`xbloom.client.XBloomClient`:
the hub's pours carry no flow rate or agitation, and the share link resolves
to the complete recipe the app itself would load.

Request shapes, header names and the filter encodings come from the hub's own
web bundle (``index-BVUEadnx.js``) and were each exercised live.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterable

from .exceptions import XBloomAPIError
from .models import CommunityPage, CommunityPour, CommunityRecipe, CommunityRecipeDetail

if TYPE_CHECKING:  # the session is only used, never constructed, here
    import aiohttp

API_BASE = "https://collective-api.xbloom.com"

# The hub's web client sends LanguageType 3 for Chinese, 7 for Arabic and 0
# for everything else, and nothing more. Arabic (7) returns the criteria
# names in Arabic; recipe names and notes stay as their authors wrote them.
_LANGUAGE_TYPES = {"zh": 3, "ar": 7}

# The hub answers with this in ``code`` on success, inside an HTTP 200.
_OK = 200

# ``sort`` in the search body: 1 by upload date, 2 by likes. The web client
# also sends 3 for its third menu entry; it is not exposed here.
SORTS = {"date": 1, "likes": 2}
# ``recipeType``: what is being brewed.
KINDS = {"coffee": 1, "tea": 2}
# ``recipeUserType``: who shared it.
SOURCES = {"official": 1, "community": 2}

# Search filter → (criteria list it is resolved against, body field).
# Machines are sent as their codes (``"J15"``); every other list as numbers,
# which is how the web client encodes them.
_FILTERS = {
    "origins": ("originList", "originIds"),
    "varietals": ("varietalList", "varietalIds"),
    "processes": ("processingList", "processIds"),
    "roasts": ("roastList", "roastList"),
    "flavors": ("flavorList", "flavorIds"),
    "cup_types": ("cupTypeList", "cupTypeList"),
}

# The page size the web client asks for. The service honours far larger ones.
DEFAULT_PAGE_SIZE = 20


def _language_type(code: str | None) -> int:
    primary = (code or "").strip().lower().replace("_", "-").split("-", 1)[0]
    return _LANGUAGE_TYPES.get(primary, 0)


def _strings(raw: Any) -> list[str]:
    return [str(x) for x in raw] if isinstance(raw, list) else []


def _number(raw: Any) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


class XBloomCommunityClient:
    """Search and read recipes on the community hub. No credentials."""

    def __init__(self, session: aiohttp.ClientSession, *, language: str | None = None) -> None:
        self._session = session
        self._headers = {
            "Content-Type": "application/json;charset=utf-8",
            "LanguageType": str(_language_type(language)),
        }
        self._criteria: dict[str, list[dict[str, str]]] | None = None

    async def _post(self, endpoint: str, body: dict[str, Any]) -> Any:
        async with self._session.post(
            f"{API_BASE}/{endpoint}", json=body, headers=self._headers,
        ) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)
        if not isinstance(data, dict):
            raise XBloomAPIError(f"community hub returned {data!r}")
        if data.get("code") != _OK:
            raise XBloomAPIError(f"community hub: {data.get('msg') or data.get('code')}")
        return data.get("data")

    # -- vocabulary ---------------------------------------------------------- #
    async def criteria(self) -> dict[str, list[dict[str, str]]]:
        """The hub's filter vocabulary, ``{list_name: [{name, value}, ...]}``.

        Fetched once per client: the names come back in the client's language,
        the values are the same in every language.
        """
        if self._criteria is None:
            raw = await self._post("communityRecipe/recipe/criteria", {})
            if not isinstance(raw, dict):
                raise XBloomAPIError("community hub criteria missing")
            self._criteria = {
                key: [
                    {"name": str(item.get("name", "")), "value": str(item.get("value", ""))}
                    for item in items if isinstance(item, dict)
                ]
                for key, items in raw.items() if isinstance(items, list)
            }
        return self._criteria

    async def _resolve(self, list_name: str, names: Iterable[str]) -> list[str]:
        """Names → the hub's values, case-insensitively. Unknown names raise."""
        options = (await self.criteria()).get(list_name, [])
        by_name = {o["name"].casefold(): o["value"] for o in options}
        values, unknown = [], []
        for name in names:
            value = by_name.get(str(name).strip().casefold())
            if value is None:
                unknown.append(str(name))
            else:
                values.append(value)
        if unknown:
            known = ", ".join(o["name"] for o in options)
            raise ValueError(f"not on the hub: {', '.join(unknown)}. It knows: {known}")
        return values

    async def _name_of(self, list_name: str, value: Any) -> str | None:
        for option in (await self.criteria()).get(list_name, []):
            if option["value"] == str(value):
                return option["name"]
        return None

    # -- search -------------------------------------------------------------- #
    async def search(
        self,
        keyword: str | None = None,
        *,
        machine: str | None = None,
        kind: str | None = None,
        source: str | None = None,
        origins: Iterable[str] = (),
        varietals: Iterable[str] = (),
        processes: Iterable[str] = (),
        roasts: Iterable[str] = (),
        flavors: Iterable[str] = (),
        cup_types: Iterable[str] = (),
        sort: str = "date",
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> CommunityPage:
        """One page of hub recipes, newest (or most liked) first.

        Every filter takes the names :meth:`criteria` lists — ``machine="Studio"``,
        ``origins=["Ethiopia"]`` — in the client's language. ``kind`` is one of
        :data:`KINDS`, ``source`` one of :data:`SOURCES`, ``sort`` one of
        :data:`SORTS`.
        """
        for label, value, allowed in (
            ("kind", kind, KINDS), ("source", source, SOURCES), ("sort", sort, SORTS),
        ):
            if value is not None and value not in allowed:
                raise ValueError(f"{label} must be one of {', '.join(allowed)}")
        if page < 1 or page_size < 1:
            raise ValueError("page and page_size start at 1")

        body: dict[str, Any] = {
            "pageIndex": page,
            "pageSize": page_size,
            "keyword": (keyword or "").strip() or None,
            "recipeType": KINDS.get(kind) if kind else None,
            "recipeUserType": SOURCES.get(source) if source else None,
            "sort": SORTS[sort],
            "sortType": 2,  # descending; ascending (1) is the web client's other choice
        }
        if machine:
            body["machineList"] = await self._resolve("machineList", [machine])
        for arg, names in (
            ("origins", origins), ("varietals", varietals), ("processes", processes),
            ("roasts", roasts), ("flavors", flavors), ("cup_types", cup_types),
        ):
            names = [n for n in names if str(n).strip()]
            if names:
                list_name, field = _FILTERS[arg]
                body[field] = [int(v) for v in await self._resolve(list_name, names)]

        raw = await self._post("communityRecipe/index/page", body)
        if not isinstance(raw, dict):
            raise XBloomAPIError("community hub search returned no page")
        return {
            "page": int(raw.get("pageIndex") or page),
            "total_pages": int(raw.get("totalPage") or 0),
            "total": int(raw.get("total") or 0),
            "recipes": [await self._parse(r) for r in raw.get("list") or [] if isinstance(r, dict)],
        }

    async def detail(self, recipe_id: int | str) -> CommunityRecipeDetail:
        """One hub recipe with its description and pours, by its hub id."""
        raw = await self._post(
            "communityRecipe/recipe/detail", {"id": int(recipe_id), "type": 1},
        )
        if not isinstance(raw, dict):
            raise XBloomAPIError(f"community hub has no recipe {recipe_id}")
        recipe: CommunityRecipeDetail = {
            **await self._parse(raw),
            "description": str(raw.get("introduce") or ""),
            "uploaded_on": str(raw.get("uploadDate") or ""),
            "pours": [self._parse_pour(p) for p in raw.get("pourList") or [] if isinstance(p, dict)],
        }
        return recipe

    # -- parsing ------------------------------------------------------------- #
    async def _parse(self, r: dict[str, Any]) -> CommunityRecipe:
        roast = r.get("roast")
        return {
            "id": int(r["communityRecipeId"]),
            "name": str(r.get("recipeName") or "").strip(),
            "author": str(r.get("userName") or "").strip(),
            "official": r.get("official") == 1,
            "machine": str(r.get("model") or ""),
            "cup_type": int(r.get("cupTypeInt") or 0),
            "coffee_type": str(r.get("type") or ""),
            "origin": _strings(r.get("origin")),
            "varietal": _strings(r.get("varietal")),
            "process": _strings(r.get("process")),
            "flavor": _strings(r.get("flavor")),
            # 0 is "not given"; any other value is a roastList entry.
            "roast": await self._name_of("roastList", roast) if roast else None,
            "dose_g": _number(r.get("dose")),
            "water_ratio": _number(r.get("grandWater")),  # ratio denominator, as in share links
            "grinder_size": _number(r.get("grinderSize")),
            "rpm": int(r.get("rpm") or 0),
            # The detail answer carries no pourCount, only the pours.
            "pour_count": int(r.get("pourCount") or len(r.get("pourList") or [])),
            "cup_volume": str(r.get("volume") or ""),  # free text: "225", "~600"
            "likes": int(r.get("likesCount") or 0),
            "image_url": str(r.get("imageUrl") or ""),
            "share_url": str(r.get("shareRecipeLink") or ""),
        }

    @staticmethod
    def _parse_pour(p: dict[str, Any]) -> CommunityPour:
        return {
            "name": str(p.get("theName") or ""),
            "volume_ml": float(p.get("volume") or 0),
            "temperature_c": float(p.get("temperature") or 0),
            "pattern": int(p.get("pattern") or 0),  # api id, as in spec.PATTERN_API_TO_NAME
            "pause_s": int(p.get("pausing") or 0),
        }
