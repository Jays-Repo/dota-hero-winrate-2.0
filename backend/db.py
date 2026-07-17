"""SQLite storage for cached per-match item and enemy data.

The heavy OpenDota work (fetching every match detail for a hero) only needs to
happen once per match. We store the parsed results here so repeat lookups are
fast local queries instead of dozens of API calls.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Iterable

import aiosqlite

DB_PATH = Path(__file__).parent / "dota_stats.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS synced_matches (
    account_id INTEGER NOT NULL,
    hero_id    INTEGER NOT NULL,
    match_id   INTEGER NOT NULL,
    won        INTEGER NOT NULL,
    played_at  INTEGER,
    PRIMARY KEY (account_id, hero_id, match_id)
);

CREATE TABLE IF NOT EXISTS match_items (
    account_id INTEGER NOT NULL,
    hero_id    INTEGER NOT NULL,
    match_id   INTEGER NOT NULL,
    item_id    INTEGER NOT NULL,
    PRIMARY KEY (account_id, hero_id, match_id, item_id)
);

CREATE TABLE IF NOT EXISTS match_enemies (
    account_id    INTEGER NOT NULL,
    hero_id       INTEGER NOT NULL,
    match_id      INTEGER NOT NULL,
    enemy_hero_id INTEGER NOT NULL,
    PRIMARY KEY (account_id, hero_id, match_id, enemy_hero_id)
);

CREATE INDEX IF NOT EXISTS idx_items_lookup
    ON match_items (account_id, hero_id);
CREATE INDEX IF NOT EXISTS idx_enemies_lookup
    ON match_enemies (account_id, hero_id);

CREATE TABLE IF NOT EXISTS reference_cache (
    key        TEXT PRIMARY KEY,
    json       TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);
"""


async def connect() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(DB_PATH)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys = ON;")
    await conn.executescript(SCHEMA)
    await conn.commit()
    return conn


async def save_reference(
    conn: aiosqlite.Connection,
    key: str,
    value: Any,
) -> None:
    """Persist rarely-changing OpenDota data (hero list, item constants)."""
    await conn.execute(
        "INSERT INTO reference_cache (key, json, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET json = excluded.json, "
        "updated_at = excluded.updated_at",
        (key, json.dumps(value), int(time.time())),
    )
    await conn.commit()


async def load_reference(conn: aiosqlite.Connection, key: str) -> Any | None:
    async with conn.execute(
        "SELECT json FROM reference_cache WHERE key = ?",
        (key,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None
    return json.loads(row["json"])


async def get_synced_match_ids(
    conn: aiosqlite.Connection,
    account_id: int,
    hero_id: int,
) -> set[int]:
    async with conn.execute(
        "SELECT match_id FROM synced_matches WHERE account_id = ? AND hero_id = ?",
        (account_id, hero_id),
    ) as cursor:
        rows = await cursor.fetchall()
    return {int(row["match_id"]) for row in rows}


async def store_match_records(
    conn: aiosqlite.Connection,
    account_id: int,
    hero_id: int,
    records: Iterable["SyncedMatch"],
) -> None:
    match_rows: list[tuple[int, int, int, int, int | None]] = []
    item_rows: list[tuple[int, int, int, int]] = []
    enemy_rows: list[tuple[int, int, int, int]] = []

    for record in records:
        match_rows.append(
            (account_id, hero_id, record.match_id, int(record.won), record.played_at)
        )
        for item_id in record.item_ids:
            item_rows.append((account_id, hero_id, record.match_id, item_id))
        for enemy_id in record.enemy_hero_ids:
            enemy_rows.append((account_id, hero_id, record.match_id, enemy_id))

    if not match_rows:
        return

    await conn.executemany(
        "INSERT OR IGNORE INTO synced_matches "
        "(account_id, hero_id, match_id, won, played_at) VALUES (?, ?, ?, ?, ?)",
        match_rows,
    )
    if item_rows:
        await conn.executemany(
            "INSERT OR IGNORE INTO match_items "
            "(account_id, hero_id, match_id, item_id) VALUES (?, ?, ?, ?)",
            item_rows,
        )
    if enemy_rows:
        await conn.executemany(
            "INSERT OR IGNORE INTO match_enemies "
            "(account_id, hero_id, match_id, enemy_hero_id) VALUES (?, ?, ?, ?)",
            enemy_rows,
        )
    await conn.commit()


async def delete_matches_missing_enemies(
    conn: aiosqlite.Connection,
    account_id: int,
    hero_id: int,
) -> int:
    """Remove matches stored without any enemy lineup so they can be re-synced.

    Every real match has 5 enemies, so a synced match with no rows in
    match_enemies is incomplete (e.g. its detail fetch was rate-limited).
    Returns the number of rows removed.
    """
    cursor = await conn.execute(
        """
        DELETE FROM synced_matches
        WHERE account_id = ? AND hero_id = ?
          AND match_id NOT IN (
              SELECT match_id FROM match_enemies
              WHERE account_id = ? AND hero_id = ?
          )
        """,
        (account_id, hero_id, account_id, hero_id),
    )
    removed = cursor.rowcount
    await conn.commit()
    return removed if removed is not None else 0


async def count_matches(
    conn: aiosqlite.Connection,
    account_id: int,
    hero_id: int,
    limit: int | None = None,
) -> int:
    if limit is None:
        async with conn.execute(
            "SELECT COUNT(*) AS n FROM synced_matches "
            "WHERE account_id = ? AND hero_id = ?",
            (account_id, hero_id),
        ) as cursor:
            row = await cursor.fetchone()
        return int(row["n"]) if row else 0

    async with conn.execute(
        """
        SELECT COUNT(*) AS n FROM (
            SELECT match_id FROM synced_matches
            WHERE account_id = ? AND hero_id = ?
            ORDER BY played_at DESC
            LIMIT ?
        )
        """,
        (account_id, hero_id, limit),
    ) as cursor:
        row = await cursor.fetchone()
    return int(row["n"]) if row else 0


def _recent_match_cte() -> str:
    """Subquery selecting the most recent `limit` match_ids for a hero."""
    return (
        "SELECT match_id FROM synced_matches "
        "WHERE account_id = ? AND hero_id = ? "
        "ORDER BY played_at DESC LIMIT ?"
    )


async def cache_summary(conn: aiosqlite.Connection) -> dict[str, int]:
    """Totals across everything stored, for a status/overview view."""
    async with conn.execute(
        """
        SELECT COUNT(*) AS matches,
               COUNT(DISTINCT hero_id) AS heroes,
               COUNT(DISTINCT account_id) AS accounts
        FROM synced_matches
        """
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return {"matches": 0, "heroes": 0, "accounts": 0}
    return {
        "matches": int(row["matches"]),
        "heroes": int(row["heroes"]),
        "accounts": int(row["accounts"]),
    }


async def aggregate_items(
    conn: aiosqlite.Connection,
    account_id: int,
    hero_id: int,
    limit: int | None = None,
) -> list[tuple[int, int, int]]:
    """Return (item_id, games, wins) tuples for the hero.

    When `limit` is set, only the most recent `limit` matches are considered.
    """
    if limit is None:
        query = """
            SELECT mi.item_id AS item_id,
                   COUNT(*) AS games,
                   SUM(sm.won) AS wins
            FROM match_items mi
            JOIN synced_matches sm
              ON sm.account_id = mi.account_id
             AND sm.hero_id = mi.hero_id
             AND sm.match_id = mi.match_id
            WHERE mi.account_id = ? AND mi.hero_id = ?
            GROUP BY mi.item_id
        """
        params: tuple[Any, ...] = (account_id, hero_id)
    else:
        query = f"""
            SELECT mi.item_id AS item_id,
                   COUNT(*) AS games,
                   SUM(sm.won) AS wins
            FROM match_items mi
            JOIN synced_matches sm
              ON sm.account_id = mi.account_id
             AND sm.hero_id = mi.hero_id
             AND sm.match_id = mi.match_id
            WHERE mi.account_id = ? AND mi.hero_id = ?
              AND mi.match_id IN ({_recent_match_cte()})
            GROUP BY mi.item_id
        """
        params = (account_id, hero_id, account_id, hero_id, limit)

    async with conn.execute(query, params) as cursor:
        rows = await cursor.fetchall()
    return [(int(r["item_id"]), int(r["games"]), int(r["wins"])) for r in rows]


async def aggregate_enemies(
    conn: aiosqlite.Connection,
    account_id: int,
    hero_id: int,
    limit: int | None = None,
) -> list[tuple[int, int, int]]:
    """Return (enemy_hero_id, games, wins) tuples for the hero.

    When `limit` is set, only the most recent `limit` matches are considered.
    """
    if limit is None:
        query = """
            SELECT me.enemy_hero_id AS enemy_hero_id,
                   COUNT(*) AS games,
                   SUM(sm.won) AS wins
            FROM match_enemies me
            JOIN synced_matches sm
              ON sm.account_id = me.account_id
             AND sm.hero_id = me.hero_id
             AND sm.match_id = me.match_id
            WHERE me.account_id = ? AND me.hero_id = ?
            GROUP BY me.enemy_hero_id
        """
        params: tuple[Any, ...] = (account_id, hero_id)
    else:
        query = f"""
            SELECT me.enemy_hero_id AS enemy_hero_id,
                   COUNT(*) AS games,
                   SUM(sm.won) AS wins
            FROM match_enemies me
            JOIN synced_matches sm
              ON sm.account_id = me.account_id
             AND sm.hero_id = me.hero_id
             AND sm.match_id = me.match_id
            WHERE me.account_id = ? AND me.hero_id = ?
              AND me.match_id IN ({_recent_match_cte()})
            GROUP BY me.enemy_hero_id
        """
        params = (account_id, hero_id, account_id, hero_id, limit)

    async with conn.execute(query, params) as cursor:
        rows = await cursor.fetchall()
    return [
        (int(r["enemy_hero_id"]), int(r["games"]), int(r["wins"])) for r in rows
    ]
