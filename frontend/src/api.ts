import type {
  Hero,
  HeroWinRate,
  MatchupsResponse,
  PlayerProfile,
  TopItemsResponse,
} from "./types";

async function readError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: string };
    if (typeof payload.detail === "string") {
      return payload.detail;
    }
  } catch {
    // Fall through to generic message.
  }
  return `Request failed with status ${response.status}.`;
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  return (await response.json()) as T;
}

export function fetchHeroes(): Promise<Hero[]> {
  return getJson<Hero[]>("/api/heroes");
}

export function fetchPlayer(accountId: string): Promise<PlayerProfile> {
  return getJson<PlayerProfile>(`/api/players/${encodeURIComponent(accountId)}`);
}

export function fetchHeroWinRate(
  accountId: string,
  heroId: number,
): Promise<HeroWinRate> {
  const params = new URLSearchParams({
    account_id: accountId.trim(),
    hero_id: String(heroId),
  });
  return getJson<HeroWinRate>(`/api/winrate?${params.toString()}`);
}

export function fetchTopItems(
  accountId: string,
  heroId: number,
): Promise<TopItemsResponse> {
  const params = new URLSearchParams({
    account_id: accountId.trim(),
    hero_id: String(heroId),
  });
  return getJson<TopItemsResponse>(`/api/top-items?${params.toString()}`);
}

export function fetchMatchups(
  accountId: string,
  heroId: number,
): Promise<MatchupsResponse> {
  const params = new URLSearchParams({
    account_id: accountId.trim(),
    hero_id: String(heroId),
  });
  return getJson<MatchupsResponse>(`/api/matchups?${params.toString()}`);
}
