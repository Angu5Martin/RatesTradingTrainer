// The MARKET MAKING GAME's wire types: what /api/mmgame returns. Public information only (see src/rates_trainer/mmgame/game.py).

export type Status = "active" | "shocked" | "paused" | "resolved" | "upcoming";
export type Category = "experiment" | "information" | "resolution";

export interface Trade {
  n: number; round: number; phase: "A" | "B"; market: string; bot: string; type: string | null; me: "buy" | "sell"; qty: number; price: number;
  position_after: number; bid: number; offer: number;
  edge?: number; fair?: number; stale?: boolean;        // edge: shown by the coach at level 1 (probability markets) and for every trade once its market has resolved
}
export interface Note { id: string; round: number; category: Category; headline: string; text: string }
export interface QuoteView { bid: number; offer: number; size: number; set_round: number; stale: boolean }

export interface MarketView {
  id: string; title: string; kind: "probability" | "world"; category: string; unit: string; tick: number; decimals: number; lot_value: number;
  range: [number, number]; status: Status; opens_at: number; resolves_at: number; limit: number; notes: Note[];
  opens_in?: number;
  question?: string; rules?: string[]; resolution_rule?: string; position?: number; quote?: QuoteView | null; trades?: Trade[]; cash?: number;
  possible?: [number, number]; remaining?: number; avg_price?: number | null; open_pnl?: number; closed?: { bid: boolean; offer: boolean }; risk?: number;
  resolved_round?: number; settle?: number; position_at_settlement?: number; pnl?: number; source?: string | null; as_of?: string | null; resolution_text?: string;
}

export interface Portfolio {
  pnl_settled: number; pnl_open: number; pnl_total: number; gross_lots: number; net_lots: number; risk_used: number; risk_budget: number | null; trades: number;
  open_markets: number; resolved_markets: number;
}

export type GameEvent =
  | { type: "trade"; market: string; trade: Trade }
  | { type: "shock"; id: string; round: number; category: Category; headline: string; text: string; markets: string[] }
  | { type: "resolved"; market: string; title: string; settle: number; pnl: number; position: number }
  | { type: "opened"; market: string; title: string };
export interface Report { round: number; events: GameEvent[] }

export interface GameState {
  id: string; level: number; level_name: string; round: number; rounds: number; phase: "quoting" | "done"; started: string; mix: string; coach: boolean;
  size_max: number; limit: number; markets: MarketView[]; portfolio: Portfolio;
  shocks: { id: string; round: number; category: Category; headline: string; text: string; markets: string[] }[];
  last_report: Report | null; counterparties: { id: string; type: string | null }[]; convention: string;
}

export interface LevelInfo {
  level: number; name: string; blurb: string; markets: [number, number, number]; rounds: number; limit: number; size_max: number; risk_budget: number | null;
  shocks: [number, number]; coach: boolean; late_markets: number; linked: number;
}
export interface GameSummary { id: string; level: number; level_name: string; started: string; round: number; rounds: number; markets: number; done: boolean; pnl: number; trades: number }
export interface GameList { levels: LevelInfo[]; mixes: string[]; games: GameSummary[] }
export interface StartBody { level: number; markets?: number | null; mix?: string; seed?: number | null; coach?: boolean | null }
export interface QuoteBody { market: string; bid: number | string; offer: number | string; size: number }

export interface DebriefTrade {
  n: number; round: number; phase: string; bot: string; informed: boolean; me: "buy" | "sell"; qty: number; price: number; fair: number; bid: number; offer: number; stale: boolean;
  edge: number; result: number; cause: string; verdict: string; position_after: number;
}
export interface DebriefQuote { round: number; bid: number; offer: number; size: number; fair: number; error_sd: number; half_spread_sd: number; position: number; verdict: string; spread: string }
export interface DebriefShock {
  id: string; round: number; headline: string; text: string; position: number; fair_before: number; fair_after: number; fair_moved_sd: number; mark_impact: number;
  quote_was_off_by_sd: number | null; requoted_at_once: boolean; requote_mid_error_sd: number | null;
}
export interface DebriefMarket {
  id: string; title: string; kind: string; category: string; unit: string; lot_value: number; question: string; resolution_rule: string; rules_at_resolution: string[];
  source: string | null; as_of: string | null; settle: number; settle_text: string; opens_at: number; resolved_round: number; position_at_settlement: number; final_fair: number;
  trades: DebriefTrade[]; quotes: DebriefQuote[]; shocks: DebriefShock[];
  pnl: { total: number; spread_capture: number; mispricing: number; edge: number; adverse_selection: number; news_drift: number; settlement_luck: number };
}
export interface Debrief {
  game: GameSummary; seed: number; level: number; mix: string;
  totals: { pnl: number; spread_capture: number; mispricing: number; decision_edge: number; adverse_selection: number; decision_result: number; news_drift: number; settlement_luck: number; luck: number };
  trade_causes: Record<string, number>; markets: DebriefMarket[];
  shocks: GameState["shocks"]; shock_plan: { id: string; round: number; kind: string; category: string; shift_sd: number }[];
  counterparties: { id: string; personality: string; label: string; description: string; trades: number; lots: number; my_result: number; edge_given: number }[];
  decisions: { market: string; round: number; kind: string; text: string }[]; convention: string;
}
