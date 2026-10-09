import { useEffect, useMemo, useRef, useState } from "react";
import { GUIDES, type GuideId, resolveLink } from "./guides";
import { Markdown, headings, parseMarkdown } from "./markdown";

const parsed = new Map<GuideId, ReturnType<typeof parseMarkdown>>();
const blocksOf = (id: GuideId) => { let b = parsed.get(id); if (!b) { b = parseMarkdown(GUIDES[id].source); parsed.set(id, b); } return b; };

/** HOW TO · BEST PRACTICES: the guides from docs/ in a sheet over the current screen. Opening and closing it changes nothing underneath (it is an overlay;
 *  the screen below stays mounted with its quotes, drafts and selections). Tabs switch guide; the contents column and links jump to sections. */
export function GuideSheet({ guides, initial, anchor, onClose }: { guides: GuideId[]; initial?: GuideId; anchor?: string; onClose: () => void }) {
  const [tab, setTab] = useState<GuideId>(initial ?? guides[0]);
  const body = useRef<HTMLDivElement>(null);
  const closeBtn = useRef<HTMLButtonElement>(null);
  const pending = useRef<string | null>(anchor ?? null);           // a section to open at, once the guide has rendered
  const blocks = useMemo(() => blocksOf(tab), [tab]);
  const toc = useMemo(() => headings(blocks).filter((h) => h.level === 2), [blocks]);
  const prefix = `guide-${tab}-`;

  useEffect(() => {
    const back = document.activeElement as HTMLElement | null;
    closeBtn.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); onClose(); } };
    window.addEventListener("keydown", onKey, true);
    return () => { window.removeEventListener("keydown", onKey, true); back?.focus?.(); };
  }, [onClose]);

  const jump = (anchor: string | null) => {
    const el = anchor ? body.current?.querySelector<HTMLElement>(`[data-anchor="${CSS.escape(anchor)}"]`) : null;
    if (el) el.scrollIntoView?.({ block: "start" });
    else body.current?.scrollTo?.({ top: 0 });
  };
  useEffect(() => { jump(pending.current); pending.current = null; }, [tab]);   // eslint-disable-line react-hooks/exhaustive-deps

  const go = (guide: GuideId, anchor: string | null) => {
    if (guide === tab) { jump(anchor); return; }
    pending.current = anchor;
    setTab(guide);
  };
  const reachable = (href: string) => { const r = resolveLink(href, tab); return !!r && guides.includes(r.guide); };
  const opts = {
    idPrefix: prefix,
    canFollow: reachable,
    follow: (href: string) => { const r = resolveLink(href, tab); if (!r || !guides.includes(r.guide)) return false; go(r.guide, r.anchor); return true; },
  };

  return (
    <div className="overlay guide-overlay" onClick={onClose}>
      <div className="sheet guide-sheet" role="dialog" aria-modal="true" aria-label="How to and best practices" onClick={(e) => e.stopPropagation()}>
        <header className="sheet-h guide-h">
          <h2>HOW TO · BEST PRACTICES</h2>
          {guides.length > 1 ? (
            <div className="guide-tabs" role="tablist" aria-label="guides">
              {guides.map((g) => <button key={g} role="tab" aria-selected={g === tab} className={`seg-b ${g === tab ? "on" : ""}`} onClick={() => go(g, null)}>{GUIDES[g].tab}</button>)}
            </div>
          ) : null}
          <span className="tb-spacer" />
          <span className="dim guide-src" title="The same file is in the repository">{GUIDES[tab].file}</span>
          <button ref={closeBtn} className="btn btn-ghost" onClick={onClose}>Close <span className="kbd-inline">Esc</span></button>
        </header>
        <div className="guide-main">
          <nav className="guide-toc" aria-label="sections">
            <ul>{toc.map((h) => <li key={h.slug}><button onClick={() => jump(h.slug)}>{h.text}</button></li>)}</ul>
          </nav>
          <div className="guide-body" ref={body} role="tabpanel" aria-label={GUIDES[tab].title} data-testid="guide-body">
            <article className="md"><Markdown blocks={blocks} opts={opts} /></article>
          </div>
        </div>
      </div>
    </div>
  );
}
