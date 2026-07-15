"""Market normalizer (L2): latest raw payloads -> one market snapshot row.

Mappings are declarative per source: a dotted-path table from payload to
metric names (declared here, provider-specific knowledge lives in one
place). Numbers are machine-copied — no interpretation at this layer.
"""

import json
from typing import Any

from bios.common.logutil import get_logger
from bios.common.timeutil import utc_now
from bios.ingestion.rawstore import RawStore
from bios.knowledge.snapshots import SnapshotRepo

logger = get_logger(__name__)

# source_id -> metric -> dotted path into the JSON payload.
# "[0]" indexes lists. Missing paths are recorded as data gaps, not errors.
METRIC_PATHS: dict[str, dict[str, str]] = {
    "src_coingecko_btc": {
        "price_usd": "market_data.current_price.usd",
        "volume_24h_usd": "market_data.total_volume.usd",
        "market_cap_usd": "market_data.market_cap.usd",
    },
    "src_bybit_btc_derivs": {
        "funding_rate": "result.list.[0].fundingRate",
        "open_interest": "result.list.[0].openInterest",
        "open_interest_value_usd": "result.list.[0].openInterestValue",
    },
    "src_fng_alternative": {"fear_greed": "data.[0].value"},
    "src_mempool_hashrate": {
        "hash_rate": "currentHashrate",
        "difficulty": "currentDifficulty",
    },
    "src_blockchain_info_stats": {
        "miners_revenue_usd": "miners_revenue_usd",
        "n_tx_24h": "n_tx",
    },
}


def dig(payload: Any, path: str) -> float | None:
    node = payload
    for part in path.split("."):
        if part.startswith("[") and part.endswith("]"):
            index = int(part[1:-1])
            if not isinstance(node, list) or index >= len(node):
                return None
            node = node[index]
        elif isinstance(node, dict):
            node = node.get(part)
        else:
            return None
        if node is None:
            return None
    try:
        return float(node)
    except (TypeError, ValueError):
        return None


class MarketNormalizer:
    def __init__(self, store: RawStore, snapshots: SnapshotRepo, asset_id: str) -> None:
        self._store = store
        self._snapshots = snapshots
        self._asset_id = asset_id

    def build_snapshot(self) -> dict[str, Any]:
        """Read the latest raw item of each mapped source and upsert one
        snapshot at the current hour. Returns metrics + gaps for reporting."""
        ts = utc_now().replace(minute=0, second=0, microsecond=0)
        metrics: dict[str, float] = {}
        provenance: dict[str, str] = {}
        gaps: list[str] = []
        for source_id, paths in METRIC_PATHS.items():
            item = self._store.latest(source_id)
            if item is None:
                gaps.extend(f"{source_id}:{m}" for m in paths)
                continue
            payload = json.loads(item.payload_text)
            for metric, path in paths.items():
                value = dig(payload, path)
                if value is None:
                    gaps.append(f"{source_id}:{metric}")
                else:
                    metrics[metric] = value
                    provenance[metric] = item.raw_item_id
        price = metrics.pop("price_usd", None)
        volume = metrics.pop("volume_24h_usd", None)
        self._snapshots.upsert(
            self._asset_id, ts, price, volume, asset_metrics=metrics, sources=provenance
        )
        logger.info(
            "snapshot %s @%s: price=%s metrics=%d gaps=%d",
            self._asset_id,
            ts.isoformat(),
            price,
            len(metrics),
            len(gaps),
        )
        return {"ts": ts, "price_usd": price, "metrics": metrics, "gaps": gaps}
