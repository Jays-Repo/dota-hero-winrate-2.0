export interface Hero {
  id: number;
  name: string;
  localized_name: string;
}

export interface SideStats {
  games: number;
  wins: number;
  losses: number;
  win_rate: number;
}

export interface ItemStat {
  item_id: number;
  item_key: string;
  item_name: string;
  item_image: string;
  games: number;
  wins: number;
  losses: number;
  win_rate: number;
}

export interface HeroWinRate {
  account_id: number;
  hero_id: number;
  hero_name: string;
  hero_localized_name: string;
  games: number;
  wins: number;
  losses: number;
  win_rate: number;
  last_played: number | null;
  radiant: SideStats;
  dire: SideStats;
}

export interface TopItemsResponse {
  account_id: number;
  hero_id: number;
  top_items: ItemStat[];
  items_sample_size: number;
}

export interface MatchupStat {
  hero_id: number;
  hero_name: string;
  hero_localized_name: string;
  games: number;
  wins: number;
  losses: number;
  win_rate: number;
}

export interface MatchupsResponse {
  account_id: number;
  hero_id: number;
  best_against: MatchupStat[];
  worst_against: MatchupStat[];
  sample_size: number;
}

export interface HeroAnalysisResponse {
  account_id: number;
  hero_id: number;
  top_items: ItemStat[];
  items_sample_size: number;
  best_against: MatchupStat[];
  worst_against: MatchupStat[];
}

export interface PlayerProfile {
  account_id: number;
  personaname: string | null;
  avatarfull: string | null;
  profileurl: string | null;
}
