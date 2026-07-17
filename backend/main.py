from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import db
from items import (
    ITEM_STATS_CACHE_TTL_SECONDS,
    RECENT_MATCH_LIMIT,
    build_item_stats_from_counts,
    load_items_cache,
)
from match_analysis import sync_hero_matches
from matchups import build_hero_matchups_from_counts
from opendota import (
    API_KEY,
    OpenDotaError,
    fetch_json,
    get_rate_limit_info,
    normalize_account_id,
)

HEROES_CACHE: list[dict[str, Any]] = []
# Single-element list so helpers can flip the flag without `global`.
ITEMS_LOADED: list[bool] = [False]


class HeroSummary(BaseModel):
    id: int
    name: str
    localized_name: str


class PlayerProfile(BaseModel):
    account_id: int
    personaname: str | None = None
    avatarfull: str | None = None
    profileurl: str | None = None


class SideStats(BaseModel):
    games: int
    wins: int
    losses: int
    win_rate: float = Field(description="Win rate as a percentage (0-100).")


class ItemStat(BaseModel):
    item_id: int
    item_key: str
    item_name: str
    item_image: str
    games: int
    wins: int
    losses: int
    win_rate: float


class HeroWinRate(BaseModel):
    account_id: int
    hero_id: int
    hero_name: str
    hero_localized_name: str
    games: int
    wins: int
    losses: int
    win_rate: float = Field(description="Win rate as a percentage (0-100).")
    last_played: int | None = None
    radiant: SideStats
    dire: SideStats


class TopItemsResponse(BaseModel):
    account_id: int
    hero_id: int
    top_items: list[ItemStat]
    items_sample_size: int


class MatchupStat(BaseModel):
    hero_id: int
    hero_name: str
    hero_localized_name: str
    games: int
    wins: int
    losses: int
    win_rate: float


class MatchupsResponse(BaseModel):
    account_id: int
    hero_id: int
    best_against: list[MatchupStat]
    worst_against: list[MatchupStat]
    sample_size: int


class StatusResponse(BaseModel):
    reference_data_loaded: bool
    using_api_key: bool
    cached_matches: int
    cached_heroes: int
    cached_accounts: int
    rate_limit_remaining_minute: int | None = None
    rate_limit_remaining_day: int | None = None
    daily_limit_reset_utc: str
    daily_limit_reset_in_seconds: int


class HeroAnalysisResponse(BaseModel):
    account_id: int
    hero_id: int
    top_items: list[ItemStat]
    items_sample_size: int
    best_against: list[MatchupStat]
    worst_against: list[MatchupStat]


ANALYSIS_CACHE: dict[tuple[int, int], tuple[float, HeroAnalysisResponse]] = {}
ANALYSIS_INFLIGHT: dict[tuple[int, int], asyncio.Task[HeroAnalysisResponse]] = {}


async def load_reference_data(
    client: httpx.AsyncClient,
    conn: "aiosqlite.Connection",
) -> bool:
    """Populate the hero list and item constants. Returns True on success.

    Tries OpenDota first and caches the result in the DB. If OpenDota is
    unreachable (e.g. rate-limited), falls back to the last cached copy so the
    app keeps working offline against already-synced data. Safe to call
    repeatedly; only fetches what's still missing.
    """
    global HEROES_CACHE

    if not HEROES_CACHE:
        heroes: Any = None
        try:
            heroes = await fetch_json(client, "heroes")
            if isinstance(heroes, list):
                await db.save_reference(conn, "heroes", heroes)
        except OpenDotaError:
            heroes = await db.load_reference(conn, "heroes")
            if heroes is None:
                raise
        if isinstance(heroes, list):
            HEROES_CACHE = sorted(
                heroes, key=lambda hero: hero["localized_name"].lower()
            )

    if not ITEMS_LOADED[0]:
        items: Any = None
        try:
            items = await fetch_json(client, "constants/items")
            if isinstance(items, dict):
                await db.save_reference(conn, "items", items)
        except OpenDotaError:
            items = await db.load_reference(conn, "items")
            if items is None:
                raise
        if isinstance(items, dict):
            load_items_cache(items)
            ITEMS_LOADED[0] = True

    return bool(HEROES_CACHE) and ITEMS_LOADED[0]


async def ensure_reference_data() -> None:
    """Lazily load reference data if startup couldn't reach OpenDota."""
    if HEROES_CACHE and ITEMS_LOADED[0]:
        return
    client: httpx.AsyncClient = app.state.http_client
    conn = app.state.db
    try:
        await load_reference_data(client, conn)
    except OpenDotaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    if not HEROES_CACHE:
        raise HTTPException(
            status_code=503,
            detail="Hero data is not available yet. Try again in a minute.",
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    connection = await db.connect()
    app.state.db = connection
    try:
        async with httpx.AsyncClient() as client:
            app.state.http_client = client
            try:
                await load_reference_data(client, connection)
            except OpenDotaError as exc:
                # Don't crash the server if OpenDota is rate-limiting or down at
                # boot; we'll lazily load this data on the first request instead.
                print(f"[startup] Reference data not loaded yet: {exc}")
            yield
    finally:
        await connection.close()


app = FastAPI(
    title="Dota Hero Winrate API",
    description="Small API that wraps OpenDota player hero stats.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def hero_lookup(hero_id: int) -> dict[str, Any]:
    for hero in HEROES_CACHE:
        if hero["id"] == hero_id:
            return hero
    raise HTTPException(status_code=404, detail=f"Hero {hero_id} not found.")


def side_stats_from_wl(payload: object) -> SideStats:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="Unexpected OpenDota response.")

    wins = int(payload.get("win", 0))
    losses = int(payload.get("lose", 0))
    games = wins + losses
    win_rate = round((wins / games) * 100, 1) if games else 0.0

    return SideStats(
        games=games,
        wins=wins,
        losses=losses,
        win_rate=win_rate,
    )


async def fetch_side_stats(
    client: httpx.AsyncClient,
    account_id: int,
    hero_id: int,
    is_radiant: int,
) -> SideStats:
    try:
        payload = await fetch_json(
            client,
            f"players/{account_id}/wl?hero_id={hero_id}&is_radiant={is_radiant}",
        )
    except OpenDotaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return side_stats_from_wl(payload)


def get_cached_analysis(account_id: int, hero_id: int) -> HeroAnalysisResponse | None:
    cached = ANALYSIS_CACHE.get((account_id, hero_id))
    if cached is None:
        return None

    expires_at, payload = cached
    if time.monotonic() > expires_at:
        ANALYSIS_CACHE.pop((account_id, hero_id), None)
        return None

    return payload


def store_cached_analysis(payload: HeroAnalysisResponse) -> None:
    ANALYSIS_CACHE[(payload.account_id, payload.hero_id)] = (
        time.monotonic() + ITEM_STATS_CACHE_TTL_SECONDS,
        payload,
    )


async def get_hero_analysis(
    client: httpx.AsyncClient,
    conn: "aiosqlite.Connection",
    account_id: int,
    hero_id: int,
) -> HeroAnalysisResponse:
    cache_key = (account_id, hero_id)
    cached = get_cached_analysis(account_id, hero_id)
    if cached is not None:
        return cached

    inflight = ANALYSIS_INFLIGHT.get(cache_key)
    if inflight is not None:
        return await inflight

    async def compute() -> HeroAnalysisResponse:
        # Pull only matches we haven't stored yet, then read fast local aggregates.
        # If the refresh fails (e.g. rate-limited) but we already have this hero
        # cached, fall back to the stored data instead of erroring out.
        try:
            await sync_hero_matches(client, conn, account_id, hero_id, RECENT_MATCH_LIMIT)
        except OpenDotaError:
            already_cached = await db.count_matches(conn, account_id, hero_id)
            if already_cached == 0:
                raise

        sample_size = await db.count_matches(
            conn, account_id, hero_id, RECENT_MATCH_LIMIT
        )
        item_counts = await db.aggregate_items(
            conn, account_id, hero_id, RECENT_MATCH_LIMIT
        )
        enemy_counts = await db.aggregate_enemies(
            conn, account_id, hero_id, RECENT_MATCH_LIMIT
        )

        item_rows = build_item_stats_from_counts(item_counts, limit=10)
        best_rows, worst_rows = build_hero_matchups_from_counts(
            enemy_counts, HEROES_CACHE
        )

        payload = HeroAnalysisResponse(
            account_id=account_id,
            hero_id=hero_id,
            top_items=[ItemStat(**row) for row in item_rows],
            items_sample_size=sample_size,
            best_against=[MatchupStat(**row) for row in best_rows],
            worst_against=[MatchupStat(**row) for row in worst_rows],
        )
        store_cached_analysis(payload)
        return payload

    task = asyncio.create_task(compute())
    ANALYSIS_INFLIGHT[cache_key] = task
    try:
        return await task
    finally:
        ANALYSIS_INFLIGHT.pop(cache_key, None)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/status", response_model=StatusResponse)
async def get_status() -> StatusResponse:
    conn = app.state.db
    summary = await db.cache_summary(conn)
    rate = get_rate_limit_info()

    now = datetime.now(timezone.utc)
    next_reset = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    return StatusResponse(
        reference_data_loaded=bool(HEROES_CACHE) and ITEMS_LOADED[0],
        using_api_key=bool(API_KEY),
        cached_matches=summary["matches"],
        cached_heroes=summary["heroes"],
        cached_accounts=summary["accounts"],
        rate_limit_remaining_minute=rate.get("remaining_minute"),
        rate_limit_remaining_day=rate.get("remaining_day"),
        daily_limit_reset_utc=next_reset.isoformat(),
        daily_limit_reset_in_seconds=int((next_reset - now).total_seconds()),
    )


@app.get("/api/heroes", response_model=list[HeroSummary])
async def list_heroes() -> list[HeroSummary]:
    await ensure_reference_data()
    return [
        HeroSummary(
            id=hero["id"],
            name=hero["name"],
            localized_name=hero["localized_name"],
        )
        for hero in HEROES_CACHE
    ]


@app.get("/api/players/{account_id}", response_model=PlayerProfile)
async def get_player(account_id: int) -> PlayerProfile:
    client: httpx.AsyncClient = app.state.http_client
    conn = app.state.db
    cache_key = f"player:{account_id}"

    try:
        payload = await fetch_json(client, f"players/{account_id}")
        profile = payload.get("profile") or {}
        result = PlayerProfile(
            account_id=account_id,
            personaname=profile.get("personaname"),
            avatarfull=profile.get("avatarfull"),
            profileurl=profile.get("profileurl"),
        )
        await db.save_reference(conn, cache_key, result.model_dump())
        return result
    except OpenDotaError as exc:
        # OpenDota's /players endpoint occasionally 500s. Serve the last known
        # profile if we've cached one, rather than failing the request.
        cached = await db.load_reference(conn, cache_key)
        if cached is not None:
            return PlayerProfile(**cached)
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get("/api/winrate", response_model=HeroWinRate)
async def get_hero_winrate(
    account_id: str = Query(..., description="Steam32 account ID or Steam64 ID."),
    hero_id: int = Query(..., ge=1),
) -> HeroWinRate:
    try:
        normalized_account_id = normalize_account_id(account_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await ensure_reference_data()
    hero = hero_lookup(hero_id)
    client: httpx.AsyncClient = app.state.http_client

    try:
        hero_stats = await fetch_json(client, f"players/{normalized_account_id}/heroes")
    except OpenDotaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    if not isinstance(hero_stats, list):
        raise HTTPException(status_code=502, detail="Unexpected OpenDota response.")

    match = next((row for row in hero_stats if row.get("hero_id") == hero_id), None)
    if match is None or match.get("games", 0) == 0:
        raise HTTPException(
            status_code=404,
            detail="No recorded games found for this player on the selected hero.",
        )

    games = int(match["games"])
    wins = int(match.get("win", 0))
    losses = games - wins

    radiant, dire = await asyncio.gather(
        fetch_side_stats(client, normalized_account_id, hero_id, 1),
        fetch_side_stats(client, normalized_account_id, hero_id, 0),
    )

    return HeroWinRate(
        account_id=normalized_account_id,
        hero_id=hero_id,
        hero_name=hero["name"],
        hero_localized_name=hero["localized_name"],
        games=games,
        wins=wins,
        losses=losses,
        win_rate=round((wins / games) * 100, 1),
        last_played=match.get("last_played") or None,
        radiant=radiant,
        dire=dire,
    )


@app.get("/api/hero-analysis", response_model=HeroAnalysisResponse)
async def get_hero_analysis_endpoint(
    account_id: str = Query(..., description="Steam32 account ID or Steam64 ID."),
    hero_id: int = Query(..., ge=1),
) -> HeroAnalysisResponse:
    try:
        normalized_account_id = normalize_account_id(account_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await ensure_reference_data()
    hero_lookup(hero_id)
    client: httpx.AsyncClient = app.state.http_client
    conn = app.state.db

    try:
        return await get_hero_analysis(client, conn, normalized_account_id, hero_id)
    except OpenDotaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


async def load_hero_analysis(account_id: str, hero_id: int) -> HeroAnalysisResponse:
    try:
        normalized_account_id = normalize_account_id(account_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await ensure_reference_data()
    hero_lookup(hero_id)
    client: httpx.AsyncClient = app.state.http_client
    conn = app.state.db

    try:
        return await get_hero_analysis(client, conn, normalized_account_id, hero_id)
    except OpenDotaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get("/api/top-items", response_model=TopItemsResponse)
async def get_top_items(
    account_id: str = Query(..., description="Steam32 account ID or Steam64 ID."),
    hero_id: int = Query(..., ge=1),
) -> TopItemsResponse:
    analysis = await load_hero_analysis(account_id, hero_id)
    return TopItemsResponse(
        account_id=analysis.account_id,
        hero_id=analysis.hero_id,
        top_items=analysis.top_items,
        items_sample_size=analysis.items_sample_size,
    )


@app.get("/api/matchups", response_model=MatchupsResponse)
async def get_matchups(
    account_id: str = Query(..., description="Steam32 account ID or Steam64 ID."),
    hero_id: int = Query(..., ge=1),
) -> MatchupsResponse:
    analysis = await load_hero_analysis(account_id, hero_id)
    return MatchupsResponse(
        account_id=analysis.account_id,
        hero_id=analysis.hero_id,
        best_against=analysis.best_against,
        worst_against=analysis.worst_against,
        sample_size=analysis.items_sample_size,
    )
