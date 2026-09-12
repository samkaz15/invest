-- 0008: Macro scores — the dimension readings and the two asset views.
--
-- Append-only, unlike the BIOS-era dimension_reports it replaces. That
-- table upserted on (asset, dimension, as_of), so recomputing overwrote
-- what the system had thought (docs/REPOSITORY_AUDIT.md §14 L3) and "what
-- did the analysis say on the 5th?" had no answer. Here a recomputation at
-- a new as_of is a new row and the old reading stands.

CREATE TABLE IF NOT EXISTS macro_scores (
    -- sc_<as-of day>_<dimension>, e.g. sc_2026-09-12_inflation
    score_id       text PRIMARY KEY,
    dimension      text NOT NULL,
    as_of          timestamptz NOT NULL,   -- the data cutoff this was built from
    computed_at    timestamptz NOT NULL DEFAULT now(),

    score          numeric NOT NULL CHECK (score BETWEEN -100 AND 100),
    -- What the score means in words for this dimension: hawkish/dovish for
    -- a central bank, bullish/bearish for an asset view. Stored rather than
    -- derived on read so the wording cannot drift away from the number.
    stance         text NOT NULL,
    confidence     numeric NOT NULL CHECK (confidence BETWEEN 0 AND 1),

    -- Every input: series, reading, weight, points, and a sentence. "Why is
    -- this +0.8?" has to be answerable from this row alone — the rule that
    -- deleted BIOS's scoring engine applies to its replacement too.
    signals        jsonb NOT NULL DEFAULT '[]',
    -- Inputs pulling against the net reading. Surfaced, never averaged away.
    contradictions jsonb NOT NULL DEFAULT '[]',
    data_gaps      jsonb NOT NULL DEFAULT '[]',
    -- What this score structurally cannot see: central-bank gold buying,
    -- MOF intervention, geopolitical risk premium. A yield-and-dollar model
    -- of gold is not wrong, it is incomplete, and a reader who is not told
    -- which will mistake silence for absence.
    blind_spots    jsonb NOT NULL DEFAULT '[]',

    method_version text NOT NULL,
    UNIQUE (dimension, as_of)
);
CREATE INDEX IF NOT EXISTS macro_scores_dimension_idx ON macro_scores(dimension, as_of DESC);
CREATE TRIGGER macro_scores_append_only BEFORE UPDATE OR DELETE ON macro_scores
    FOR EACH ROW EXECUTE FUNCTION mios_forbid_mutation();
