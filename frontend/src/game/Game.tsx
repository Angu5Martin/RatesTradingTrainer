import { useCallback, useEffect, useState } from "react";
import { GuideSheet } from "../guide/GuideSheet";
import { GAME_GUIDES, type GuideId } from "../guide/guides";
import { Debrief } from "./Debrief";
import { Setup } from "./Setup";
import { Table } from "./Table";
import { rememberedGame, useGame } from "./store";

/** MARKET MAKING GAME: the lobby, the table, and the debrief. A reload lands back on the same table (the server replays the saved game).
 *  The How To guides open over whichever screen is showing; nothing underneath is unmounted, so quotes being typed and selections survive. */
export function Game() {
  const s = useGame();
  const [guide, setGuide] = useState<{ id: GuideId; anchor?: string } | null>(null);
  const closeGuide = useCallback(() => setGuide(null), []);
  useEffect(() => {
    const id = rememberedGame();
    if (id && useGame.getState().state === null && !useGame.getState().busy) void useGame.getState().resume(id);
  }, []);
  const open = () => setGuide({ id: "game" });
  const screen = s.state && s.state.phase === "done" ? <Debrief onGuide={() => setGuide({ id: "game", anchor: "reading-the-debrief" })} /> : s.state ? <Table onGuide={open} /> : <Setup onGuide={open} />;
  return (
    <>
      {screen}
      {guide ? <GuideSheet guides={GAME_GUIDES} initial={guide.id} anchor={guide.anchor} onClose={closeGuide} /> : null}
    </>
  );
}
