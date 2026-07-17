import { useEffect, useMemo, useRef, useState } from "react";
import { getHeroImageUrls } from "./heroImage";
import type { Hero, HeroAttribute } from "./types";

interface HeroSelectProps {
  heroes: Hero[];
  value: string;
  onChange: (heroId: string) => void;
  disabled?: boolean;
  loading?: boolean;
}

const ATTRIBUTE_ORDER: HeroAttribute[] = ["str", "agi", "int", "all"];

const ATTRIBUTE_LABELS: Record<HeroAttribute, string> = {
  str: "Strength",
  agi: "Agility",
  int: "Intelligence",
  all: "Universal",
};

function HeroThumb({ hero }: { hero: Hero }) {
  const candidates = getHeroImageUrls(hero.name);
  const [index, setIndex] = useState(0);
  const [failed, setFailed] = useState(false);

  if (failed) {
    return <span className="hero-thumb hero-thumb-fallback" aria-hidden="true" />;
  }

  return (
    <img
      src={candidates[index]}
      alt=""
      className="hero-thumb"
      referrerPolicy="no-referrer"
      onError={() => {
        if (index < candidates.length - 1) {
          setIndex((current) => current + 1);
          return;
        }
        setFailed(true);
      }}
    />
  );
}

export default function HeroSelect({
  heroes,
  value,
  onChange,
  disabled = false,
  loading = false,
}: HeroSelectProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);

  const selectedHero = useMemo(
    () => heroes.find((hero) => String(hero.id) === value) ?? null,
    [heroes, value],
  );

  const grouped = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const matches = needle
      ? heroes.filter((hero) =>
          hero.localized_name.toLowerCase().includes(needle),
        )
      : heroes;

    return ATTRIBUTE_ORDER.map((attr) => ({
      attr,
      heroes: matches
        .filter((hero) => hero.primary_attr === attr)
        .sort((a, b) => a.localized_name.localeCompare(b.localized_name)),
    })).filter((group) => group.heroes.length > 0);
  }, [heroes, query]);

  useEffect(() => {
    if (!open) {
      return;
    }
    function handlePointerDown(event: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setOpen(false);
      }
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  useEffect(() => {
    if (!open) {
      setQuery("");
    }
  }, [open]);

  function handleSelect(heroId: number) {
    onChange(String(heroId));
    setOpen(false);
  }

  return (
    <div className="hero-select" ref={containerRef}>
      <button
        type="button"
        className="hero-select-trigger"
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        {selectedHero ? (
          <span className="hero-select-value">
            <HeroThumb hero={selectedHero} />
            <span>{selectedHero.localized_name}</span>
          </span>
        ) : (
          <span className="hero-select-placeholder">
            {loading ? "Loading heroes..." : "Select a hero"}
          </span>
        )}
        <span className="hero-select-caret" aria-hidden="true">
          ▾
        </span>
      </button>

      {open ? (
        <div className="hero-select-panel" role="listbox">
          <div className="hero-select-search">
            <input
              type="text"
              autoFocus
              placeholder="Search heroes..."
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>

          <div className="hero-select-options">
            {grouped.length === 0 ? (
              <p className="hero-select-empty">No heroes match your search.</p>
            ) : (
              grouped.map((group) => (
                <div key={group.attr} className="hero-select-group">
                  <p className={`hero-select-group-title attr-${group.attr}`}>
                    {ATTRIBUTE_LABELS[group.attr]}
                  </p>
                  {group.heroes.map((hero) => {
                    const isSelected = String(hero.id) === value;
                    return (
                      <button
                        key={hero.id}
                        type="button"
                        role="option"
                        aria-selected={isSelected}
                        className={`hero-select-option${
                          isSelected ? " is-selected" : ""
                        }`}
                        onClick={() => handleSelect(hero.id)}
                      >
                        <HeroThumb hero={hero} />
                        <span>{hero.localized_name}</span>
                      </button>
                    );
                  })}
                </div>
              ))
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}
