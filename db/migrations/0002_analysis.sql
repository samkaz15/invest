-- 0002: Analysis layer — derived data (recomputable, therefore updatable;
-- no append-only triggers here by design, MSD §13).

CREATE TABLE IF NOT EXISTS dimension_reports (
    asset_id          text NOT NULL,
    dimension         text NOT NULL,
    as_of             timestamptz NOT NULL,
    score             smallint NOT NULL CHECK (score BETWEEN -100 AND 100),
    conviction        real NOT NULL CHECK (conviction BETWEEN 0 AND 1),
    signals           jsonb NOT NULL DEFAULT '[]',
    key_findings      jsonb NOT NULL DEFAULT '[]',
    watch_items       jsonb NOT NULL DEFAULT '[]',
    data_gaps         jsonb NOT NULL DEFAULT '[]',
    invalidation      text NOT NULL DEFAULT '',
    analyzer_version  text NOT NULL,
    PRIMARY KEY (asset_id, dimension, as_of)
);
CREATE INDEX IF NOT EXISTS dimension_reports_asof_idx ON dimension_reports(as_of);

CREATE TABLE IF NOT EXISTS market_reactions (
    event_id     text NOT NULL REFERENCES events(event_id),
    asset_id     text NOT NULL,
    horizon      text NOT NULL CHECK (horizon IN ('+1h','+1d','+7d','+30d','+90d')),
    base_ts      timestamptz NOT NULL,
    base_price   numeric NOT NULL,
    target_ts    timestamptz NOT NULL,
    target_price numeric NOT NULL,
    return       real NOT NULL,
    computed_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (event_id, asset_id, horizon)
);
