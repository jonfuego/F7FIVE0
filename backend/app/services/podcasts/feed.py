"""Parse a podcast RSS feed into plain data.

`feedparser` does the heavy lifting, because real feeds are messy (bad XML,
odd dates, three ways to say "duration"). Two things are done on top of it:

- A feed that declares XML entities is refused before anything parses it. A
  "billion laughs" feed would otherwise expand into gigabytes. Real podcast
  feeds never declare entities.
- The Podcasting 2.0 tags that carry both text and attributes
  (`podcast:season name="..."`) lose their text in feedparser, so a second,
  strict, entity-free pass (defusedxml) reads `podcast:season`, `podcast:episode`,
  `podcast:chapters` and `itunes:season` / `itunes:episode` per item. If that
  pass cannot read the document, feedparser's own values are used.

Every description is stored as plain text: tags are dropped (script and style
with their content), entities are unescaped, nothing is kept as HTML.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Optional

import feedparser
from defusedxml import ElementTree as SafeET

log = logging.getLogger("f7five0.podcasts.feed")

MAX_DESCRIPTION_CHARS = 20_000

_PODCAST_NS = (
    "https://podcastindex.org/namespace/1.0",
    "https://github.com/Podcastindex-org/podcast-namespace/blob/main/docs/1.0.md",
)
_ITUNES_NS = ("http://www.itunes.com/dtds/podcast-1.0.dtd",)

_ENTITY_DECL_RE = re.compile(rb"<!ENTITY", re.IGNORECASE)
_DOCTYPE_RE = re.compile(rb"<!DOCTYPE", re.IGNORECASE)
_ROOT_CONTENT_RE = re.compile(rb"<(channel|feed|item|entry)[\s>/]", re.IGNORECASE)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class FeedError(ValueError):
    """The body is not a usable podcast feed."""


@dataclass
class ParsedEpisode:
    guid: Optional[str]
    title: str
    description: str
    published_at: Optional[datetime]
    duration_sec: Optional[int]
    enclosure_url: str
    enclosure_type: Optional[str]
    enclosure_length: Optional[int]
    season: Optional[int] = None
    episode: Optional[int] = None
    chapters_url: Optional[str] = None


@dataclass
class ParsedFeed:
    title: str
    author: Optional[str]
    description: str
    art_url: Optional[str]
    podcast_guid: Optional[str]
    link: Optional[str]
    episodes: list[ParsedEpisode] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Plain text
# ---------------------------------------------------------------------------
_PARAGRAPH_TAGS = {"p", "div", "ul", "ol", "blockquote", "table", "h1", "h2", "h3", "h4", "h5", "h6", "pre"}
_LINE_TAGS = {"br", "li", "tr"}
_SKIP_TAGS = {"script", "style", "head", "title", "noscript", "template"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag in _PARAGRAPH_TAGS:
            self._out.append("\n\n")
        elif tag in _LINE_TAGS:
            self._out.append("\n")

    def handle_startendtag(self, tag: str, attrs) -> None:
        if tag in _LINE_TAGS or tag in _PARAGRAPH_TAGS:
            self._out.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag in _PARAGRAPH_TAGS:
            self._out.append("\n\n")
        elif tag in _LINE_TAGS:
            self._out.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._out.append(data)

    def text(self) -> str:
        return "".join(self._out)


def plain_text(value: Optional[str], *, limit: int = MAX_DESCRIPTION_CHARS) -> str:
    """HTML (or plain text) to plain text. Tags are removed, script and style
    are dropped with their content, entities are unescaped, paragraphs stay
    separated by a blank line. Never returns markup, a NUL or a control char."""
    if not value:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(str(value))
        parser.close()
        text = parser.text()
    except Exception:  # noqa: BLE001  (HTMLParser can choke on hostile input)
        text = re.sub(r"<[^>]*>", " ", str(value))
    text = _CONTROL_RE.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    text = text.replace("\xa0", " ")
    lines = [re.sub(r"[ \t\f\v]+", " ", ln).strip() for ln in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:limit]


def _one_line(value: Optional[str], limit: int = 500) -> str:
    return re.sub(r"\s+", " ", plain_text(value, limit=limit)).strip()


# ---------------------------------------------------------------------------
# Small field parsers
# ---------------------------------------------------------------------------
def _int(value: Any) -> Optional[int]:
    if isinstance(value, dict):
        return None
    try:
        n = int(str(value).strip().split(".")[0])
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def parse_duration(value: Any) -> Optional[int]:
    """`1:02:03`, `12:30`, `1800` or `1800.5` to whole seconds."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if ":" in text:
            total = 0.0
            for part in text.split(":"):
                total = total * 60 + float(part or 0)
            seconds = total
        else:
            seconds = float(text)
    except ValueError:
        return None
    return int(seconds) if 0 <= seconds < 10 * 24 * 3600 else None


def _http_url(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if value.lower().startswith(("http://", "https://")) and len(value) <= 2048 else None


def _published(entry: Any) -> Optional[datetime]:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def _pick_enclosure(entry: Any) -> Optional[dict]:
    encs = [e for e in (entry.get("enclosures") or []) if _http_url(e.get("href"))]
    if not encs:
        return None
    for e in encs:
        if str(e.get("type") or "").lower().startswith(("audio/", "video/")):
            return e
    return encs[0]


# ---------------------------------------------------------------------------
# Strict pass for the namespaced tags
# ---------------------------------------------------------------------------
def _local_text(el: Any, namespaces: tuple[str, ...], name: str) -> Optional[str]:
    for ns in namespaces:
        found = el.find(f"{{{ns}}}{name}")
        if found is not None:
            return (found.text or "").strip() or None
    return None


def _xml_item_extras(body: bytes) -> list[dict]:
    """Per `<item>`, in document order: season, episode, chapters_url. [] when
    the strict parser cannot read the document."""
    try:
        root = SafeET.fromstring(body)
    except Exception:  # noqa: BLE001  (not well-formed, or it declared entities)
        return []
    channel = root.find("channel")
    if channel is None:
        return []
    out: list[dict] = []
    for item in channel.findall("item"):
        chapters_url = None
        for ns in _PODCAST_NS:
            ch = item.find(f"{{{ns}}}chapters")
            if ch is not None:
                chapters_url = _http_url(ch.get("url"))
                break
        out.append({
            "season": _int(_local_text(item, _PODCAST_NS, "season") or _local_text(item, _ITUNES_NS, "season")),
            "episode": _int(_local_text(item, _PODCAST_NS, "episode") or _local_text(item, _ITUNES_NS, "episode")),
            "chapters_url": chapters_url,
        })
    return out


def _xml_channel_guid(body: bytes) -> Optional[str]:
    try:
        root = SafeET.fromstring(body)
    except Exception:  # noqa: BLE001
        return None
    channel = root.find("channel")
    return _local_text(channel, _PODCAST_NS, "guid") if channel is not None else None


# ---------------------------------------------------------------------------
# The parser
# ---------------------------------------------------------------------------
def _refuse_entities(body: bytes) -> None:
    m = _DOCTYPE_RE.search(body[:65536])
    if not m:
        return
    root = _ROOT_CONTENT_RE.search(body, m.end())
    prolog = body[m.start(): root.start() if root else len(body)]
    if _ENTITY_DECL_RE.search(prolog):
        raise FeedError("the feed declares XML entities, which are not allowed")


def parse_feed(body: bytes, feed_url: str = "") -> ParsedFeed:
    """Parse a feed body. Raises FeedError when it is not a usable feed."""
    if not body or not body.strip():
        raise FeedError("the feed is empty")
    _refuse_entities(body)
    try:
        parsed = feedparser.parse(body)
    except Exception as exc:  # noqa: BLE001
        raise FeedError(f"the feed could not be read ({type(exc).__name__})") from exc

    channel = parsed.feed
    title = _one_line(channel.get("title"))
    if not title and not parsed.entries:
        raise FeedError("that is not a podcast feed")

    extras = _xml_item_extras(body)
    if len(extras) != len(parsed.entries):
        extras = []

    episodes: list[ParsedEpisode] = []
    for i, entry in enumerate(parsed.entries):
        enclosure = _pick_enclosure(entry)
        if enclosure is None:
            continue  # nothing to play
        extra = extras[i] if extras else {}
        season = extra.get("season") or _int(entry.get("itunes_season")) or _int(entry.get("podcast_season"))
        episode_no = extra.get("episode") or _int(entry.get("itunes_episode")) or _int(entry.get("podcast_episode"))
        chapters_url = extra.get("chapters_url")
        if chapters_url is None:
            chapters = entry.get("podcast_chapters")
            if isinstance(chapters, dict):
                chapters_url = _http_url(chapters.get("url"))
        description = plain_text(
            entry.get("summary") or (entry.get("content") or [{}])[0].get("value")
        )
        guid = entry.get("id")
        episodes.append(ParsedEpisode(
            guid=str(guid).strip() if guid else None,
            title=_one_line(entry.get("title")) or "Untitled episode",
            description=description,
            published_at=_published(entry),
            duration_sec=parse_duration(entry.get("itunes_duration")),
            enclosure_url=str(enclosure["href"]).strip(),
            enclosure_type=(str(enclosure.get("type") or "").strip().lower() or None),
            enclosure_length=_int(enclosure.get("length")),
            season=season,
            episode=episode_no,
            chapters_url=chapters_url,
        ))

    image = channel.get("image") or {}
    return ParsedFeed(
        title=title or feed_url or "Untitled podcast",
        author=_one_line(channel.get("author") or channel.get("itunes_author")) or None,
        description=plain_text(channel.get("subtitle") or channel.get("summary") or channel.get("description")),
        art_url=_http_url(image.get("href") if isinstance(image, dict) else None),
        podcast_guid=(str(channel.get("podcast_guid")).strip() if isinstance(channel.get("podcast_guid"), str) else None)
        or _xml_channel_guid(body),
        link=_http_url(channel.get("link")),
        episodes=episodes,
    )
