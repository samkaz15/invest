"""Adapter tests: raw store, RSS/Atom/JSON parsing, canonical payloads."""

import json
from pathlib import Path

import pytest

from bios.config.models import SourceSpec
from bios.ingestion.adapter import AdapterError, conditional_headers
from bios.ingestion.adapters.http_json import JsonApiAdapter
from bios.ingestion.adapters.rss import RssAdapter
from bios.ingestion.http import HttpResponse
from bios.ingestion.rawitem import RawDraft, build_raw_item, content_hash_of
from bios.ingestion.rawstore import FileRawStore

RSS_SAMPLE = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Feed</title>
<item><guid>g1</guid><title>SEC approves ETF</title><link>https://x/1</link>
<pubDate>Wed, 10 Jan 2024 21:00:00 GMT</pubDate><description>d1</description></item>
<item><title>Second item no guid</title><link>https://x/2</link></item>
<item><link>https://x/broken-no-title</link></item>
</channel></rss>"""

ATOM_SAMPLE = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>A</title>
<entry><id>a1</id><title>Atom entry</title><link href="https://a/1"/>
<updated>2024-01-10T21:00:00Z</updated><summary>s</summary></entry></feed>"""


class FakeClient:
    def __init__(self, response: HttpResponse) -> None:
        self.response = response
        self.requested_headers: dict[str, str] | None = None

    def get(self, url: str, headers: dict[str, str] | None = None) -> HttpResponse:
        self.requested_headers = headers
        return self.response


def _spec(kind: str = "rss") -> SourceSpec:
    return SourceSpec(
        source_id="src_test_feed", name="t", kind=kind, url="https://example.com/feed", tier=3
    )


def test_rss_entries_become_canonical_drafts_and_bad_entry_fails_soft() -> None:
    result = RssAdapter(_spec()).fetch(FakeClient(HttpResponse(200, RSS_SAMPLE)))
    assert len(result.drafts) == 2  # third entry has no title -> parse failure
    assert len(result.parse_failures) == 1
    first = json.loads(result.drafts[0].payload_text)
    assert first == {
        "guid": "g1",
        "title": "SEC approves ETF",
        "link": "https://x/1",
        "published": "Wed, 10 Jan 2024 21:00:00 GMT",
        "summary": "d1",
    }
    # canonical payload -> stable hash across refetches
    assert content_hash_of(result.drafts[0].payload_text) == content_hash_of(
        RssAdapter(_spec()).fetch(FakeClient(HttpResponse(200, RSS_SAMPLE))).drafts[0].payload_text
    )


def test_atom_feed_supported() -> None:
    result = RssAdapter(_spec()).fetch(FakeClient(HttpResponse(200, ATOM_SAMPLE)))
    assert len(result.drafts) == 1
    assert json.loads(result.drafts[0].payload_text)["link"] == "https://a/1"


def test_malformed_feed_raises_adapter_error() -> None:
    with pytest.raises(AdapterError, match="unparsable feed"):
        RssAdapter(_spec()).fetch(FakeClient(HttpResponse(200, "<not-xml")))


def test_not_modified_short_circuits() -> None:
    result = RssAdapter(_spec()).fetch(FakeClient(HttpResponse(304, "")))
    assert result.not_modified and not result.drafts


def test_json_adapter_validates_and_passes_conditional_headers() -> None:
    client = FakeClient(HttpResponse(200, '{"price": 1}', {"etag": 'W/"abc"'}))
    result = JsonApiAdapter(_spec("http_json")).fetch(client, conditional_headers('W/"old"', None))
    assert result.drafts[0].payload_text == '{"price": 1}'
    assert result.etag == 'W/"abc"'
    assert client.requested_headers == {"If-None-Match": 'W/"old"'}
    with pytest.raises(AdapterError, match="non-JSON"):
        JsonApiAdapter(_spec("http_json")).fetch(FakeClient(HttpResponse(200, "<html>")))


def test_raw_store_dedupes_and_is_append_only(tmp_path: Path) -> None:
    store = FileRawStore(tmp_path)
    draft = RawDraft(payload_text='{"a":1}', content_type="application/json")
    item1 = build_raw_item("src_test_feed", draft)
    assert store.put(item1) is True
    item2 = build_raw_item("src_test_feed", draft)  # same payload, new identity
    assert store.put(item2) is False  # deduplicated by content hash
    files = list(tmp_path.rglob("raw_*.json"))
    assert len(files) == 1
    # cold restart re-reads the ledger
    assert FileRawStore(tmp_path).seen("src_test_feed", item1.content_hash)
