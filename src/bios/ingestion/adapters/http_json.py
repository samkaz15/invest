"""Generic JSON API adapter: one fetch = one RawDraft (the whole document).

Provider-agnostic on purpose: any JSON endpoint (price, funding, on-chain
stats, macro series) is just a SourceSpec. Splitting/normalizing documents
is the extraction layer's job.
"""

import json

from bios.ingestion.adapter import (
    AdapterError,
    FetchResult,
    HttpGetter,
    SourceAdapter,
)
from bios.ingestion.rawitem import RawDraft

CONTENT_TYPE = "application/json"


class JsonApiAdapter(SourceAdapter):
    def fetch(self, client: HttpGetter, conditional: dict[str, str] | None = None) -> FetchResult:
        headers = {**self.spec.headers, **(conditional or {})}
        resp = client.get(self.spec.url, headers=headers or None)
        if resp.not_modified:
            return FetchResult(not_modified=True)
        try:
            json.loads(resp.text)
        except json.JSONDecodeError as exc:
            raise AdapterError(f"non-JSON response from {self.spec.source_id}: {exc}") from exc
        draft = RawDraft(payload_text=resp.text, content_type=CONTENT_TYPE, url=self.spec.url)
        return FetchResult(
            drafts=[draft],
            etag=resp.headers.get("etag"),
            last_modified=resp.headers.get("last-modified"),
        )
