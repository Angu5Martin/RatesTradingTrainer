import { Fragment, type ReactNode } from "react";

/** The small Markdown subset the guides in docs/ are written in, parsed into blocks and rendered as React elements (never as raw HTML).
 *  Headings, paragraphs, bullet / numbered / check lists (nested by indentation), pipe tables, fenced code, block quotes, rules, and <details><summary> for
 *  expandable sections; inline code, **bold**, *italic* and [links](href). Anything else is shown as text. One source: the same files read on GitHub. */

export type Block =
  | { t: "h"; level: number; text: string; slug: string }
  | { t: "p"; text: string }
  | { t: "list"; ordered: boolean; items: Item[] }
  | { t: "table"; head: string[]; rows: string[][] }
  | { t: "code"; lang: string; text: string }
  | { t: "quote"; blocks: Block[] }
  | { t: "hr" }
  | { t: "details"; summary: string; blocks: Block[] };
export interface Item { text: string; check: boolean | null; children: Block[] }

/** GitHub's heading anchors: lower case, punctuation dropped, spaces to hyphens. */
export function slugify(text: string): string {
  return plainText(text).toLowerCase().replace(/[^\p{L}\p{N}\- ]/gu, "").replace(/ /g, "-");
}

/** Inline markup removed: what a heading or a link reads as. */
export function plainText(s: string): string {
  return s.replace(/`([^`]*)`/g, "$1").replace(/\*\*([^*]+)\*\*/g, "$1").replace(/\*([^*\s][^*]*)\*/g, "$1").replace(/\[([^\]]*)\]\([^)]*\)/g, "$1");
}

const LIST = /^(\s*)([-*]|\d+\.)\s+(.*)$/;
const TABLE_SEP = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;

function cells(line: string): string[] {
  const out: string[] = [];
  let cur = "";
  const body = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  for (let i = 0; i < body.length; i++) {
    const c = body[i];
    if (c === "\\" && body[i + 1] === "|") { cur += "|"; i++; continue; }
    if (c === "|") { out.push(cur.trim()); cur = ""; continue; }
    cur += c;
  }
  out.push(cur.trim());
  return out;
}

export function parseMarkdown(src: string): Block[] {
  const lines = src.replace(/\r\n?/g, "\n").split("\n");
  const slugs = new Map<string, number>();
  const unique = (s: string) => { const n = slugs.get(s) ?? 0; slugs.set(s, n + 1); return n ? `${s}-${n}` : s; };

  function blocks(ls: string[]): Block[] {
    const out: Block[] = [];
    let i = 0;
    while (i < ls.length) {
      const line = ls[i];
      const trim = line.trim();
      if (!trim) { i++; continue; }
      if (trim.startsWith("```")) {
        const lang = trim.slice(3).trim();
        const body: string[] = [];
        i++;
        while (i < ls.length && !ls[i].trim().startsWith("```")) body.push(ls[i++]);
        i++;
        out.push({ t: "code", lang, text: body.join("\n") });
        continue;
      }
      if (/^<details>/i.test(trim)) {
        let depth = 0;
        const body: string[] = [];
        let summary = "Details";
        for (; i < ls.length; i++) {
          const l = ls[i].trim();
          if (/^<details>/i.test(l)) { depth++; if (depth === 1) continue; }
          if (/^<\/details>/i.test(l)) { depth--; if (depth === 0) { i++; break; } }
          const m = depth === 1 ? /^<summary>(.*)<\/summary>$/i.exec(l) : null;
          if (m) { summary = m[1]; continue; }
          body.push(ls[i]);
        }
        out.push({ t: "details", summary, blocks: blocks(body) });
        continue;
      }
      const h = /^(#{1,6})\s+(.*?)\s*#*$/.exec(trim);
      if (h) { out.push({ t: "h", level: h[1].length, text: h[2], slug: unique(slugify(h[2])) }); i++; continue; }
      if (/^(-{3,}|\*{3,})$/.test(trim)) { out.push({ t: "hr" }); i++; continue; }
      if (trim.startsWith("|") && i + 1 < ls.length && TABLE_SEP.test(ls[i + 1])) {
        const head = cells(trim);
        const rows: string[][] = [];
        i += 2;
        while (i < ls.length && ls[i].trim().startsWith("|")) rows.push(cells(ls[i++]));
        out.push({ t: "table", head, rows });
        continue;
      }
      if (trim.startsWith(">")) {
        const body: string[] = [];
        while (i < ls.length && ls[i].trim().startsWith(">")) body.push(ls[i++].trim().replace(/^>\s?/, ""));
        out.push({ t: "quote", blocks: blocks(body) });
        continue;
      }
      const li = LIST.exec(line);
      if (li) {
        const indent = li[1].length;
        const ordered = /\d/.test(li[2]);
        const items: Item[] = [];
        while (i < ls.length) {
          const m = LIST.exec(ls[i]);
          if (!m || m[1].length !== indent || /\d/.test(m[2]) !== ordered) break;
          let text = m[3];
          let check: boolean | null = null;
          const c = /^\[( |x|X)\]\s+(.*)$/.exec(text);
          if (c) { check = c[1] !== " "; text = c[2]; }
          i++;
          const sub: string[] = [];
          while (i < ls.length && ls[i].trim() && (ls[i].length - ls[i].trimStart().length) > indent) {
            const deeper = LIST.exec(ls[i]);
            if (deeper && deeper[1].length > indent) sub.push(ls[i].slice(indent + 2));
            else if (sub.length) sub.push(ls[i].slice(indent + 2));
            else text += " " + ls[i].trim();
            i++;
          }
          items.push({ text, check, children: sub.length ? blocks(sub) : [] });
          while (i < ls.length && !ls[i].trim() && i + 1 < ls.length && LIST.exec(ls[i + 1])?.[1].length === indent && /\d/.test(LIST.exec(ls[i + 1])![2]) === ordered) i++;
        }
        out.push({ t: "list", ordered, items });
        continue;
      }
      const para: string[] = [];
      while (i < ls.length && ls[i].trim() && !LIST.exec(ls[i]) && !/^(#{1,6}\s|```|<details>|<\/details>|>|\|)/i.test(ls[i].trim()) && !/^(-{3,}|\*{3,})$/.test(ls[i].trim())) para.push(ls[i++].trim());
      if (para.length) out.push({ t: "p", text: para.join(" ") });
      else i++;                                                                          // a stray closing tag or similar: skip it
    }
    return out;
  }
  return blocks(lines);
}

/** Every heading in the document, in order, with its anchor. */
export function headings(bs: Block[]): { level: number; text: string; slug: string }[] {
  const out: { level: number; text: string; slug: string }[] = [];
  const walk = (xs: Block[]) => xs.forEach((b) => {
    if (b.t === "h") out.push({ level: b.level, text: plainText(b.text), slug: b.slug });
    if (b.t === "details" || b.t === "quote") walk(b.blocks);
    if (b.t === "list") b.items.forEach((it) => walk(it.children));
  });
  walk(bs);
  return out;
}

/** Every link target in the document. */
export function links(src: string): string[] {
  const out: string[] = [];
  const re = /\[[^\]]*\]\(([^)\s]+)\)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(src))) out.push(m[1]);
  return out;
}

export interface RenderOpts {
  /** Called for a link the renderer can follow inside the app; return false when it cannot (the link is shown as text). */
  follow: (href: string) => boolean;
  canFollow: (href: string) => boolean;
  idPrefix: string;
}

function inline(s: string, o: RenderOpts, key = "i"): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*\s][^*]*\*)|(\[[^\]]+\]\([^)\s]+\))/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let n = 0;
  while ((m = re.exec(s))) {
    if (m.index > last) out.push(s.slice(last, m.index));
    const tok = m[0];
    const k = `${key}-${n++}`;
    if (m[1]) out.push(<code key={k}>{tok.slice(1, -1)}</code>);
    else if (m[2]) out.push(<strong key={k}>{inline(tok.slice(2, -2), o, k)}</strong>);
    else if (m[3]) out.push(<em key={k}>{inline(tok.slice(1, -1), o, k)}</em>);
    else {
      const lm = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(tok)!;
      const href = lm[2];
      out.push(o.canFollow(href)
        ? <a key={k} href={href.startsWith("#") ? href : `#${href}`} onClick={(e) => { e.preventDefault(); o.follow(href); }}>{inline(lm[1], o, k)}</a>
        : <span key={k} className="md-ref" title={`in the repository: ${href.replace(/^\.\.\//, "docs/")}`}>{inline(lm[1], o, k)}</span>);
    }
    last = m.index + tok.length;
  }
  if (last < s.length) out.push(s.slice(last));
  return out;
}

const NUMERIC = /^[−+\-]?[\d.,]+%?$|^[−+\-]?\+?[\d,]+(\.\d+)?$/;

export function Markdown({ blocks, opts }: { blocks: Block[]; opts: RenderOpts }) {
  return <>{blocks.map((b, i) => <BlockView key={i} b={b} o={opts} k={`b${i}`} />)}</>;
}

function BlockView({ b, o, k }: { b: Block; o: RenderOpts; k: string }): JSX.Element {
  switch (b.t) {
    case "h": {
      const Tag = (`h${Math.min(6, b.level + 1)}`) as "h2";                          // the guide's title (#) sits under the sheet's own h2
      return <Tag id={`${o.idPrefix}${b.slug}`} data-anchor={b.slug} className={`md-h md-h${b.level}`}>{inline(b.text, o, k)}</Tag>;
    }
    case "p": return <p>{inline(b.text, o, k)}</p>;
    case "hr": return <hr />;
    case "code": return <pre className={`md-code ${b.lang ? `lang-${b.lang}` : ""}`}><code>{b.text}</code></pre>;
    case "quote": return <blockquote><Markdown blocks={b.blocks} opts={o} /></blockquote>;
    case "details": return <details className="md-details"><summary>{inline(b.summary, o, k)}</summary><div className="md-details-b"><Markdown blocks={b.blocks} opts={o} /></div></details>;
    case "table": return (
      <div className="md-table"><table className="tbl">
        <thead><tr>{b.head.map((c, j) => <th key={j}>{inline(c, o, `${k}h${j}`)}</th>)}</tr></thead>
        <tbody>{b.rows.map((r, ri) => <tr key={ri}>{r.map((c, j) => <td key={j} className={j > 0 && NUMERIC.test(c.replace(/\s/g, "")) ? "r num" : ""}>{inline(c, o, `${k}r${ri}c${j}`)}</td>)}</tr>)}</tbody>
      </table></div>
    );
    case "list": {
      const Tag = b.ordered ? "ol" : "ul";
      const checks = b.items.some((it) => it.check !== null);
      return (
        <Tag className={checks ? "md-checks" : undefined}>
          {b.items.map((it, j) => (
            <li key={j}>{it.check !== null ? <span className="md-box" aria-hidden>{it.check ? "☑" : "☐"}</span> : null}
              <Fragment>{inline(it.text, o, `${k}l${j}`)}</Fragment>{it.children.length ? <Markdown blocks={it.children} opts={o} /> : null}</li>
          ))}
        </Tag>
      );
    }
  }
}
