from __future__ import annotations

from typing import Any

ITEMS_BY_ID: dict[int, dict[str, Any]] = {}
ITEMS_BY_KEY: dict[str, dict[str, Any]] = {}

# Consumables, laning defaults, and basic components — not "core" items.
EXCLUDED_ITEM_KEYS = {
    "tango",
    "tango_single",
    "clarity",
    "flask",
    "faerie_fire",
    "enchanted_mango",
    "blood_grenage",
    "blood_grenade",
    "magic_stick",
    "magic_wand",
    "branches",
    "tpscroll",
    "dust",
    "smoke_of_deceit",
    "ward_observer",
    "ward_sentry",
    "ward_dispenser",
    "courier",
    "fly_courier",
    "ring_of_protection",
    "sobi_mask",
    "quelling_blade",
    "orb_of_venom",
    "blight_stone",
    "wind_lace",
    "circlet",
    "gauntlets",
    "slippers",
    "mantle",
    "belt_of_strength",
    "boots_of_elves",
    "robe",
    "ogre_axe",
    "blade_of_alacrity",
    "staff_of_wizardry",
    "point_booster",
    "vitality_booster",
    "energy_booster",
    "void_stone",
    "ring_of_regen",
    "soul_ring",
    "infused_raindrop",
    "bottle",
    "orb_of_corrosion",
    "orb_of_destruction",
    "falcon_blade",
    "pers",
    "broadsword",
    "claymore",
    "mithril_hammer",
    "javelin",
    "blitz_knuckles",
    "chainmail",
    "platemail",
    "quarterstaff",
    "gloves",
    "lifesteal",
    "lesser_crit",
}

MIN_CORE_ITEM_COST = 600
# How many of the most recent matches (per hero) to analyze for item/matchup
# stats. Keeps the number of expensive per-match detail fetches bounded.
RECENT_MATCH_LIMIT = 25
MATCH_DETAIL_BATCH_SIZE = 10
MATCH_DETAIL_BATCH_DELAY_SECONDS = 0.35
ITEM_STATS_CACHE_TTL_SECONDS = 600
ITEM_IMAGE_BASE = (
    "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/items"
)


def load_items_cache(items: dict[str, Any]) -> None:
    global ITEMS_BY_ID, ITEMS_BY_KEY
    ITEMS_BY_ID = {}
    ITEMS_BY_KEY = {}

    for key, item in items.items():
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        if item_id is None:
            continue
        normalized = {
            "key": key,
            "id": int(item_id),
            "name": item.get("dname") or key,
            "cost": int(item.get("cost") or 0),
            "recipe": bool(item.get("recipe")),
        }
        ITEMS_BY_ID[normalized["id"]] = normalized
        ITEMS_BY_KEY[key] = normalized


def item_image_url(item_key: str) -> str:
    return f"{ITEM_IMAGE_BASE}/{item_key}.png"


def is_core_item_key(item_key: str) -> bool:
    if not item_key or item_key.startswith("recipe_"):
        return False
    if item_key in EXCLUDED_ITEM_KEYS:
        return False

    item = ITEMS_BY_KEY.get(item_key)
    if item is None:
        return False
    if item["recipe"]:
        return False
    if item["cost"] < MIN_CORE_ITEM_COST:
        return False
    return True


def is_core_item_id(item_id: int) -> bool:
    if item_id <= 0:
        return False
    item = ITEMS_BY_ID.get(item_id)
    if item is None:
        return False
    return is_core_item_key(item["key"])


def player_won(player_slot: int, radiant_win: bool) -> bool:
    is_radiant = player_slot < 128
    return radiant_win if is_radiant else not radiant_win


def core_items_from_player(player: dict[str, Any]) -> set[int]:
    item_ids: set[int] = set()

    purchase_log = player.get("purchase_log") or []
    if purchase_log:
        for entry in purchase_log:
            raw_key = entry.get("key") or ""
            item_key = raw_key.removeprefix("item_")
            if is_core_item_key(item_key):
                item_ids.add(ITEMS_BY_KEY[item_key]["id"])
        if item_ids:
            return item_ids

    for slot in range(6):
        item_id = int(player.get(f"item_{slot}") or 0)
        if is_core_item_id(item_id):
            item_ids.add(item_id)

    return item_ids


def build_top_item_stats(
    match_players: list[tuple[bool, set[int]]],
    limit: int = 10,
) -> list[dict[str, Any]]:
    aggregated: dict[int, dict[str, int]] = {}

    for won, item_ids in match_players:
        for item_id in item_ids:
            bucket = aggregated.setdefault(item_id, {"games": 0, "wins": 0})
            bucket["games"] += 1
            if won:
                bucket["wins"] += 1

    ranked: list[dict[str, Any]] = []
    for item_id, counts in aggregated.items():
        item = ITEMS_BY_ID.get(item_id)
        if item is None:
            continue
        games = counts["games"]
        wins = counts["wins"]
        ranked.append(
            {
                "item_id": item_id,
                "item_key": item["key"],
                "item_name": item["name"],
                "item_image": item_image_url(item["key"]),
                "games": games,
                "wins": wins,
                "losses": games - wins,
                "win_rate": round((wins / games) * 100, 1) if games else 0.0,
            }
        )

    ranked.sort(key=lambda row: (-row["games"], -row["win_rate"]))
    return ranked[:limit]


def build_item_stats_from_counts(
    counts: list[tuple[int, int, int]],
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Format pre-aggregated (item_id, games, wins) rows from the database."""
    ranked: list[dict[str, Any]] = []
    for item_id, games, wins in counts:
        item = ITEMS_BY_ID.get(item_id)
        if item is None:
            continue
        ranked.append(
            {
                "item_id": item_id,
                "item_key": item["key"],
                "item_name": item["name"],
                "item_image": item_image_url(item["key"]),
                "games": games,
                "wins": wins,
                "losses": games - wins,
                "win_rate": round((wins / games) * 100, 1) if games else 0.0,
            }
        )

    ranked.sort(key=lambda row: (-row["games"], -row["win_rate"]))
    return ranked[:limit]
