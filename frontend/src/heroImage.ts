const STEAM_CDN =
  "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes";
const OPENDOTA_CDN = "https://www.opendota.com/assets/images/dota2/heroes";

function heroShortName(heroInternalName: string): string {
  return heroInternalName.replace("npc_dota_hero_", "");
}

export function getHeroImageUrls(heroInternalName: string): string[] {
  const shortName = heroShortName(heroInternalName);
  return [
    `${STEAM_CDN}/${shortName}.png`,
    `${OPENDOTA_CDN}/${shortName}.png`,
  ];
}

export function getHeroImageUrl(heroInternalName: string): string {
  return getHeroImageUrls(heroInternalName)[0];
}
