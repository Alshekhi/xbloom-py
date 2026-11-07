"""Response shape definitions for the xBloom cloud API.

All types are TypedDict — JSON-compatible, zero serialization cost,
cheap on hot data paths (no dataclass overhead).
Field names map from API camelCase to Python snake_case.
"""
from typing import TypedDict


class Pour(TypedDict):
    """One pour step within a recipe. All 10 fields always present in API response."""
    id: int               # tableId
    recipe_id: int        # recipeId
    name: str             # theName: "Bloom", "Pour1", etc.
    volume_ml: float      # volume (mL)
    temperature_c: float  # temperature (°C)
    pattern: int          # 1=centered, 2=spiral, 3=circular (confirmed vs xBloom app UI)
    flow_rate: float      # flowRate (mL/s)
    pause_s: int          # pausing (seconds after pour)
    agitate_before: int   # isEnableVibrationBefore: 1=yes, 2=no
    agitate_after: int    # isEnableVibrationAfter: 1=yes, 2=no


class _RecipeRequired(TypedDict):
    """Always-present recipe fields (all 20 observed in every live API response)."""
    # Identity
    id: str               # tableId cast to str for host compatibility
    name: str             # theName
    # Brew parameters
    dose_g: float         # dose (coffee grams)
    water_ratio: float    # grandWater (water-to-coffee ratio multiplier)
    grinder_size: float   # grinderSize
    grinder_size_enabled: int  # isSetGrinderSize: 1=enabled, 2=disabled
    rpm: int              # rpm (grinder motor)
    # Pour structure
    pour_count: int       # pourCount
    pours: list           # pourList — list[Pour] semantically
    # Cup type
    cup_type: int         # cupType: 1=XPOD, 2=OMNI
    cup_type_name: str    # cupTypeName
    # Bypass water (flag always present; values absent when disabled)
    bypass_water_enabled: int  # isEnableBypassWater: 1=yes, 2=no
    # Metadata
    color_hex: str        # theColor e.g. "#DED9AF"
    adapted_model: int    # adaptedModel (machine model compatibility)
    created_at_ms: int    # createTimeStamp (Unix ms)
    is_default: int       # isDefault: 1=yes
    is_shortcut: int      # isShortcuts: 1=yes, 2=no
    subset_type: int      # subSetType (all observed: 1)
    subset_id: int        # theSubsetId
    share_url: str        # shareRecipeLink


class CommunityPour(TypedDict):
    """One pour as the community hub lists it — no flow rate, no agitation."""
    name: str             # theName: "Bloom", "Pour1", ...
    volume_ml: float      # volume
    temperature_c: float  # temperature
    pattern: int          # api id: 1=centered, 2=spiral, 3=circular
    pause_s: int          # pausing


class CommunityRecipe(TypedDict):
    """A recipe as the community hub's search lists it."""
    id: int               # communityRecipeId — what detail() takes
    name: str             # recipeName
    author: str           # userName
    official: bool        # official == 1: shared by xBloom itself
    machine: str          # model: "Studio", "Original"
    cup_type: int         # cupTypeInt, as in spec.CUP_TYPES
    coffee_type: str      # type: "Single Origin", "Blend", "" for tea
    origin: list          # list[str]
    varietal: list        # list[str]
    process: list         # list[str]
    flavor: list          # list[str], the author's tasting notes
    roast: str | None     # roast resolved to its name; None when not given
    dose_g: float | None
    water_ratio: float | None  # grandWater: the ratio denominator (1:N)
    grinder_size: float | None
    rpm: int
    pour_count: int
    cup_volume: str       # volume, free text: "225", "~600"
    likes: int            # likesCount
    image_url: str
    share_url: str        # shareRecipeLink — resolves to the full Recipe


class CommunityRecipeDetail(CommunityRecipe):
    """A hub recipe with its description and pours."""
    description: str      # introduce
    uploaded_on: str      # uploadDate, YYYY-MM-DD
    pours: list           # list[CommunityPour]


class CommunityPage(TypedDict):
    """One page of a hub search."""
    page: int
    total_pages: int
    total: int
    recipes: list         # list[CommunityRecipe]


class Recipe(_RecipeRequired, total=False):
    """Full recipe record. Optional fields absent when not applicable."""
    bypass_temp_c: float      # bypassTemp — absent when bypass_water_enabled == 2
    bypass_volume_ml: float   # bypassVolume — absent when bypass_water_enabled == 2
    pod: dict                 # podsVo — absent when recipe has no linked pod
    shared: bool              # True for a downloaded "Shared Recipe" (tuMyRecipeShared)
