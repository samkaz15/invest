"""Concrete adapter kinds and the factory mapping SourceSpec.kind to them."""

from mios.config.models import SourceSpec
from mios.ingestion.adapter import SourceAdapter
from mios.ingestion.adapters.http_json import JsonApiAdapter
from mios.ingestion.adapters.rss import RssAdapter

_KINDS: dict[str, type[SourceAdapter]] = {
    "rss": RssAdapter,
    "http_json": JsonApiAdapter,
}


def build_adapter(spec: SourceSpec) -> SourceAdapter:
    return _KINDS[spec.kind](spec)  # kinds are closed by SourceSpec's Literal


__all__ = ["JsonApiAdapter", "RssAdapter", "build_adapter"]
