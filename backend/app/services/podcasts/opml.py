"""OPML import and export for podcast subscriptions.

Import reads a subscription list another app exported. It is parsed with
defusedxml (entities, DTDs and external references are refused) and the
upload is capped at 1 MB by the caller (`net_guard.OPML_MAX_BYTES`). Export
writes OPML 2.0 with one outline per followed show that has a feed.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Iterable, Optional

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

MAX_FEEDS_PER_IMPORT = 2000


class OpmlError(ValueError):
    """The upload is not an OPML file we can read."""


def parse_opml(data: bytes) -> list[str]:
    """Every distinct `xmlUrl` in the file, in document order (any outline
    depth). Raises OpmlError for a file that is not OPML, is not well formed,
    or tries entity expansion."""
    try:
        root = SafeET.fromstring(data)
    except (DefusedXmlException, ET.ParseError, ValueError) as exc:
        raise OpmlError("not a readable OPML file") from exc
    if str(root.tag).lower() != "opml":
        raise OpmlError("not an OPML file")
    seen: dict[str, None] = {}
    for outline in root.iter("outline"):
        url = (outline.get("xmlUrl") or outline.get("xmlurl") or "").strip()
        if url:
            seen.setdefault(url, None)
    return list(seen)


def export_opml(shows: Iterable[tuple[str, Optional[str], str]], title: str = "F7FIVE0 podcasts") -> bytes:
    """OPML 2.0 for `(title, link, feed_url)` rows."""
    root = ET.Element("opml", version="2.0")
    head = ET.SubElement(root, "head")
    ET.SubElement(head, "title").text = title
    body = ET.SubElement(root, "body")
    for show_title, link, feed_url in shows:
        attrs = {"type": "rss", "text": show_title, "title": show_title, "xmlUrl": feed_url}
        if link:
            attrs["htmlUrl"] = link
        ET.SubElement(body, "outline", attrs)
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
