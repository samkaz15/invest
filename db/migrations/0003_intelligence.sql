-- 0003: Intelligence layer — regimes (derived), score cards / scenario sets /
-- decisions / decision outcomes (append-only judgment history, Art.6).

CREATE TABLE IF NOT EXISTS regimes (
    asset_id   text NOT NULL,
    date       date NOT NULL,
    trend      text NOT NULL,   -- bull | bear | range | unknown
    vol        text NOT NULL,   -- low | normal | high | unknown
    liquidity  text NOT NULL,   -- easing | neutral | tightening | unknown
    version    text NOT NULL,
    computed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (asset_id, date)
);

CREATE TABLE IF NOT EXISTS score_cards (
    score_card_id     text PRIMARY KEY,
    asset_id          text NOT NULL,
    as_of             timestamptz NOT NULL,
    composite         smallint NOT NULL CHECK (composite BETWEEN -100 AND 100),
    verdict_hint      text NOT NULL,
    conflict_index    real NOT NULL CHECK (conflict_index BETWEEN 0 AND 1),
    data_completeness real NOT NULL CHECK (data_completeness BETWEEN 0 AND 1),
    weights_version   text NOT NULL,
    phase             jsonb NOT NULL DEFAULT '{}',
    dimensions        jsonb NOT NULL DEFAULT '[]'
);
CREATE TRIGGER score_cards_append_only BEFORE UPDATE OR DELETE ON score_cards
    FOR EACH ROW EXECUTE FUNCTION bios_forbid_mutation();

CREATE TABLE IF NOT EXISTS scenario_sets (
    scenario_set_id text PRIMARY KEY,
    asset_id        text NOT NULL,
    as_of           timestamptz NOT NULL,
    scenarios       jsonb NOT NULL,   -- probabilities validated to sum 1.0 in code
    method_version  text NOT NULL,
    base_rate_note  text NOT NULL DEFAULT ''
);
CREATE TRIGGER scenario_sets_append_only BEFORE UPDATE OR DELETE ON scenario_sets
    FOR EACH ROW EXECUTE FUNCTION bios_forbid_mutation();

CREATE TABLE IF NOT EXISTS decisions (
    decision_id      text PRIMARY KEY,
    asset_id         text NOT NULL,
    as_of            timestamptz NOT NULL,
    action           text NOT NULL CHECK (action IN ('BUY','WAIT','TAKE_PROFIT')),
    conviction       real NOT NULL CHECK (conviction BETWEEN 0 AND 1),
    rationale        text NOT NULL,
    rationale_refs   jsonb NOT NULL DEFAULT '[]',
    counter_argument text NOT NULL,
    invalidation     jsonb NOT NULL,   -- {condition, check} — mandatory by schema
    risk_note        text NOT NULL,
    delta_from_yesterday text NOT NULL DEFAULT '',
    score_card_id    text NOT NULL REFERENCES score_cards(score_card_id),
    scenario_set_id  text NOT NULL REFERENCES scenario_sets(scenario_set_id),
    engine_version   text NOT NULL
);
CREATE TRIGGER decisions_append_only BEFORE UPDATE OR DELETE ON decisions
    FOR EACH ROW EXECUTE FUNCTION bios_forbid_mutation();

CREATE TABLE IF NOT EXISTS decision_outcomes (
    decision_id  text NOT NULL REFERENCES decisions(decision_id),
    horizon      text NOT NULL CHECK (horizon IN ('+1d','+7d','+30d','+90d')),
    return       real NOT NULL,
    verdict      text NOT NULL CHECK (verdict IN ('correct','incorrect','neutral')),
    scored_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (decision_id, horizon)
);
CREATE TRIGGER decision_outcomes_append_only BEFORE UPDATE OR DELETE ON decision_outcomes
    FOR EACH ROW EXECUTE FUNCTION bios_forbid_mutation();
