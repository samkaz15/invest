-- 0010: The calendar says when, and how well it knows when.
--
-- FRED's release-dates endpoint returns a *date*, not an instant. The BLS
-- publishes CPI at 08:30 America/New_York; FRED will tell you it is the
-- 15th and nothing more. Those are two different states of knowledge and
-- storing them in one timestamptz column would silently turn the second
-- into the first — every date-only entry would read as midnight UTC, which
-- is a claim nobody made and which sorts wrongly against entries that do
-- know their time.
--
-- So the precision is recorded. Entries whose publication time is stated in
-- config/calendar.yaml are 'exact'; everything else is 'date_only' and is
-- displayed as a day rather than as a time.
--
-- economic_calendar stays the one mutable table here: a schedule is a claim
-- about the future, and publishers move dates. It carries no append-only
-- trigger for that reason, unlike every table holding a measured value.

ALTER TABLE economic_calendar
    ADD COLUMN IF NOT EXISTS time_precision text NOT NULL DEFAULT 'date_only'
        CHECK (time_precision IN ('exact', 'date_only'));

-- The publisher's own id for the release (FRED's numeric release_id, say).
-- Kept so a stored row can be traced back to the payload that produced it,
-- and so re-fetching the same schedule updates the same row instead of
-- appending a second copy of the same event.
ALTER TABLE economic_calendar
    ADD COLUMN IF NOT EXISTS provider_release_id text;

-- One row per (provider release, scheduled day, series). Re-running the
-- collector must update a moved date rather than leave both.
CREATE UNIQUE INDEX IF NOT EXISTS economic_calendar_provider_idx
    ON economic_calendar(source_id, provider_release_id, scheduled_at, COALESCE(series_id, ''));
CREATE INDEX IF NOT EXISTS economic_calendar_scheduled_idx
    ON economic_calendar(scheduled_at);


-- --------------------------------------------------------------------------
-- What a stored release's numbers actually mean.
--
-- `releases` has held actual / forecast / previous since migration 0005 with
-- nothing saying what unit they are in, because nothing wrote to it. Now
-- that something does, the unit has to be on the row: a CPI release can
-- honestly be reported as an index level (316.5) or as a month-over-month
-- change (0.0028), and a reader who guesses wrong is out by two orders of
-- magnitude. The same ambiguity in `surprise` would be worse, because a
-- surprise is small by construction and a wrong unit still looks plausible.
--
-- MIOS stores the published figure as published — the level — and derives
-- the change at export time from two stored levels, so the derivation stays
-- reproducible rather than becoming a second stored truth that can drift.
ALTER TABLE releases
    ADD COLUMN IF NOT EXISTS basis text NOT NULL DEFAULT 'level'
        CHECK (basis IN ('level', 'pct_change', 'diff'));
