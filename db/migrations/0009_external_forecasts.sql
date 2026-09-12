-- 0009: What everyone else thinks, stored the same way MIOS's own opinion is.
--
-- `forecast_errors` answers "did the drivers beat doing nothing?". That is
-- the right first question and a very low bar: the naive baseline is beaten
-- routinely by anyone paying attention, so clearing it proves little. The
-- question that decides whether this project was worth building is "did it
-- beat what was already publicly known?" — and that needs the publicly
-- known number stored, at the moment it was knowable, and never rewritten.
--
-- Institutions revise their forecasts continuously. The Cleveland Fed's
-- nowcast moves most days. So an external forecast is a vintage series in
-- exactly the way MIOS's own forecasts are, and gets the same treatment:
-- one row per publication, append-only, no updates.
--
-- The comparison this table makes possible is only fair if both sides were
-- formed from the same information. That is what `vintage_at` is for, and
-- why it is separate from `published_at` — see the column comments.

CREATE TABLE IF NOT EXISTS external_forecasts (
    -- xf_<published day>_<provider>-<target slug>-<period>
    external_forecast_id text PRIMARY KEY,
    provider_id      text NOT NULL REFERENCES sources(source_id),
    target_series_id text NOT NULL REFERENCES series(series_id),
    target_period    date NOT NULL,

    -- When the institution published this figure. Theirs, from the payload.
    published_at     timestamptz NOT NULL,
    -- When MIOS could first have known it: the retrieval time of the fetch
    -- that carried it. Never earlier than reality, and that asymmetry is
    -- deliberate. Backfilling a year of nowcast history gives rows whose
    -- published_at is old and whose vintage_at is today, and a comparison
    -- keyed on published_at would credit MIOS with knowing them all along.
    -- Every leak-free read filters on vintage_at.
    vintage_at       timestamptz NOT NULL,

    -- The forecast converted into the target's own forecasting units — the
    -- same transform MIOS's point_value uses, so the two are subtractable
    -- without a conversion sitting in the comparison code.
    point_value      numeric NOT NULL,
    -- As published, before that conversion, with the unit the publisher
    -- used. Kept because a scale error in the conversion is otherwise
    -- undetectable after the fact: this column is what makes it checkable.
    raw_value        numeric NOT NULL,
    raw_unit         text NOT NULL,

    -- Tier 1 means a central bank or statistical agency publishing its own
    -- projection. An aggregator's republication of a survey is not that,
    -- and the tier is copied here so a comparison can be read without
    -- joining back to the source registry.
    tier             smallint NOT NULL CHECK (tier BETWEEN 1 AND 4),
    method           text NOT NULL DEFAULT '',  -- what the publisher calls it
    source_url       text NOT NULL,             -- 指示書 §26: always recoverable
    raw_item_id      text,                      -- the payload this came from
    created_at       timestamptz NOT NULL DEFAULT now(),

    -- One publication per provider, per target, per period. A re-fetch of
    -- the same publication is a no-op; a genuinely new publication is a new
    -- row. There is no path that edits one.
    UNIQUE (provider_id, target_series_id, target_period, published_at)
);
CREATE INDEX IF NOT EXISTS external_forecasts_target_idx
    ON external_forecasts(target_series_id, target_period, vintage_at);
CREATE INDEX IF NOT EXISTS external_forecasts_vintage_idx ON external_forecasts(vintage_at);
CREATE TRIGGER external_forecasts_append_only BEFORE UPDATE OR DELETE ON external_forecasts
    FOR EACH ROW EXECUTE FUNCTION mios_forbid_mutation();


-- --------------------------------------------------------------------------
-- Scoring the outside forecasters on exactly the terms MIOS scores itself.
--
-- Same first print, same naive baseline, same skill definition. If the two
-- scoring paths used different actuals or different baselines, every
-- comparison drawn from them would be an artefact of that difference — so
-- the baseline here is computed by the same function the forecaster uses.
CREATE TABLE IF NOT EXISTS external_forecast_errors (
    external_forecast_id text PRIMARY KEY REFERENCES external_forecasts(external_forecast_id),
    provider_id       text NOT NULL REFERENCES sources(source_id),
    target_series_id  text NOT NULL REFERENCES series(series_id),
    target_period     date NOT NULL,

    actual            numeric NOT NULL,   -- first print, as in forecast_errors
    actual_vintage_at timestamptz NOT NULL,

    point_value       numeric NOT NULL,
    -- The naive baseline as it stood at this forecast's vintage_at — not
    -- the one MIOS happened to store that day. Recomputing it at the right
    -- instant is what keeps `skill` comparable across the two tables.
    baseline_value    numeric NOT NULL,

    error             numeric NOT NULL,
    abs_error         numeric NOT NULL,
    baseline_error    numeric NOT NULL,
    skill             numeric NOT NULL,
    direction_hit     boolean,
    days_ahead        integer NOT NULL,
    scored_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS external_forecast_errors_target_idx
    ON external_forecast_errors(target_series_id, target_period);
CREATE INDEX IF NOT EXISTS external_forecast_errors_provider_idx
    ON external_forecast_errors(provider_id, days_ahead);
CREATE TRIGGER external_forecast_errors_append_only
    BEFORE UPDATE OR DELETE ON external_forecast_errors
    FOR EACH ROW EXECUTE FUNCTION mios_forbid_mutation();
