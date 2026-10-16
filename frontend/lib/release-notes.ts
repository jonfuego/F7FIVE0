// Release notes from GitHub are Markdown. This turns the small part of Markdown
// the notes use (headings, bullet and numbered lists, paragraphs, bold, inline
// code and links) into plain data that the page renders as React elements.
// Nothing is ever rendered as HTML, and a link is kept only when it is http(s).

export type Inline =
  | { kind: "text"; text: string }
  | { kind: "bold"; text: string }
  | { kind: "code"; text: string }
  | { kind: "link"; text: string; href: string };

export type Block =
  | { kind: "heading"; level: 1 | 2 | 3; content: Inline[] }
  | { kind: "paragraph"; content: Inline[] }
  | { kind: "list"; ordered: boolean; items: Inline[][] };

function safeHref(raw: string): string | null {
  try {
    const u = new URL(raw);
    return u.protocol === "https:" || u.protocol === "http:" ? u.toString() : null;
  } catch {
    return null;
  }
}

/** Bold (`**x**` or `__x__`), inline code and `[text](url)` links. */
export function parseInline(text: string): Inline[] {
  const out: Inline[] = [];
  const re = /(\*\*([^*]+)\*\*|__([^_]+)__|`([^`]+)`|\[([^\]]+)\]\(([^)\s]+)\))/g;
  let last = 0;
  let m: RegExpExecArray | null;
  const pushText = (t: string) => {
    if (!t) return;
    const prev = out[out.length - 1];
    if (prev && prev.kind === "text") prev.text += t;
    else out.push({ kind: "text", text: t });
  };
  while ((m = re.exec(text)) !== null) {
    pushText(text.slice(last, m.index));
    if (m[2] !== undefined || m[3] !== undefined) {
      out.push({ kind: "bold", text: m[2] ?? m[3] });
    } else if (m[4] !== undefined) {
      out.push({ kind: "code", text: m[4] });
    } else {
      const href = safeHref(m[6]);
      if (href) out.push({ kind: "link", text: m[5], href });
      else pushText(m[5]);
    }
    last = m.index + m[0].length;
  }
  pushText(text.slice(last));
  return out;
}

const HEADING = /^(#{1,6})\s+(.*?)\s*#*\s*$/;
const BULLET = /^\s*[-*+]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;

export function parseReleaseNotes(md: string): Block[] {
  const blocks: Block[] = [];
  let para: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;

  const flushPara = () => {
    if (para.length) blocks.push({ kind: "paragraph", content: parseInline(para.join(" ")) });
    para = [];
  };
  const flushList = () => {
    if (list) blocks.push({ kind: "list", ordered: list.ordered, items: list.items.map(parseInline) });
    list = null;
  };

  for (const rawLine of md.replace(/\r\n?/g, "\n").split("\n")) {
    const line = rawLine.trimEnd();
    if (!line.trim()) {
      flushPara();
      flushList();
      continue;
    }
    const h = HEADING.exec(line);
    if (h) {
      flushPara();
      flushList();
      const level = Math.min(3, h[1].length) as 1 | 2 | 3;
      blocks.push({ kind: "heading", level, content: parseInline(h[2]) });
      continue;
    }
    const b = BULLET.exec(line);
    const n = b ? null : NUMBERED.exec(line);
    if (b || n) {
      flushPara();
      const ordered = !!n;
      const curList = list as { ordered: boolean; items: string[] } | null;
      if (curList && curList.ordered !== ordered) flushList();
      if (!list) list = { ordered, items: [] };
      (list as { ordered: boolean; items: string[] }).items.push((b ?? n)![1]);
      continue;
    }
    const curList = list as { ordered: boolean; items: string[] } | null;
    if (curList && /^\s+/.test(rawLine)) {
      // An indented line continues the last list item.
      curList.items[curList.items.length - 1] += " " + line.trim();
      continue;
    }
    flushList();
    para.push(line.trim());
  }
  flushPara();
  flushList();
  return blocks;
}
