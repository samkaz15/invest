-- 0006: Predictions — the table without which none of this can be checked.
--
-- BIOS could score a trade. It could not answer "what did we think August
-- CPI would be, ten days before it printed?", because nothing stored a
-- prediction (docs/REPOSITORY_AUDIT.md §4.1 problem B). That question is
-- the whole point of MIOS, and answering it requires one row per forecast
-- per day, never overwritten (CONSTITUTION.md Art.6-4).
--
-- The append-only trigger plus the natural key do the enforcing: a second
-- forecast for the same target on the same day is refused, and no forecast
-- can ever be edited. Re-running the daily job is therefore safe and
-- cannot quietly rewrite yesterday's opinion.

CREATE TABLE IF NOT EXISTS predictions (
    -- fc_<predicted day>_<target slug>-<period>, e.g.
    -- fc_2026-09-12_us-core-cpi-index-2026-08
    forecast_id      text PRIMARY KEY,
    target_series_id text NOT NULL REFERENCES series(series_id),
    target_period    date NOT NULL,          -- the reference period being forecast
    predicted_at     timestamptz NOT NULL,   -- when this opinion was formed
    -- The data cutoff the forecast was built from. Equal to predicted_at in
    -- live running, earlier when replaying history — which is what makes a
    -- backtested forecast comparable to a live one.
    as_of            timestamptz NOT NULL,

    point_value      numeric,                -- the forecast, in the target series' unit
    -- The naive benchmark for the same period, computed from the same
    -- as-of data. Stored rather than recomputed later, because "did we beat
    -- the trivial answer?" must be answerable from the row itself
    -- (docs/EVALUATION.md §3).
    baseline_value   numeric,

    -- P(actual lands above / below the baseline). Derived from the
    -- historical spread of this method's own baseline errors, so they mean
    -- something measurable rather than expressing a mood. NULL when there
    -- is too little history to say — which is a real answer.
    upside_prob      numeric CHECK (upside_prob BETWEEN 0 AND 1),
    downside_prob    numeric CHECK (downside_prob BETWEEN 0 AND 1),
    confidence       numeric NOT NULL CHECK (confidence BETWEEN 0 AND 1),

    method_version   text NOT NULL,          -- stamped so old forecasts stay interpretable
    -- Every input: series, value, weight, contribution. A forecast whose
    -- arithmetic cannot be replayed from its own row is exactly the kind of
    -- untraceable score this project deleted from BIOS.
    drivers          jsonb NOT NULL DEFAULT '[]',
    contradictions   jsonb NOT NULL DEFAULT '[]',  -- drivers pointing against the net call
    data_gaps        jsonb NOT NULL DEFAULT '[]',  -- inputs that were missing, named
    created_at       timestamptz NOT NULL DEFAULT now(),

    UNIQUE (target_series_id, target_period, predicted_at)
);
CREATE INDEX IF NOT EXISTS predictions_target_idx
    ON predictions(target_series_id, target_period, predicted_at);
CREATE INDEX IF NOT EXISTS predictions_predicted_at_idx ON predictions(predicted_at);
CREATE TRIGGER predictions_append_only BEFORE UPDATE OR DELETE ON predictions
    FOR EACH ROW EXECUTE FUNCTION mios_forbid_mutation();
