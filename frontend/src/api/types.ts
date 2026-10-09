// The public contract with the Python engine: plain-data views from episodes/views.py. Nothing here is computed in the browser.
// Fields the contract deliberately does not carry (informed flags, posteriors, seeds, truth, future moves, checkpoint answers) have no type here either.

export type Kind = "quote" | "rfq" | "checkpoint" | "hedge" | "position" | "overnight" | "rehedge";
export type Rating = "sound" | "defensible" | "poor" | "error";
export type Action = "pays" | "receives"; // what the CLIENT does: pays fixed / receives fixed
export type SideWord = "pay" | "receive"; // what the dealer does

export interface EpisodeMeta { id: string; title: string; level: number; round: number; rounds: number; round_title: string }
export interface Header { title: string; round: number; rounds: number; round_title: string; briefing: string | null; notes: string[]; show_risk_card: boolean }
export interface RiskCardFactor { name: string; label: string; normal_daily_vol: number; vol_unit: string; loadings: { tenor: number; bp_per_unit: number }[] | null }
export interface RiskCard { title: string; regime_vol: number; step_days: number; factors: RiskCardFactor[] }

export interface CurvePoint { tenor: number; mid: number }
export interface FocusQuote { tenor: number; mid: number; bid: number; offer: number; dv01_per_m: number }
export interface LadderRow { tenor: number; mid: number; bid: number; offer: number; dv01_per_m: number; cost_bp: number }
export interface ProductLine {
  code: string; kind: "future" | "bond"; label: string; unit: string; dv01_per_unit: number; cost_per_unit: number; info: string;
  price?: number; half_spread_ticks?: number;                        // futures
  clean?: number; yield?: number; asw_bp?: number; half_spread?: number; // the CTD bond
}
export interface Market { mode: "single" | "ladder"; curve: CurvePoint[]; focus: FocusQuote | null; ladder: LadderRow[]; products: ProductLine[] }

export interface SwapRow { label: string; side: SideWord; notional: number; tenor: number; rate: number }
export interface HedgeRow { code: string; kind: "future" | "bond"; quantity: number }
export interface Book {
  swaps: SwapRow[]; hedges: HedgeRow[]; dv01: number; limit_dv01: number; focus_tenor: number;
  buckets: { tenor: number; dv01: number }[] | null; slope: { exposure: number; limit: number | null } | null; curvature: number | null;
  curve_position: number | null; spreads: { swap_spread: number; fut_basis: number } | null; pnl_so_far: number;
}

export interface Research { text: string; reliability: number; steps_total: number; steps_left: number; total_bp: number; remaining_bp: number; per_step_bp: number; expected_per_step_bp: number }
export interface Conditions {
  volatility: string; liquidity: string; flow: string; swap_cost: { multiplier: number; depth_dv01: number | null } | null;
  desk_expectation: string | null; research: Research | null;
  named_clients: { name: string; description: string; observations: { side: "paid" | "received"; move_bp: number }[] }[];
  calendar: { vol_mult: number } | null; extra_lines: string[];
}
export interface Inquiry { name: string | null; ctype: string; description: string; short: string; action: Action; notional: number; tenor: number; dv01: number }
export interface LastInquiry { short: string; action: Action; notional: number; tenor: number; outcome: string }
export interface InputSpec {
  type: "quote" | "rfq" | "number" | "hedge" | "position"; hint: string; unit?: string | null;
  swap_tenors?: number[]; products?: string[]; can_flatten?: boolean; can_switch?: boolean; can_target?: boolean;
}

export interface ObservationView {
  schema: number; kind: Kind; episode: EpisodeMeta; header: Header; risk_card: RiskCard;
  market: Market | null; book: Book | null; conditions: Conditions | null; clients_today: string[];
  inquiry: Inquiry | null; last_inquiry: LastInquiry | null; hedge_menu: { tenor: number; dv01_per_m: number; cost_bp: number }[] | null;
  overnight: { time_pnl: number } | null; next_step: { trading_hours: number } | null;
  checkpoint: { intro: string; with_screen: boolean; inquiry: { action: Action; notional: number; tenor: number } | null; prompt: string; note: string } | null;
  prompt: string; input: InputSpec;
}

// ---- decisions (the encoded form the API accepts)
export type EncodedTrade =
  | { kind: "swap"; tenor: number; side: SideWord; notional: number }
  | { kind: "future"; code: string; contracts: number }
  | { kind: "bond"; code: string; face: number };
export type EncodedDecision =
  | { type: "quote"; bid: number; offer: number }
  | { type: "rfq"; level: number | null }
  | { type: "checkpoint"; raw: string }
  | { type: "hedge"; label: string; trades: EncodedTrade[] };

// ---- results
export type ResultEvent =
  | { type: "client_arrives"; name: string | null; short: string; description: string; action: Action; notional: number; your_rate: number; street_rate: number }
  | { type: "passed" }
  | { type: "fill"; filled: false; p_win: number }
  | { type: "fill"; filled: true; p_win: number; action: Action; notional: number; tenor: number; rate: number; dealer_side: SideWord; edge: number }
  | { type: "checkpoint_recorded" }
  | { type: "checkpoint_grade"; correct: boolean; feedback: string; expected: string; label: string | null }
  | { type: "flat_book" }
  | { type: "hedge_trade"; kind: "swap"; side: SideWord; notional: number; tenor: number; rate: number; cost: number }
  | { type: "hedge_trade"; kind: "future"; code: string; contracts: number; cost: number }
  | { type: "hedge_trade"; kind: "bond"; code: string; face: number; cost: number }
  | { type: "skipped_trade"; description: string; threshold_pct: number }
  | { type: "no_trade" }
  | { type: "overnight"; causes: { name: string; amount: number }[] }
  | { type: "market"; focus_tenor: number; move_bp: number; release: boolean; tenor_moves: { tenor: number; bp: number }[]; factor_moves: { name: string; value: number }[];
      first_order: { name: string; pnl: number }[]; first_total: number; full_revaluation: number; convexity_cross: number }
  | { type: "round_pnl"; round_pnl: number; total_pnl: number };

export interface AssessmentView {
  kind: string; rating: Rating; reasons: string[]; expected_pnl: number; variance: number;
  table: { label: string; expected: number; sigma: number; rating: Rating }[];
  metrics: Record<string, unknown> & { dv01_before?: number; dv01_after?: number; exposures?: Record<string, number>; cost?: number; sigma?: number };
}
export interface StepResultView { schema: number; events: ResultEvent[]; assessment: AssessmentView | null; grade: { correct: boolean; feedback: string; expected: string } | null; done: boolean }

export interface PathStats { mean: number; p05: number; p95: number; samples: number[] }

export interface DebriefView {
  schema: number;
  decisions: { round: number; kind: string; rating: Rating; headline: string; reasons: string[] }[];
  calculation_checks: { correct: boolean; expected: string }[];
  outcome: {
    by_cause: { cause: string; amount: number }[]; total: number; exposures_by_round: { round: number; level: number; slope: number }[] | null;
    spread_note: { swap_spread: number; fut_basis: number } | null; risk_left: { dv01: number; flatten_cost: number };
  };
  luck: { label: string; expected_pnl: number; realised_pnl: number; luck: number; sigma_units: number | null };
  clients: { round: number; name: string | null; ctype: string; action: Action; notional: number; tenor: number | null; informed: boolean; traded: boolean }[];
  evidence_vs_truth: { name: string; posteriors: number[]; informed: boolean }[] | null;
  view_truth: { right: boolean; reliability: number } | null;
  counterfactuals: { policies: { name: string; pnl: number; ratings: Rating[] }[]; you: number } | null;
  market_paths: { label: string; n: number; yours: PathStats; rank: number; reference: PathStats | null } | null;
}

// ---- server state
export interface PendingState { observation: ObservationView; decision: EncodedDecision; result: StepResultView }
export interface DeskState { id: string; phase: "awaiting" | "settled" | "done"; episode: EpisodeMeta; observation: ObservationView | null; pending: PendingState | null }
export type QKind = "conceptual" | "calculation";
export interface CatalogueItem { id: string; difficulty: 1 | 2 | 3; curated: boolean; kind: QKind }
export interface CatalogueSkill { id: string; title: string; planned: boolean; prereqs: string[]; sources: number; curated: number; difficulties: Record<string, number>; kinds: Record<QKind, number>; items: CatalogueItem[] }
export interface CatalogueTrack { id: string; title: string; sources: number; skills: CatalogueSkill[] }
export interface Catalogue { episodes: { id: string; level: number; skill: string; title: string }[]; train: { tracks: CatalogueTrack[]; sources: number } }
export interface SavedSession { id: string; saved: string; level: number; episode: string; title: string; rounds: number; decisions: number; ratings: Record<Rating, number>; pnl: number; luck: number; checkpoints: number; checkpoints_correct: number }

export interface LiveSession { id: string; phase: "awaiting" | "settled"; episode: DeskState["episode"]; started: string; decisions: number; in_history: boolean }

// ---- TRAIN: the QuestionSession views (plain data; no answers until they are due)
export interface ChoicePartView { index: number; kind: "choice"; prompt: string; options: string[] }
export interface NumericPartView { index: number; kind: "numeric"; prompt: string; unit: string; unit_label: string; note: string; bare_scale: number; entry_hint: string }
export type PartView = ChoicePartView | NumericPartView;
export interface PartResult { correct: boolean; skipped: boolean; status: "correct" | "incorrect" | "skipped"; feedback: string; expected: string; detail: string; why: string }
export type DonePart = PartView & { submitted: string; result: PartResult };
export interface QuestionView {
  id: string; template_id: string; skill: string; skill_title: string; track: string; track_title: string; difficulty: 1 | 2 | 3; difficulty_label: string; kind: QKind; curated: boolean;
  stem: string; parts_total: number; parts_done: DonePart[]; current: PartView | null; solution: string[] | null; question_correct: boolean | null;
}
export interface TrainState {
  id: string; mode: "focused" | "mixed" | "single" | "replay"; label: string; selection: Record<string, unknown>; started: string; index: number; total: number;
  phase: "answering" | "feedback" | "done"; ended_early: boolean; parts_correct: number; parts_answered: number; question: QuestionView | null;
}
export interface TrainSummary {
  parts_total: number; parts_correct: number; questions_planned: number; ended_early: boolean; missed: string[];
  questions: { id: string; skill: string; skill_title: string; difficulty: number; kind: QKind; parts_correct: number; parts_answered: number; parts_total: number; correct: boolean }[];
  by_skill: { skill: string; title: string; correct: number; total: number }[];
}
export interface TrainStart { tracks?: string[]; skills?: string[]; difficulty?: number | null; max_difficulty?: number | null; kind?: QKind | null; count?: number; seed?: number | null; template_id?: string; ids?: string[]; label?: string }
export interface PracticeSaved { id: string; started: string; mode: string; label: string; finished: boolean; ended_early: boolean; questions: number; parts_total: number; parts_correct: number }
