"""Unit tests for the community hub client (xbloom/community.py).

No network: a fake session records each request and answers from a table, so
the request bodies are asserted exactly as the hub's web client sends them.
The module imports no third-party package, so this runs on a bare install.
"""
from __future__ import annotations

import pytest

from xbloom.community import API_BASE, XBloomCommunityClient
from xbloom.exceptions import XBloomAPIError

CRITERIA = {
    "originList": [{"name": "Kenya", "value": "9"}, {"name": "Peru", "value": "15"}],
    "processingList": [{"name": "Washed", "value": "87"}],
    "roastList": [{"name": "Light Roast", "value": "1"}, {"name": "Dark Roast", "value": "5"}],
    "flavorList": [{"name": "Plum", "value": "60"}],
    "varietalList": [],
    "machineList": [{"name": "Studio", "value": "J15"}, {"name": "Original", "value": "J20"}],
    "cupTypeList": [{"name": "Omni", "value": "2"}],
}

LISTED = {
    "communityRecipeId": 4021, "recipeId": 77001, "cupType": "Omni", "cupTypeInt": 2,
    "model": "Studio", "official": 2, "type": "Single Origin",
    "imageUrl": "https://example.invalid/a.jpg", "flavor": ["Plum"], "origin": ["Kenya"],
    "varietal": [], "process": ["Washed"], "recipeName": "Test Kenya Hot",
    "userName": "Test Author", "userAvatar": None, "roast": 1, "dose": 16.0,
    "grinderSize": 52.0, "rpm": 90, "pourCount": 2, "grandWater": 15.0, "volume": "240",
    "likesCount": 12, "isLike": False, "isCollect": False,
    "shareRecipeLink": "https://share-h5.xbloom.com/?id=abc%3D%3D",
}

DETAIL = {
    **LISTED,
    "introduce": "Bright and clean.",
    "uploadDate": "2026-10-01",
    "pourList": [
        {"theName": "Bloom", "volume": 40.0, "temperature": 92.0, "pausing": 30, "pattern": 2},
        {"theName": "Pour1", "volume": 200.0, "temperature": 91.0, "pausing": 0, "pattern": 3},
    ],
}


def ok(data):
    return {"code": 200, "msg": "Operation Successful", "data": data}


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    async def json(self, content_type=None):
        return self._payload


class FakeSession:
    def __init__(self, answers):
        self.answers = answers
        self.calls: list[tuple[str, dict, dict]] = []

    def post(self, url, json=None, headers=None):
        self.calls.append((url, json, headers))
        endpoint = url.removeprefix(f"{API_BASE}/")
        return FakeResponse(self.answers[endpoint])


def page(recipes):
    return ok({"pageIndex": 1, "pageSize": 20, "totalPage": 1, "total": len(recipes), "list": recipes})


def session(**extra):
    return FakeSession({
        "communityRecipe/recipe/criteria": ok(CRITERIA),
        "communityRecipe/index/page": page([LISTED]),
        "communityRecipe/recipe/detail": ok(DETAIL),
        **extra,
    })


def search_body(s):
    return next(body for url, body, _ in s.calls if url.endswith("index/page"))


async def test_bare_search_sends_the_web_clients_defaults():
    s = session()
    await XBloomCommunityClient(s).search()
    assert search_body(s) == {
        "pageIndex": 1, "pageSize": 20, "keyword": None, "recipeType": None,
        "recipeUserType": None, "sort": 1, "sortType": 2,
    }


async def test_filters_resolve_names_to_the_hubs_values():
    s = session()
    await XBloomCommunityClient(s).search(
        "  kenya ", machine="studio", kind="coffee", source="community",
        origins=["Kenya", "peru"], processes=["Washed"], roasts=["Light Roast"],
        flavors=["Plum"], cup_types=["Omni"], sort="likes", page=2, page_size=5,
    )
    body = search_body(s)
    assert body["keyword"] == "kenya"
    assert body["machineList"] == ["J15"]  # machines go as codes
    assert body["originIds"] == [9, 15]  # every other list as numbers
    assert body["processIds"] == [87]
    assert body["roastList"] == [1]
    assert body["flavorIds"] == [60]
    assert body["cupTypeList"] == [2]
    assert (body["recipeType"], body["recipeUserType"], body["sort"]) == (1, 2, 2)
    assert (body["pageIndex"], body["pageSize"]) == (2, 5)


async def test_unknown_filter_name_names_what_the_hub_knows():
    with pytest.raises(ValueError, match="Atlantis.*Kenya, Peru"):
        await XBloomCommunityClient(session()).search(origins=["Atlantis"])


async def test_bad_choice_is_refused_before_any_request():
    s = session()
    with pytest.raises(ValueError, match="sort"):
        await XBloomCommunityClient(s).search(sort="random")
    assert s.calls == []


async def test_criteria_is_fetched_once():
    s = session()
    client = XBloomCommunityClient(s)
    await client.search(origins=["Kenya"])
    await client.search(origins=["Peru"])
    assert sum(url.endswith("criteria") for url, _, _ in s.calls) == 1


async def test_search_parses_a_listed_recipe():
    result = await XBloomCommunityClient(session()).search()
    assert (result["page"], result["total_pages"], result["total"]) == (1, 1, 1)
    recipe = result["recipes"][0]
    assert recipe["id"] == 4021
    assert recipe["official"] is False
    assert recipe["roast"] == "Light Roast"
    assert recipe["water_ratio"] == 15.0
    assert recipe["cup_type"] == 2
    assert recipe["share_url"] == LISTED["shareRecipeLink"]


async def test_roast_zero_means_not_given():
    s = session(**{"communityRecipe/index/page": page([{**LISTED, "roast": 0}])})
    recipe = (await XBloomCommunityClient(s).search())["recipes"][0]
    assert recipe["roast"] is None


async def test_detail_asks_for_the_public_view_and_parses_pours():
    s = session()
    recipe = await XBloomCommunityClient(s).detail("4021")
    assert [body for url, body, _ in s.calls if url.endswith("recipe/detail")] == [
        {"id": 4021, "type": 1}
    ]
    assert recipe["description"] == "Bright and clean."
    assert recipe["uploaded_on"] == "2026-10-01"
    assert recipe["pours"][0] == {
        "name": "Bloom", "volume_ml": 40.0, "temperature_c": 92.0, "pattern": 2, "pause_s": 30,
    }


async def test_detail_counts_its_pours_when_the_hub_gives_no_count():
    """The live detail answer has a pourList and no pourCount."""
    bare = {k: v for k, v in DETAIL.items() if k != "pourCount"}
    s = session(**{"communityRecipe/recipe/detail": ok(bare)})
    assert (await XBloomCommunityClient(s).detail(4021))["pour_count"] == 2


async def test_names_are_trimmed():
    s = session(**{"communityRecipe/index/page": page([{**LISTED, "userName": "Test Author "}])})
    assert (await XBloomCommunityClient(s).search())["recipes"][0]["author"] == "Test Author"


async def test_hub_error_is_raised_with_its_message():
    s = session(**{"communityRecipe/recipe/detail": {"code": 400, "msg": "This requires you to log in first", "data": None}})
    with pytest.raises(XBloomAPIError, match="log in first"):
        await XBloomCommunityClient(s).detail(1)


@pytest.mark.parametrize(("language", "sent"), [
    (None, "0"), ("en-US", "0"), ("ar", "7"), ("ar_SA", "7"), ("zh-Hans", "3"), ("fr", "0"),
])
async def test_language_header(language, sent):
    s = session()
    await XBloomCommunityClient(s, language=language).criteria()
    assert s.calls[0][2]["LanguageType"] == sent


async def test_downloads_is_the_third_sort():
    s = session()
    await XBloomCommunityClient(s).search(sort="downloads")
    assert search_body(s)["sort"] == 3


CRITERIA_ZH = {**CRITERIA, "originList": [{"name": "肯尼亚", "value": "9"}, {"name": "秘鲁", "value": "15"}]}


class LanguageSession(FakeSession):
    """Answers the criteria in the language each request asks for."""

    def post(self, url, json=None, headers=None):
        if url.endswith("criteria"):
            self.calls.append((url, json, headers))
            return FakeResponse(ok(CRITERIA_ZH if headers["LanguageType"] == "3" else CRITERIA))
        return super().post(url, json=json, headers=headers)


async def test_an_english_name_works_in_another_language():
    s = LanguageSession({"communityRecipe/index/page": page([LISTED])})
    client = XBloomCommunityClient(s, language="zh")
    await client.search(origins=["肯尼亚", "Peru"])
    assert search_body(s)["originIds"] == [9, 15]
    assert [h["LanguageType"] for url, _, h in s.calls if url.endswith("criteria")] == ["3", "0"]


async def test_english_criteria_are_not_fetched_for_an_english_client():
    s = session()
    await XBloomCommunityClient(s).search(origins=["Kenya"])
    assert sum(url.endswith("criteria") for url, _, _ in s.calls) == 1
