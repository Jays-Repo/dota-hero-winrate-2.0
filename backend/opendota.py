from __future__ import annotations

import asyncio
import collections
import os
import time

import httpx

OPENDOTA_BASE = "https://api.opendota.com/api"

# OpenDota free tier allows ~60 requests/minute. With a (free) API key the limit
# is much higher. Set OPENDOTA_API_KEY in the environment to use one.
API_KEY = os.environ.get("OPENDOTA_API_KEY", "").strip()

# Stay safely under the limit. Default assumes no key; a key bumps it way up.
_default_limit = "1000" if API_KEY else "50"
RATE_LIMIT_PER_MIN = int(os.environ.get("OPENDOTA_RATE_LIMIT", _default_limit))

# Shared token bucket across every OpenDota call so a big sync can't starve the
# fast endpoints (win rate, player profile) into rate-limit errors.
_request_times: "collections.deque[float]" = collections.deque()
_rate_lock = asyncio.Lock()

# Most recent rate-limit info reported by OpenDota response headers.
LAST_RATE_LIMIT: dict[str, int | float | None] = {
    "remaining_minute": None,
    "remaining_day": None,
    "updated_at": None,
}


def _record_rate_limit(headers: httpx.Headers) -> None:
    minute = headers.get("x-rate-limit-remaining-minute")
    day = headers.get("x-rate-limit-remaining-day")
    if minute is not None:
        try:
            LAST_RATE_LIMIT["remaining_minute"] = int(minute)
        except ValueError:
            pass
    if day is not None:
        try:
            LAST_RATE_LIMIT["remaining_day"] = int(day)
        except ValueError:
            pass
    if minute is not None or day is not None:
        LAST_RATE_LIMIT["updated_at"] = time.time()


def get_rate_limit_info() -> dict[str, int | float | None]:
    return dict(LAST_RATE_LIMIT)


class OpenDotaError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


def _with_api_key(url: str) -> str:
    if not API_KEY:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}api_key={API_KEY}"


async def _throttle() -> None:
    """Block until we're allowed to make another request this minute."""
    async with _rate_lock:
        now = time.monotonic()
        while _request_times and now - _request_times[0] >= 60:
            _request_times.popleft()

        if len(_request_times) >= RATE_LIMIT_PER_MIN:
            wait = 60 - (now - _request_times[0]) + 0.05
            if wait > 0:
                await asyncio.sleep(wait)
            now = time.monotonic()
            while _request_times and now - _request_times[0] >= 60:
                _request_times.popleft()

        _request_times.append(time.monotonic())


async def fetch_json(
    client: httpx.AsyncClient,
    path: str,
    *,
    max_retries: int = 4,
) -> object:
    url = _with_api_key(f"{OPENDOTA_BASE}/{path.lstrip('/')}")

    for attempt in range(max_retries):
        await _throttle()

        try:
            response = await client.get(url, timeout=20.0)
        except httpx.RequestError as exc:
            # Transient network/VPN blip: back off and retry before giving up.
            if attempt < max_retries - 1:
                await asyncio.sleep(2**attempt + 1)
                continue
            raise OpenDotaError(f"OpenDota request failed: {exc}") from exc

        _record_rate_limit(response.headers)

        if response.status_code == 429:
            if attempt < max_retries - 1:
                retry_after = response.headers.get("retry-after")
                try:
                    delay = float(retry_after) if retry_after else 2**attempt + 1
                except ValueError:
                    delay = 2**attempt + 1
                await asyncio.sleep(delay)
                continue
            raise OpenDotaError(
                "OpenDota rate limit exceeded. Try again in a minute.",
                status_code=429,
            )

        if response.status_code == 404:
            raise OpenDotaError(
                "Player or resource not found on OpenDota.",
                status_code=404,
            )

        # Transient server-side errors (500/502/503/504): retry before failing.
        if response.status_code >= 500:
            if attempt < max_retries - 1:
                await asyncio.sleep(2**attempt + 1)
                continue
            raise OpenDotaError(
                f"OpenDota is temporarily unavailable (status {response.status_code}). "
                "Try again shortly.",
                status_code=502,
            )

        if response.status_code >= 400:
            raise OpenDotaError(
                f"OpenDota returned status {response.status_code}.",
                status_code=502,
            )

        return response.json()

    raise OpenDotaError("OpenDota rate limit exceeded. Try again shortly.", status_code=429)


def steam64_to_account_id(steam64: int) -> int:
    return steam64 - 76561197960265728


def normalize_account_id(raw: str) -> int:
    value = raw.strip()
    if not value.isdigit():
        raise ValueError("Account ID must be a numeric Steam32 ID or Steam64 ID.")

    numeric = int(value)
    if numeric > 76561197960265728:
        return steam64_to_account_id(numeric)
    return numeric
