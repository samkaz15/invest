-- 0007: Forecast errors — the table that decides whether any of this works.
--
-- CONSTITUTION.md Art.2 defines success as being able to answer, in six
-- months, whether MIOS actually helps forecast CPI and NFP. This is where
-- that answer comes from. Everything upstream is machinery for filling it.
--
-- One row per scored forecast, appended once and never revised. A scored
-- error that could be edited is not evidence.

CREATE TABLE IF NOT EXISTS forecast_errors (
    forecast_id       text PRIMARY KEY REFERENCES predictions(forecast_id),
    target_series_id  text NOT NULL REFERENCES series(series_id),
    target_period     date NOT NULL,

    -- The FIRST published figure for the period, not the latest revised
    -- one. A forecaster is predicting what will be printed; scoring against
    -- a number restated three months later marks them against a question
    -- nobody asked, and makes the target move under the scoreboard.
    -- The vintage is kept so which print this was stays checkable.
    actual            numeric NOT NULL,
    actual_vintage_at timestamptz NOT NULL,

    point_value       numeric NOT NULL,
    baseline_value    numeric NOT NULL,

    error             numeric NOT NULL,   -- actual - point   (sign kept: bias is a finding)
    abs_error         numeric NOT NULL,
    baseline_error    numeric NOT NULL,   -- actual - baseline
    -- abs(baseline_error) - abs(error). Positive means the drivers beat the
    -- naive answer on this period. This single column is the closest thing
    -- the project has to a verdict, which is why it is stored rather than
    -- derived differently in five places.
    skill             numeric NOT NULL,

    -- Did the forecast call the correct side of the baseline? NULL when the
    -- forecast made no directional call at all (adjustment of exactly zero),
    -- which is an abstention rather than a wrong answer.
    direction_hit     boolean,
    -- Copied from the forecast so calibration can be computed from this
    -- table alone: P(above baseline) against whether it landed above.
    upside_prob       numeric,

    -- How far out the call was made. The point of storing every daily
    -- vintage: accuracy at 30 days and at 1 day are different questions.
    days_ahead        integer NOT NULL,
    method_version    text NOT NULL,
    scored_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS forecast_errors_target_idx
    ON forecast_errors(target_series_id, target_period);
CREATE INDEX IF NOT EXISTS forecast_errors_horizon_idx ON forecast_errors(days_ahead);
CREATE TRIGGER forecast_errors_append_only BEFORE UPDATE OR DELETE ON forecast_errors
    FOR EACH ROW EXECUTE FUNCTION mios_forbid_mutation();
