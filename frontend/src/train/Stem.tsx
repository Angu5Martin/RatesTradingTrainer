/** A question's stem: prose as paragraphs, and the market-screen lines (the ones with `|` separators) as a monospace block. Display only; nothing is parsed. */
export function Stem({ text }: { text: string }) {
  const blocks: { screen: boolean; lines: string[] }[] = [];
  for (const line of text.split("\n")) {
    if (line.trim() === "") continue;
    const screen = line.includes(" | ");
    const last = blocks[blocks.length - 1];
    if (last && last.screen === screen) last.lines.push(line); else blocks.push({ screen, lines: [line] });
  }
  return (
    <div className="stem">
      {blocks.map((b, i) => b.screen
        ? <pre className="screen" key={i}>{b.lines.join("\n")}</pre>
        : <p key={i}>{b.lines.join(" ")}</p>)}
    </div>
  );
}
