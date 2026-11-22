// Release notes from GitHub are Markdown. This turns the small part of Markdown
// the notes use (headings, bullet and numbered lists, simple tables, paragraphs,
// bold, inline code and links) into plain data that the page renders as React
// elements. Nothing is ever rendered as HTML, and a link is kept only when it
// is http(s).
//
// A release page is more than its notes: since 1.0.24 it is the plain-language
// notes (release-notes/<ver>.md), then RELEASE_NOTES_MARKER, then the "Which
// file do I need?" download guide and GitHub's change list. `whatsNew` keeps
// only the part a person deciding whether to update needs.

export type Inline =
  | { kind: "text"; text: string }
  | { kind: "bold"; text: string }
  | { kind: "code"; text: string }
  | { kind: "link"; text: string; href: string };

export type Block =
  | { kind: "heading"; level: 1 | 2 | 3; content: Inline[] }
  | { kind: "paragraph"; content: Inline[] }
  | { kind: "list"; ordered: boolean; items: Inline[][] }
  | { kind: "table"; header: Inline[][]; rows: Inline[][][] };

/** The line scripts/release-body.ps1 puts between the notes and the download
 *  guide. Keep the two identical. */
export const RELEASE_NOTES_MARKER = "<!-- f7five0:download-guide -->";

const RELEASES_URL = "https://github.com/jonfuego/F7FIVE0/releases";

/** The GitHub release page of a version (only for a plain x.y.z version). */
export function releasePageUrl(version: string): string {
  return /^\d+\.\d+\.\d+$/.test(version) ? `${RELEASES_URL}/tag/v${version}` : RELEASES_URL;
}

const GUIDE_HEADING = /^(#{1,6})\s+which file do i need\??\s*#*\s*$/i;
const FULL_CHANGELOG = /^\s*(\*\*)?full changelog(\*\*)?\s*:/i;
// GitHub's generated list: "* <PR title> by @someone in https://.../pull/12".
const PR_CREDIT = /\s+by @[\w-]+(\[bot\])? in https:\/\/\S+\s*$/;

/**
 * The "What's new" part of a release page. A page with the marker gives
 * everything above it. An older page (no marker) loses the "Which file do I
 * need?" section and the Full Changelog line, and its generated list keeps
 * just the titles. HTML comments go. "" when nothing is left to show.
 */
export function whatsNew(body: string | null | undefined): string {
  let text = (body ?? "").replace(/\r\n?/g, "\n");
  const cut = text.indexOf(RELEASE_NOTES_MARKER);
  if (cut >= 0) {
    text = text.slice(0, cut);
  } else {
    const kept: string[] = [];
    let guideLevel = 0;
    for (const line of text.split("\n")) {
      const g = GUIDE_HEADING.exec(line);
      if (g) {
        guideLevel = g[1].length;
        continue;
      }
      if (guideLevel) {
        const h = HEADING.exec(line);
        if (!h || h[1].length > guideLevel) continue;
        guideLevel = 0;
      }
      if (FULL_CHANGELOG.test(line)) continue;
      kept.push(line.replace(PR_CREDIT, ""));
    }
    text = kept.join("\n");
  }
  // Drop HTML comments, repeating until none are left so a nested or split
  // "<!--" can't survive one pass. Then drop any leftover opener the same way:
  // removing one "<!--" can join the characters around it into a new one.
  let prev: string;
  do {
    prev = text;
    text = text.replace(/<!--[\s\S]*?-->/g, "").replace(/<!--/g, "");
  } while (text !== prev);
  text = text.trim();
  // Headings with nothing under them (an empty "What's Changed") are no notes.
  const hasContent = text.split("\n").some((l) => l.trim() && !HEADING.test(l.trimEnd()));
  return hasContent ? text : "";
}

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
const TABLE_ROW = /^\s*\|.*\|\s*$/;
const TABLE_RULE = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;

/** The cells of a `| a | b |` row (a `\|` stays a pipe inside a cell). */
function tableCells(line: string): string[] {
  let t = line.trim();
  if (t.startsWith("|")) t = t.slice(1);
  if (t.endsWith("|") && !t.endsWith("\\|")) t = t.slice(0, -1);
  return t.split(/(?<!\\)\|/).map((c) => c.replace(/\\\|/g, "|").trim());
}

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

  const lines = md.replace(/\r\n?/g, "\n").split("\n");
  for (let i = 0; i < lines.length; i++) {
    const rawLine = lines[i];
    const line = rawLine.trimEnd();
    if (!line.trim()) {
      flushPara();
      flushList();
      continue;
    }
    // A table: a | row |, then a |---| rule, then rows until a line that isn't one.
    if (TABLE_ROW.test(line) && i + 1 < lines.length && TABLE_RULE.test(lines[i + 1]) && lines[i + 1].includes("-")) {
      flushPara();
      flushList();
      const header = tableCells(line);
      const rows: Inline[][][] = [];
      i += 2;
      while (i < lines.length && TABLE_ROW.test(lines[i].trimEnd())) {
        const cells = tableCells(lines[i]);
        // Pad or trim to the header's width so every row lines up.
        const fitted = header.map((_, c) => cells[c] ?? "");
        rows.push(fitted.map(parseInline));
        i++;
      }
      i--;
      blocks.push({ kind: "table", header: header.map(parseInline), rows });
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
