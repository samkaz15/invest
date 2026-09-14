"""Generic CSV endpoint adapter: one fetch = one RawDraft (the whole file).

Statistical agencies ship CSV at least as often as JSON — the US Treasury
yield curve and Japan's MOF rate tables both do — and a CSV download is not
a JSON document, so it needs its own kind rather than a flag on the JSON
adapter.

Splitting rows into series is the normalizer's job, not ingestion's: what
is stored here is exactly what the server sent.
"""

import csv
import io

from mios.ingestion.adapter import (
    AdapterError,
    FetchResult,
    HttpGetter,
    SourceAdapter,
)
from mios.ingestion.rawitem import RawDraft

CONTENT_TYPE = "text/csv"


class CsvAdapter(SourceAdapter):
    def fetch(self, client: HttpGetter, conditional: dict[str, str] | None = None) -> FetchResult:
        headers = {**self.spec.headers, **(conditional or {})}
        resp = client.get(self.spec.url, headers=headers or None, encoding=self.spec.encoding)
        if resp.not_modified:
            return FetchResult(not_modified=True)

        # Validate shape at the boundary so an HTML error page served with a
        # .csv URL fails here, loudly, instead of becoming a "CSV with no
        # data rows" three layers downstream.
        text = resp.text
        try:
            reader = csv.reader(io.StringIO(text))
            header = next(reader, None)
        except csv.Error as exc:
            raise AdapterError(f"unreadable CSV from {self.spec.source_id}: {exc}") from exc
        if not header or len(header) < 2:
            snippet = text[:200].replace("\n", " ")
            raise AdapterError(
                f"{self.spec.source_id}: response is not a CSV table (first line: {snippet!r})"
            )

        draft = RawDraft(payload_text=text, content_type=CONTENT_TYPE, url=self.spec.url)
        return FetchResult(
            drafts=[draft],
            etag=resp.headers.get("etag"),
            last_modified=resp.headers.get("last-modified"),
        )
