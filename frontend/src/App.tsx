import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  fetchHeroWinRate,
  fetchHeroes,
  fetchMatchups,
  fetchPlayer,
  fetchTopItems,
} from "./api";
import HeroPortrait from "./HeroPortrait";
import HeroSelect from "./HeroSelect";
import type { Hero, HeroWinRate, ItemStat, MatchupStat, PlayerProfile, SideStats } from "./types";

type ActiveView = "winrate" | "items" | "matchups" | null;

function formatLastPlayed(timestamp: number | null): string {
  if (!timestamp) {
    return "Unknown";
  }
  return new Date(timestamp * 1000).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function winRateTone(winRate: number): string {
  if (winRate >= 55) {
    return "good";
  }
  if (winRate <= 45) {
    return "bad";
  }
  return "neutral";
}

function SideBreakdown({
  label,
  tone,
  side,
}: {
  label: string;
  tone: "radiant" | "dire";
  side: SideStats;
}) {
  return (
    <article className={`side-card side-card-${tone}`}>
      <h3>{label}</h3>
      <p className={`side-win-rate ${winRateTone(side.win_rate)}`}>
        {side.win_rate}%
      </p>
      <dl className="side-stats">
        <div>
          <dt>Games</dt>
          <dd>{side.games}</dd>
        </div>
        <div>
          <dt>Wins</dt>
          <dd>{side.wins}</dd>
        </div>
        <div>
          <dt>Losses</dt>
          <dd>{side.losses}</dd>
        </div>
      </dl>
    </article>
  );
}

function MatchupList({
  title,
  tone,
  matchups,
}: {
  title: string;
  tone: "best" | "worst";
  matchups: MatchupStat[];
}) {
  if (matchups.length === 0) {
    return null;
  }

  return (
    <article className={`matchup-card matchup-card-${tone}`}>
      <h4>{title}</h4>
      <ol className="matchup-list">
        {matchups.map((matchup) => (
          <li key={matchup.hero_id} className="matchup-row">
            <HeroPortrait
              heroInternalName={matchup.hero_name}
              heroLocalizedName={matchup.hero_localized_name}
            />
            <div className="matchup-copy">
              <strong>{matchup.hero_localized_name}</strong>
              <span className="subtle">
                {matchup.games} games · {matchup.wins}W / {matchup.losses}L
              </span>
            </div>
            <span className={`item-win-rate ${winRateTone(matchup.win_rate)}`}>
              {matchup.win_rate}%
            </span>
          </li>
        ))}
      </ol>
    </article>
  );
}

function HeroAttributes({ hero }: { hero: Hero }) {
  const rows: {
    attr: "str" | "agi" | "int";
    label: string;
    base: number;
    gain: number;
  }[] = [
    { attr: "str", label: "STR", base: hero.base_str, gain: hero.str_gain },
    { attr: "agi", label: "AGI", base: hero.base_agi, gain: hero.agi_gain },
    { attr: "int", label: "INT", base: hero.base_int, gain: hero.int_gain },
  ];

  const showGain = hero.primary_attr !== "all";

  return (
    <div className="hero-attrs">
      {rows.map((row) => {
        const isPrimary = hero.primary_attr === row.attr;
        return (
          <div
            key={row.attr}
            className={`hero-attr attr-${row.attr}${
              isPrimary ? " is-primary" : ""
            }`}
          >
            <span className="hero-attr-label">{row.label}</span>
            <span className="hero-attr-value">{row.base}</span>
            {showGain && isPrimary ? (
              <span className="hero-attr-gain">+{row.gain.toFixed(1)}</span>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

export default function App() {
  const [heroes, setHeroes] = useState<Hero[]>([]);
  const [accountId, setAccountId] = useState("");
  const [heroId, setHeroId] = useState("");
  const [bootLoading, setBootLoading] = useState(true);
  const [activeView, setActiveView] = useState<ActiveView>(null);
  const [contentLoading, setContentLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [viewError, setViewError] = useState<string | null>(null);
  const [player, setPlayer] = useState<PlayerProfile | null>(null);
  const [stats, setStats] = useState<HeroWinRate | null>(null);
  const [topItems, setTopItems] = useState<ItemStat[]>([]);
  const [itemsSampleSize, setItemsSampleSize] = useState(0);
  const [bestMatchups, setBestMatchups] = useState<MatchupStat[]>([]);
  const [worstMatchups, setWorstMatchups] = useState<MatchupStat[]>([]);
  const [matchupsSampleSize, setMatchupsSampleSize] = useState(0);

  useEffect(() => {
    fetchHeroes()
      .then(setHeroes)
      .catch(() => setError("Could not load hero list. Is the backend running?"))
      .finally(() => setBootLoading(false));
  }, []);

  const selectedHero = useMemo(
    () => heroes.find((hero) => String(hero.id) === heroId) ?? null,
    [heroes, heroId],
  );

  const formDisabled = bootLoading || contentLoading;

  const heroDisplay = useMemo(() => {
    if (stats) {
      return {
        heroName: stats.hero_name,
        heroLocalizedName: stats.hero_localized_name,
        accountId: stats.account_id,
      };
    }
    if (selectedHero && accountId.trim()) {
      return {
        heroName: selectedHero.name,
        heroLocalizedName: selectedHero.localized_name,
        accountId: Number(accountId.trim()),
      };
    }
    return null;
  }, [stats, selectedHero, accountId]);

  function getSelection() {
    if (!accountId.trim() || !heroId || !selectedHero) {
      setError("Enter your Dota account ID and pick a hero.");
      return null;
    }
    return {
      accountId: accountId.trim(),
      heroId: Number(heroId),
    };
  }

  async function loadPlayer(account: string) {
    // The Steam name/avatar are cosmetic. OpenDota's /players endpoint can be
    // flaky (occasional 500s), so never let a profile failure break the actual
    // stats — just fall back to no profile.
    try {
      const profile = await fetchPlayer(account);
      setPlayer(profile);
      return profile;
    } catch {
      setPlayer(null);
      return null;
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setViewError(null);

    const selection = getSelection();
    if (!selection) {
      return;
    }

    setActiveView("winrate");
    setContentLoading(true);
    setStats(null);

    try {
      const [profile, winRate] = await Promise.all([
        loadPlayer(selection.accountId),
        fetchHeroWinRate(selection.accountId, selection.heroId),
      ]);
      setPlayer(profile);
      setStats(winRate);
    } catch (submitError) {
      setActiveView(null);
      setPlayer(null);
      setStats(null);
      const message =
        submitError instanceof Error
          ? submitError.message
          : "Something went wrong while fetching stats.";
      setError(message);
    } finally {
      setContentLoading(false);
    }
  }

  async function handleItemsClick() {
    setError(null);
    setViewError(null);

    const selection = getSelection();
    if (!selection) {
      return;
    }

    setActiveView("items");
    setContentLoading(true);
    setTopItems([]);
    setItemsSampleSize(0);

    try {
      await loadPlayer(selection.accountId);
      const itemStats = await fetchTopItems(selection.accountId, selection.heroId);
      setTopItems(itemStats.top_items);
      setItemsSampleSize(itemStats.items_sample_size);
    } catch (itemsFetchError) {
      const message =
        itemsFetchError instanceof Error
          ? itemsFetchError.message
          : "Could not load item stats.";
      setViewError(message);
    } finally {
      setContentLoading(false);
    }
  }

  async function handleMatchupsClick() {
    setError(null);
    setViewError(null);

    const selection = getSelection();
    if (!selection) {
      return;
    }

    setActiveView("matchups");
    setContentLoading(true);
    setBestMatchups([]);
    setWorstMatchups([]);
    setMatchupsSampleSize(0);

    try {
      await loadPlayer(selection.accountId);
      const matchupStats = await fetchMatchups(selection.accountId, selection.heroId);
      setBestMatchups(matchupStats.best_against);
      setWorstMatchups(matchupStats.worst_against);
      setMatchupsSampleSize(matchupStats.sample_size);
    } catch (matchupsFetchError) {
      const message =
        matchupsFetchError instanceof Error
          ? matchupsFetchError.message
          : "Could not load matchup stats.";
      setViewError(message);
    } finally {
      setContentLoading(false);
    }
  }

  return (
    <div className="page">
      <header className="hero-panel">
        <p className="eyebrow">OpenDota + TypeScript + Python</p>
        <h1>Dota Hero Winrate</h1>
        <p className="lede">
          Look up your win rate on any hero using the{" "}
          <a href="https://docs.opendota.com/" target="_blank" rel="noreferrer">
            OpenDota API
          </a>
          .
        </p>
      </header>

      <main className="card">
        <form className="lookup-form" onSubmit={handleSubmit}>
          <label>
            Dota account ID
            <input
              type="text"
              inputMode="numeric"
              placeholder="Steam32 or Steam64 ID"
              value={accountId}
              onChange={(event) => setAccountId(event.target.value)}
              disabled={formDisabled}
            />
            <span className="hint">
              Use your Steam32 account ID, or paste a Steam64 profile ID.
            </span>
          </label>

          <div className="field">
            <span className="field-label">Hero</span>
            <HeroSelect
              heroes={heroes}
              value={heroId}
              onChange={setHeroId}
              disabled={formDisabled || heroes.length === 0}
              loading={bootLoading}
            />
          </div>

          <div className="action-buttons">
            <button type="submit" disabled={formDisabled}>
              {contentLoading && activeView === "winrate"
                ? "Fetching..."
                : "Get win rate"}
            </button>
            <button
              type="button"
              disabled={formDisabled}
              onClick={handleItemsClick}
            >
              {contentLoading && activeView === "items"
                ? "Fetching..."
                : "Get Item Information"}
            </button>
            <button
              type="button"
              disabled={formDisabled}
              onClick={handleMatchupsClick}
            >
              {contentLoading && activeView === "matchups"
                ? "Fetching..."
                : "Get vs Hero Information"}
            </button>
          </div>
        </form>

        {error ? <p className="error">{error}</p> : null}

        {activeView && heroDisplay ? (
          <section className="results">
            <div className="results-layout">
              <div className="hero-media">
                <HeroPortrait
                  heroInternalName={heroDisplay.heroName}
                  heroLocalizedName={heroDisplay.heroLocalizedName}
                />
                {selectedHero ? <HeroAttributes hero={selectedHero} /> : null}
              </div>

              <div className="results-body">
                <div className="player-row">
                  {player?.avatarfull ? (
                    <img src={player.avatarfull} alt="" className="avatar" />
                  ) : null}
                  <div>
                    <h2>
                      {player?.personaname ?? `Player ${heroDisplay.accountId}`}
                    </h2>
                    <p className="subtle">{heroDisplay.heroLocalizedName}</p>
                  </div>
                </div>

                {contentLoading ? (
                  <p className="hint items-loading">Loading...</p>
                ) : viewError ? (
                  <p className="error">{viewError}</p>
                ) : activeView === "winrate" && stats ? (
                  <>
                    <div className={`win-rate ${winRateTone(stats.win_rate)}`}>
                      <span className="win-rate-value">{stats.win_rate}%</span>
                      <span className="win-rate-label">Win rate</span>
                    </div>

                    <dl className="stats-grid">
                      <div>
                        <dt>Games</dt>
                        <dd>{stats.games}</dd>
                      </div>
                      <div>
                        <dt>Wins</dt>
                        <dd>{stats.wins}</dd>
                      </div>
                      <div>
                        <dt>Losses</dt>
                        <dd>{stats.losses}</dd>
                      </div>
                      <div>
                        <dt>Last played</dt>
                        <dd>{formatLastPlayed(stats.last_played)}</dd>
                      </div>
                    </dl>

                    <section className="side-section">
                      <h3 className="side-section-title">Games by side</h3>
                      <div className="side-grid">
                        <SideBreakdown
                          label="Radiant"
                          tone="radiant"
                          side={stats.radiant}
                        />
                        <SideBreakdown label="Dire" tone="dire" side={stats.dire} />
                      </div>
                    </section>
                  </>
                ) : activeView === "items" ? (
                  <section className="items-section items-section-inline">
                    <div className="items-section-header">
                      <h3 className="side-section-title">Top core items</h3>
                      {itemsSampleSize > 0 ? (
                        <p className="hint">
                          Most built core items from your last {itemsSampleSize} games on
                          this hero (starter items excluded).
                        </p>
                      ) : (
                        <p className="hint">
                          Most built core items from your recent games on this hero
                          (starter items excluded).
                        </p>
                      )}
                    </div>

                    {topItems.length > 0 ? (
                      <ol className="item-list">
                        {topItems.map((item, index) => (
                          <li key={item.item_id} className="item-row">
                            <span className="item-rank">{index + 1}</span>
                            <img
                              src={item.item_image}
                              alt={item.item_name}
                              className="item-icon"
                              referrerPolicy="no-referrer"
                            />
                            <div className="item-copy">
                              <strong>{item.item_name}</strong>
                              <span className="subtle">
                                {item.games} games · {item.wins}W / {item.losses}L
                              </span>
                            </div>
                            <span
                              className={`item-win-rate ${winRateTone(item.win_rate)}`}
                            >
                              {item.win_rate}%
                            </span>
                          </li>
                        ))}
                      </ol>
                    ) : (
                      <p className="hint">
                        No core item data found across your games on this hero.
                      </p>
                    )}
                  </section>
                ) : activeView === "matchups" ? (
                  <section className="matchups-section matchups-section-inline">
                    <div className="items-section-header">
                      <h3 className="side-section-title">Enemy hero matchups</h3>
                      <p className="hint">
                        Best and worst enemy heroes from{" "}
                        {matchupsSampleSize > 0
                          ? `your last ${matchupsSampleSize} games`
                          : "your recent games"}{" "}
                        on this hero (min. 3 games each).
                      </p>
                    </div>

                    <div className="matchups-grid">
                      <MatchupList
                        title="Best matchups"
                        tone="best"
                        matchups={bestMatchups}
                      />
                      <MatchupList
                        title="Worst matchups"
                        tone="worst"
                        matchups={worstMatchups}
                      />
                    </div>
                  </section>
                ) : null}
              </div>
            </div>
          </section>
        ) : null}
      </main>
    </div>
  );
}
