import { useState } from "react";
import { getHeroImageUrls } from "./heroImage";

interface HeroPortraitProps {
  heroInternalName: string;
  heroLocalizedName: string;
}

export default function HeroPortrait({
  heroInternalName,
  heroLocalizedName,
}: HeroPortraitProps) {
  const candidates = getHeroImageUrls(heroInternalName);
  const [index, setIndex] = useState(0);
  const [failed, setFailed] = useState(false);

  if (failed) {
    return (
      <div className="hero-portrait hero-portrait-fallback" aria-hidden="true">
        ?
      </div>
    );
  }

  return (
    <img
      src={candidates[index]}
      alt={heroLocalizedName}
      className="hero-portrait"
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
