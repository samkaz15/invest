"""Source adapter framework.

An adapter turns one HTTP fetch into zero or more :class:`RawDraft`s.
Adapters are provider-agnostic by *kind* (rss, http_json, ...): a concrete
provider is pure YAML (SourceSpec). A new kind is a framework change and
goes through review; a new provider never touches code.
"""

from abc import ABC, abstractmethod
from typing import Protocol

from pydantic import Field

from mios.common.errors import MiosError
from mios.common.schema import MiosModel
from mios.config.models import SourceSpec
from mios.ingestion.http import HttpResponse
from mios.ingestion.rawitem import RawDraft


class AdapterError(MiosError):
    """The source responded but its data was unusable (whole-fetch level)."""


class HttpGetter(Protocol):
    def get(self, url: str, headers: dict[str, str] | None = None) -> HttpResponse: ...


class ParseFailure(MiosModel):
    """A single item within a fetch that could not be parsed (goes to DLQ)."""

    reason: str
    payload_snippet: str = Field(max_length=2000)


class FetchResult(MiosModel):
    drafts: list[RawDraft] = Field(default_factory=list)
    parse_failures: list[ParseFailure] = Field(default_factory=list)
    etag: str | None = None
    last_modified: str | None = None
    not_modified: bool = False


class SourceAdapter(ABC):
    def __init__(self, spec: SourceSpec) -> None:
        self.spec = spec

    @abstractmethod
    def fetch(self, client: HttpGetter, conditional: dict[str, str] | None = None) -> FetchResult:
        """Fetch once. ``conditional`` carries If-None-Match / If-Modified-Since."""


def conditional_headers(etag: str | None, last_modified: str | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    return headers
