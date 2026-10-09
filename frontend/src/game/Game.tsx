import { useEffect } from "react";
import { Debrief } from "./Debrief";
import { Setup } from "./Setup";
import { Table } from "./Table";
import { rememberedGame, useGame } from "./store";

/** MARKET MAKING GAME: the lobby, the table, and the debrief. A reload lands back on the same table (the server replays the saved game). */
export function Game() {
  const s = useGame();
  useEffect(() => {
    const id = rememberedGame();
    if (id && useGame.getState().state === null && !useGame.getState().busy) void useGame.getState().resume(id);
  }, []);
  if (s.state && s.state.phase === "done") return <Debrief />;
  if (s.state) return <Table />;
  return <Setup />;
}
