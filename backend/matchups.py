from __future__ import annotations

from typing import Any

MATCHUP_LIMIT = 5
MIN_MATCHUP_GAMES = 3


def build_hero_matchups_from_records(
    records: list[Any],
    heroes_cache: list[dict[str, Any]],
    *,
    min_games: int = MIN_MATCHUP_GAMES,
    limit: int = MATCHUP_LIMIT,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    heroes_by_id = {int(hero["id"]): hero for hero in heroes_cache}
    aggregated: dict[int, dict[str, int]] = {}

    for record in records:
        for enemy_id in record.enemy_hero_ids:
            bucket = aggregated.setdefault(enemy_id, {"games": 0, "wins": 0})
            bucket["games"] += 1
            if record.won:
                bucket["wins"] += 1

    matchups: list[dict[str, Any]] = []
    for enemy_id, counts in aggregated.items():
        hero = heroes_by_id.get(enemy_id)
        if hero is None:
            continue

        games = counts["games"]
        wins = counts["wins"]
        if games < min_games:
            continue

        losses = games - wins
        matchups.append(
            {
                "hero_id": enemy_id,
                "hero_name": hero["name"],
                "hero_localized_name": hero["localized_name"],
                "games": games,
                "wins": wins,
                "losses": losses,
                "win_rate": round((wins / games) * 100, 1),
            }
        )

    ranked = sorted(
        matchups,
        key=lambda row: (row["win_rate"], row["games"]),
        reverse=True,
    )
    best = ranked[:limit]
    worst = list(reversed(ranked[-limit:])) if ranked else []
    return best, worst


def build_hero_matchups_from_counts(
    counts: list[tuple[int, int, int]],
    heroes_cache: list[dict[str, Any]],
    *,
    min_games: int = MIN_MATCHUP_GAMES,
    limit: int = MATCHUP_LIMIT,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Format pre-aggregated (enemy_hero_id, games, wins) rows from the database."""
    heroes_by_id = {int(hero["id"]): hero for hero in heroes_cache}

    matchups: list[dict[str, Any]] = []
    for enemy_id, games, wins in counts:
        hero = heroes_by_id.get(enemy_id)
        if hero is None or games < min_games:
            continue

        matchups.append(
            {
                "hero_id": enemy_id,
                "hero_name": hero["name"],
                "hero_localized_name": hero["localized_name"],
                "games": games,
                "wins": wins,
                "losses": games - wins,
                "win_rate": round((wins / games) * 100, 1),
            }
        )

    ranked = sorted(
        matchups,
        key=lambda row: (row["win_rate"], row["games"]),
        reverse=True,
    )
    best = ranked[:limit]
    worst = list(reversed(ranked[-limit:])) if ranked else []
    return best, worst
