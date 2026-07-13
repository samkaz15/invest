"""RSS 2.0 / Atom adapter.

Each feed entry becomes one RawDraft with a *canonical JSON payload*
(sorted keys) so the same article re-fetched later hashes identically —
that is what makes hash deduplication work at the article level.
Timestamps are kept as the feed's raw strings; parsing them is the
extraction layer's job, not ingestion's.
"""

import json
import xml.etree.ElementTree as ET

from bios.ingestion.adapter import (
    AdapterError,
    FetchResult,
    HttpGetter,
    ParseFailure,
    SourceAdapter,
)
from bios.ingestion.rawitem import RawDraft

_ATOM = "{http://www.w3.org/2005/Atom}"
CONTENT_TYPE = "application/x-bios-feed-entry+json"


class RssAdapter(SourceAdapter):
    def fetch(self, client: HttpGetter, conditional: dict[str, str] | None = None) -> FetchResult:
        resp = client.get(self.spec.url, headers=conditional or None)
        if resp.not_modified:
            return FetchResult(not_modified=True)
        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError as exc:
            raise AdapterError(f"unparsable feed from {self.spec.source_id}: {exc}") from exc

        entries = root.findall(".//item") or root.findall(f".//{_ATOM}entry")
        drafts: list[RawDraft] = []
        failures: list[ParseFailure] = []
        for entry in entries:
            try:
                drafts.append(self._draft(entry))
            except (AttributeError, ValueError) as exc:
                failures.append(
                    ParseFailure(
                        reason=f"feed entry parse failure: {exc}",
                        payload_snippet=ET.tostring(entry, encoding="unicode")[:2000],
                    )
                )
        return FetchResult(
            drafts=drafts,
            parse_failures=failures,
            etag=resp.headers.get("etag"),
            last_modified=resp.headers.get("last-modified"),
        )

    def _draft(self, entry: ET.Element) -> RawDraft:
        def text(*tags: str) -> str | None:
            for tag in tags:
                node = entry.find(tag)
                if node is not None and node.text:
                    return node.text.strip()
            return None

        link = text("link", f"{_ATOM}link")
        if link is None:  # atom carries link in href attribute
            node = entry.find(f"{_ATOM}link")
            link = node.get("href") if node is not None else None
        title = text("title", f"{_ATOM}title")
        if not title:
            raise ValueError("entry without title")
        record = {
            "guid": text("guid", f"{_ATOM}id") or link or title,
            "title": title,
            "link": link,
            "published": text("pubDate", f"{_ATOM}published", f"{_ATOM}updated"),
            "summary": text("description", f"{_ATOM}summary", f"{_ATOM}content"),
        }
        return RawDraft(
            payload_text=json.dumps(record, sort_keys=True, ensure_ascii=False),
            content_type=CONTENT_TYPE,
            url=link,
            meta={"feed_url": self.spec.url},
        )
