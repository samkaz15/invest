-- 0005: The MIOS core — time series with vintages, releases, and the
-- economic calendar.
--
-- This is the migration the whole project rests on. The BIOS-era
-- market_snapshots table merged metrics in place (docs/REPOSITORY_AUDIT.md
-- §4.1 problem A), which is fine for a spot price and fatal for an economic
-- statistic: CPI and NFP are revised, and an in-place merge destroys what
-- was knowable at the time. Everything below exists to make that
-- destruction impossible.
--
-- The old tables are NOT dropped. They hold BIOS-era data, they carry
-- append-only triggers that refuse deletion anyway, and nothing here reads
-- them. They are simply left behind.
--
-- NOTE: no BEGIN/COMMIT — the migration runner wraps each file in a
-- transaction together with its schema_migrations bookkeeping row.

-- MIOS gets its own refusal trigger rather than reusing the BIOS one, so
-- the error message names the right project. The old function stays where
-- it is: editing an applied migration is forbidden.
CREATE OR REPLACE FUNCTION mios_forbid_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'table % is append-only (MIOS CONSTITUTION.md Art.6): % refused. '
        'Correct by inserting a superseding row, never by rewriting history.',
        TG_TABLE_NAME, TG_OP;
END;
$$ LANGUAGE plpgsql;

-- ----------------------------------------------------------------- series
-- The registry of everything MIOS tracks over time. Synced from
-- config/series.yaml, which is the source of truth; this table exists so
-- observations can carry a foreign key and joins are cheap.
CREATE TABLE IF NOT EXISTS series (
    series_id      text PRIMARY KEY,
    name           text NOT NULL,
    country        text NOT NULL CHECK (country IN ('US','JP','EA','CN','GLOBAL')),
    category       text NOT NULL,   -- inflation | employment | growth | rates | fx | commodity | risk
    unit           text NOT NULL,   -- percent | percent_change | index | thousands | level | ratio
    frequency      text NOT NULL
                   CHECK (frequency IN ('daily','weekly','monthly','quarterly','irregular')),
    source_id      text NOT NULL REFERENCES sources(source_id),
    provider_code  text NOT NULL,   -- the id at the provider, e.g. CPIAUCSL, "10 Yr", XAU/USD
    parser         text NOT NULL,   -- which payload parser reads this series
    -- Whether the publisher revises past values. Drives how hard the
    -- vintage discipline has to work: a revisable series must never be
    -- read without an as-of filter.
    revisable      boolean NOT NULL,
    seasonal_adjustment text NOT NULL DEFAULT 'unknown'
                   CHECK (seasonal_adjustment IN ('sa','nsa','unknown','not_applicable')),
    notes          text NOT NULL DEFAULT '',
    synced_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS series_category_idx ON series(category);
CREATE INDEX IF NOT EXISTS series_source_idx ON series(source_id);

-- ----------------------------------------------------------- observations
-- One row = "at vintage_at, the value for observation_date was X".
--
-- observation_date is the REFERENCE PERIOD (2026-08-01 = August data), not
-- the publication date. Conflating the two is the second structural leak
-- the audit found (§14 L2): August CPI must not be usable by an analysis
-- dated in August.
--
-- vintage_at is when MIOS could first know the value. For a real vintage
-- feed (ALFRED) it is the provider's realtime_start; otherwise it is the
-- retrieval time of the fetch that produced it — which is honest, because
-- that genuinely is the earliest moment this system knew.
--
-- A new row is written ONLY when the value differs from the latest vintage
-- for that (series, observation_date). Re-fetching unchanged data adds
-- nothing, so every row here is a real first publication or a real
-- revision, and revision_n counts revisions rather than fetches.
--
-- value IS NULL is meaningful and distinct from having no row: it records
-- that the publisher explicitly reported no figure for that period.
CREATE TABLE IF NOT EXISTS observations (
    series_id        text NOT NULL REFERENCES series(series_id),
    observation_date date NOT NULL,
    vintage_at       timestamptz NOT NULL,
    value            numeric,
    revision_n       integer NOT NULL DEFAULT 0 CHECK (revision_n >= 0),
    source_id        text NOT NULL REFERENCES sources(source_id),
    raw_item_id      text NOT NULL,   -- provenance into data/raw/; no fabricated numbers
    ingested_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (series_id, observation_date, vintage_at)
);
-- The shape every as-of query walks: newest vintage at or before a cutoff.
CREATE INDEX IF NOT EXISTS observations_asof_idx
    ON observations(series_id, observation_date, vintage_at DESC);
CREATE INDEX IF NOT EXISTS observations_vintage_idx ON observations(vintage_at);
CREATE TRIGGER observations_append_only BEFORE UPDATE OR DELETE ON observations
    FOR EACH ROW EXECUTE FUNCTION mios_forbid_mutation();

-- ---------------------------------------------------------------- releases
-- One publication event of an indicator: what came out, what the market
-- expected, and what the previous print was said to be.
--
-- Separate from observations because a release is an *event with
-- expectations attached*, and the surprise it produces is what actually
-- moves Gold and USDJPY. A revision to a past period arrives as a new
-- observation vintage, not as a second release row — hence the uniqueness
-- of (series_id, period).
CREATE TABLE IF NOT EXISTS releases (
    release_id            text PRIMARY KEY,
    series_id             text NOT NULL REFERENCES series(series_id),
    period                date NOT NULL,          -- reference period of the figure
    release_at            timestamptz NOT NULL,   -- when it was published
    actual                numeric,
    forecast              numeric,                -- consensus as of the release
    previous              numeric,                -- prior period as previously published
    revised_previous      numeric,                -- prior period as restated by this release
    -- Kept as a stored column rather than computed on read: the surprise is
    -- referenced constantly, and deriving it in a dozen queries invites a
    -- dozen chances to derive it differently.
    surprise              numeric GENERATED ALWAYS AS (actual - forecast) STORED,
    standardized_surprise numeric,                -- surprise / stdev of past surprises
    source_id             text NOT NULL REFERENCES sources(source_id),
    source_url            text NOT NULL,          -- CONSTITUTION.md Art.4: no figure without provenance
    vintage_at            timestamptz NOT NULL,
    ingested_at           timestamptz NOT NULL DEFAULT now(),
    UNIQUE (series_id, period)
);
CREATE INDEX IF NOT EXISTS releases_release_at_idx ON releases(release_at);
CREATE TRIGGER releases_append_only BEFORE UPDATE OR DELETE ON releases
    FOR EACH ROW EXECUTE FUNCTION mios_forbid_mutation();

-- ------------------------------------------------------ economic_calendar
-- What is coming, and when. Deliberately NOT append-only: a schedule is a
-- statement about the future and publishers move dates. This is the one
-- table where updating in place is correct, because nothing downstream
-- reconstructs history from it — the record of what actually happened
-- lives in releases and observations.
--
-- It is also why scheduled releases cannot live in `events`: that table
-- requires known_at not to precede occurred_at by more than a day, which a
-- future date violates by construction (audit §4.1 problem C).
CREATE TABLE IF NOT EXISTS economic_calendar (
    calendar_id   text PRIMARY KEY,
    series_id     text REFERENCES series(series_id),  -- NULL for FOMC/BOJ meetings
    event_type    text NOT NULL,                      -- config/taxonomy/events.yaml
    country       text NOT NULL CHECK (country IN ('US','JP','EA','CN','GLOBAL')),
    title         text NOT NULL,
    scheduled_at  timestamptz NOT NULL,
    period        date,                               -- reference period being published
    importance    smallint NOT NULL CHECK (importance BETWEEN 1 AND 5),
    status        text NOT NULL DEFAULT 'scheduled'
                  CHECK (status IN ('scheduled','released','cancelled')),
    release_id    text REFERENCES releases(release_id),
    source_id     text NOT NULL REFERENCES sources(source_id),
    source_url    text NOT NULL DEFAULT '',
    updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS calendar_scheduled_idx ON economic_calendar(scheduled_at);
CREATE INDEX IF NOT EXISTS calendar_status_idx ON economic_calendar(status);

-- --------------------------------------------------------- normalize_state
-- Which raw items have already been turned into observations. Lets
-- `mios normalize` be re-run safely and keeps re-parsing proportional to
-- new data rather than to all history.
CREATE TABLE IF NOT EXISTS normalize_state (
    raw_item_id   text PRIMARY KEY,
    series_id     text NOT NULL REFERENCES series(series_id),
    processed_at  timestamptz NOT NULL DEFAULT now(),
    written       integer NOT NULL DEFAULT 0,   -- observations actually written
    skipped       integer NOT NULL DEFAULT 0    -- unchanged values, correctly not rewritten
);
