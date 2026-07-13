"""Concrete adapter kinds and the factory mapping SourceSpec.kind to them."""

from bios.config.models import SourceSpec
from bios.ingestion.adapter import SourceAdapter
from bios.ingestion.adapters.http_json import JsonApiAdapter
from bios.ingestion.adapters.rss import RssAdapter

_KINDS: dict[str, type[SourceAdapter]] = {
    "rss": RssAdapter,
    "http_json": JsonApiAdapter,
}


def build_adapter(spec: SourceSpec) -> SourceAdapter:
    return _KINDS[spec.kind](spec)  # kinds are closed by SourceSpec's Literal


__all__ = ["JsonApiAdapter", "RssAdapter", "build_adapter"]
