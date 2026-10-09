// The in-app How To guides are the Markdown files in docs/, bundled as text at build time: one source for GitHub and the app, so they cannot drift apart.
import liveDesk from "../../../docs/LIVE_DESK_GUIDE.md?raw";
import overview from "../../../docs/MARKET_MAKING_GAME/OVERVIEW.md?raw";
import probability from "../../../docs/MARKET_MAKING_GAME/PROBABILITY_MARKETS.md?raw";
import world from "../../../docs/MARKET_MAKING_GAME/WORLD_MARKETS.md?raw";

export type GuideId = "desk" | "game" | "world" | "probability";
export interface Guide { id: GuideId; tab: string; title: string; file: string; source: string }

export const GUIDES: Record<GuideId, Guide> = {
  desk: { id: "desk", tab: "Live Desk", title: "Live Desk guide", file: "docs/LIVE_DESK_GUIDE.md", source: liveDesk },
  game: { id: "game", tab: "Overview", title: "Market Making Game: how to play well", file: "docs/MARKET_MAKING_GAME/OVERVIEW.md", source: overview },
  world: { id: "world", tab: "World markets", title: "World markets", file: "docs/MARKET_MAKING_GAME/WORLD_MARKETS.md", source: world },
  probability: { id: "probability", tab: "Probability markets", title: "Probability markets", file: "docs/MARKET_MAKING_GAME/PROBABILITY_MARKETS.md", source: probability },
};

/** The guides opened from each area, in tab order. */
export const DESK_GUIDES: GuideId[] = ["desk"];
export const GAME_GUIDES: GuideId[] = ["game", "world", "probability"];

/** Which guide (and anchor) a relative link in a guide points to, when it is one of the guides; null for any other file. */
export function resolveLink(href: string, from: GuideId): { guide: GuideId; anchor: string | null } | null {
  const [path, anchor = null] = href.split("#") as [string, string | undefined];
  if (!path) return { guide: from, anchor };
  if (/^[a-z]+:/i.test(path)) return null;
  const base = path.split("/").pop()!;
  const hit = (Object.values(GUIDES) as Guide[]).find((g) => g.file.endsWith(`/${base}`) && (base !== "OVERVIEW.md" || g.id === "game"));
  return hit ? { guide: hit.id, anchor } : null;
}
