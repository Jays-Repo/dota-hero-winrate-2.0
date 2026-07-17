from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import aiosqlite
import httpx

import db
from items import (
    MATCH_DETAIL_BATCH_DELAY_SECONDS,
    MATCH_DETAIL_BATCH_SIZE,
    RECENT_MATCH_LIMIT,
    core_items_from_player,
    player_won,
)
from opendota import OpenDotaError, fetch_json


@dataclass
class SyncedMatch:
    """A single match ready to be persisted for a given (account, hero)."""

    match_id: int
    won: bool
    played_at: int | None
    item_ids: set[int] = field(default_factory=set)
    enemy_hero_ids: set[int] = field(default_factory=set)


def enemy_hero_ids_from_match(
    detail: dict[str, Any],
    player_slot: int,
) -> set[int]:
    is_radiant = player_slot < 128
    enemy_ids: set[int] = set()

    for row in detail.get("players", []):
        slot = int(row.get("player_slot", 0))
        if (slot < 128) == is_radiant:
            continue
        hero_id = int(row.get("hero_id") or 0)
        if hero_id:
            enemy_ids.add(hero_id)

    return enemy_ids


async def list_hero_matches(
    client: httpx.AsyncClient,
    account_id: int,
    hero_id: int,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    offset = 0
    page_size = 100

    while limit is None or len(matches) < limit:
        fetch_size = page_size if limit is None else min(page_size, limit - len(matches))
        payload = await fetch_json(
            client,
            (
                f"players/{account_id}/matches"
                f"?hero_id={hero_id}&limit={fetch_size}&offset={offset}"
            ),
        )
        if not isinstance(payload, list) or not payload:
            break

        matches.extend(payload)
        if len(payload) < fetch_size:
            break
        offset += len(payload)

    if limit is not None:
        return matches[:limit]
    return matches


async def fetch_match_detail(
    client: httpx.AsyncClient,
    match_id: int,
) -> dict[str, Any] | None:
    try:
        payload = await fetch_json(client, f"matches/{match_id}")
    except OpenDotaError:
        return None
    return payload if isinstance(payload, dict) else None


def build_synced_match(
    summary: dict[str, Any],
    detail: dict[str, Any] | None,
    account_id: int,
    hero_id: int,
) -> SyncedMatch | None:
    """Build a fully-populated match record, or None if it should be retried.

    We only persist a match once we have its detail (which carries the enemy
    lineup and item purchases). If the detail fetch failed, return None so the
    match stays un-synced and gets retried on the next sync instead of being
    permanently stored with empty data.
    """
    if detail is None:
        return None

    player_slot = int(summary["player_slot"])
    won = player_won(player_slot, bool(summary["radiant_win"]))
    played_at = summary.get("start_time")

    # Match on player_slot from the summary; account_id can be anonymized in the
    # detail payload, which would otherwise cause us to never find the player.
    player = next(
        (
            row
            for row in detail.get("players", [])
            if int(row.get("player_slot", -1)) == player_slot
        ),
        None,
    )
    if player is None:
        return None

    return SyncedMatch(
        match_id=int(summary["match_id"]),
        won=won,
        played_at=int(played_at) if played_at else None,
        item_ids=core_items_from_player(player),
        enemy_hero_ids=enemy_hero_ids_from_match(detail, player_slot),
    )


async def sync_hero_matches(
    client: httpx.AsyncClient,
    conn: aiosqlite.Connection,
    account_id: int,
    hero_id: int,
    limit: int | None = RECENT_MATCH_LIMIT,
) -> int:
    """Fetch only matches we haven't stored yet, persist them, return new count.

    The match list from OpenDota is cheap (a few paginated calls). We diff it
    against what's already in the database and only pull the expensive per-match
    detail for matches we've never seen before. `limit` bounds how many of the
    most recent matches we analyze, keeping detail fetches cheap.
    """
    match_summaries = await list_hero_matches(client, account_id, hero_id, limit)
    if not match_summaries:
        return 0

    # Repair any matches previously stored without their enemy lineup (e.g. from
    # a rate-limited backfill) so they get re-fetched below.
    await db.delete_matches_missing_enemies(conn, account_id, hero_id)

    known_ids = await db.get_synced_match_ids(conn, account_id, hero_id)
    new_summaries = [
        summary
        for summary in match_summaries
        if int(summary["match_id"]) not in known_ids
    ]
    if not new_summaries:
        return 0

    new_records: list[SyncedMatch] = []

    for start in range(0, len(new_summaries), MATCH_DETAIL_BATCH_SIZE):
        batch = new_summaries[start : start + MATCH_DETAIL_BATCH_SIZE]
        details = await asyncio.gather(
            *(fetch_match_detail(client, int(row["match_id"])) for row in batch)
        )

        for summary, detail in zip(batch, details, strict=False):
            record = build_synced_match(summary, detail, account_id, hero_id)
            if record is not None:
                new_records.append(record)

        if start + MATCH_DETAIL_BATCH_SIZE < len(new_summaries):
            await asyncio.sleep(MATCH_DETAIL_BATCH_DELAY_SECONDS)

    await db.store_match_records(conn, account_id, hero_id, new_records)
    return len(new_records)
