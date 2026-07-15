-- 0001: Core knowledge schema (MASTER_SYSTEM_DESIGN §13).
-- Append-only discipline is enforced IN THE DATABASE: events, evidences,
-- event_relations, audit_log and agent_runs refuse UPDATE/DELETE via trigger.
-- Corrections happen by inserting superseding rows (Constitution Art.3).
-- NOTE: no BEGIN/COMMIT here — the migration runner wraps each file in a
-- transaction together with its schema_migrations bookkeeping row.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     text PRIMARY KEY,
    applied_at  timestamptz NOT NULL DEFAULT now()
);

-- Refusal trigger shared by all append-only tables.
CREATE OR REPLACE FUNCTION bios_forbid_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'table % is append-only (BIOS Constitution Art.3): % refused',
        TG_TABLE_NAME, TG_OP;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------- sources
-- Synced from config/sources/*.yaml (YAML is the source of truth).
CREATE TABLE IF NOT EXISTS sources (
    source_id   text PRIMARY KEY,
    name        text NOT NULL,
    kind        text NOT NULL,
    tier        smallint NOT NULL CHECK (tier BETWEEN 1 AND 4),
    enabled     boolean NOT NULL,
    notes       text NOT NULL DEFAULT '',
    synced_at   timestamptz NOT NULL DEFAULT now()
);

-- --------------------------------------------------------------- entities
CREATE TABLE IF NOT EXISTS entities (
    entity_id    text PRIMARY KEY,
    kind         text NOT NULL,
    name         text NOT NULL,
    aliases      jsonb NOT NULL DEFAULT '[]',
    identifiers  jsonb NOT NULL DEFAULT '{}',
    attributes   jsonb NOT NULL DEFAULT '{}',
    confidence   text NOT NULL DEFAULT 'verified',
    merged_into  text REFERENCES entities(entity_id),
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS entities_kind_idx ON entities(kind);

-- ----------------------------------------------------------- event_chains
CREATE TABLE IF NOT EXISTS event_chains (
    chain_id         text PRIMARY KEY,
    title            text NOT NULL,
    chain_type       text NOT NULL,
    parent_chain_id  text REFERENCES event_chains(chain_id),
    status           text NOT NULL CHECK (status IN ('active','dormant','closed')),
    started_at       date,
    closed_at        date,
    milestones       jsonb NOT NULL DEFAULT '[]',
    watch_points     jsonb NOT NULL DEFAULT '[]',
    summary          text NOT NULL DEFAULT '',
    updated_at       timestamptz NOT NULL DEFAULT now()
);

-- ----------------------------------------------------------------- events
CREATE TABLE IF NOT EXISTS events (
    event_id        text PRIMARY KEY,
    schema_version  smallint NOT NULL DEFAULT 2,
    status          text NOT NULL CHECK (status IN ('candidate','confirmed','corrected','retracted')),
    supersedes      text REFERENCES events(event_id),
    type            text NOT NULL,
    title           text NOT NULL,
    summary_fact    text NOT NULL,
    occurred_at     timestamptz NOT NULL,
    known_at        timestamptz NOT NULL,
    recorded_at     timestamptz NOT NULL DEFAULT now(),
    ended_at        timestamptz,
    time_precision  text NOT NULL CHECK (time_precision IN ('minute','hour','day','month')),
    chain_id        text REFERENCES event_chains(chain_id),
    confidence      text NOT NULL CHECK (confidence IN ('verified','reported','disputed')),
    magnitude_initial smallint CHECK (magnitude_initial BETWEEN 1 AND 5),
    assets          jsonb NOT NULL DEFAULT '[]',
    tags            jsonb NOT NULL DEFAULT '[]',
    curation        jsonb NOT NULL DEFAULT '{}',
    CHECK (known_at >= occurred_at - interval '1 day')  -- sanity: markets can't know far before it happened
);
CREATE INDEX IF NOT EXISTS events_known_at_idx ON events(known_at);
CREATE INDEX IF NOT EXISTS events_type_idx ON events(type);
CREATE INDEX IF NOT EXISTS events_chain_idx ON events(chain_id);
CREATE TRIGGER events_append_only BEFORE UPDATE OR DELETE ON events
    FOR EACH ROW EXECUTE FUNCTION bios_forbid_mutation();

-- -------------------------------------------------------------- evidences
CREATE TABLE IF NOT EXISTS evidences (
    evidence_id   text PRIMARY KEY,
    raw_item_id   text,                         -- file raw store reference (Phase 1)
    source_id     text NOT NULL REFERENCES sources(source_id),
    tier          smallint NOT NULL CHECK (tier BETWEEN 1 AND 4),
    url           text,
    archived_url  text,
    quote         text NOT NULL DEFAULT '',
    published_at  timestamptz,
    retrieved_at  timestamptz NOT NULL
);
CREATE TRIGGER evidences_append_only BEFORE UPDATE OR DELETE ON evidences
    FOR EACH ROW EXECUTE FUNCTION bios_forbid_mutation();

-- Event <-> Evidence link. "No FACT without evidence" is enforced at the
-- repository layer inside the insert transaction (SQL alone cannot demand
-- a child row); the QA audit re-checks it nightly.
CREATE TABLE IF NOT EXISTS event_evidences (
    event_id     text NOT NULL REFERENCES events(event_id),
    evidence_id  text NOT NULL REFERENCES evidences(evidence_id),
    PRIMARY KEY (event_id, evidence_id)
);

-- ---------------------------------------------------- event_participations
CREATE TABLE IF NOT EXISTS event_participations (
    event_id   text NOT NULL REFERENCES events(event_id),
    entity_id  text NOT NULL REFERENCES entities(entity_id),
    role       text NOT NULL CHECK (role IN ('actor','target','counterparty','venue','affected','mentioned')),
    detail     text NOT NULL DEFAULT '',
    PRIMARY KEY (event_id, entity_id, role)
);
CREATE INDEX IF NOT EXISTS participations_entity_idx ON event_participations(entity_id);

-- --------------------------------------------------------- event_relations
CREATE TABLE IF NOT EXISTS event_relations (
    from_event  text NOT NULL REFERENCES events(event_id),
    to_event    text NOT NULL REFERENCES events(event_id),
    rel_type    text NOT NULL CHECK (rel_type IN
        ('TRIGGERED_BY','CAUSED_BY_BG','PART_OF','PRECEDES','SIMILAR_TO',
         'INVALIDATES','AMPLIFIES','OFFSETS','FOLLOWS_PATTERN')),
    confidence  real CHECK (confidence BETWEEN 0 AND 1),
    evidence_id text REFERENCES evidences(evidence_id),
    created_by  text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (from_event, to_event, rel_type),
    CHECK (from_event <> to_event),
    -- Causal edges without evidence are forbidden (MSD §6.3).
    CHECK (rel_type NOT IN ('TRIGGERED_BY','CAUSED_BY_BG')
           OR (evidence_id IS NOT NULL AND confidence IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS relations_to_idx ON event_relations(to_event);
CREATE TRIGGER relations_append_only BEFORE UPDATE OR DELETE ON event_relations
    FOR EACH ROW EXECUTE FUNCTION bios_forbid_mutation();

-- ---------------------------------------------------------- curation_queue
CREATE TABLE IF NOT EXISTS curation_queue (
    candidate_id  text PRIMARY KEY,
    created_at    timestamptz NOT NULL DEFAULT now(),
    source_id     text NOT NULL,
    kind          text NOT NULL DEFAULT 'news',
    payload       jsonb NOT NULL,
    dedupe_key    text NOT NULL UNIQUE,          -- e.g. article link hash
    status        text NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','approved','rejected')),
    reviewed_at   timestamptz,
    review_note   text NOT NULL DEFAULT '',
    event_id      text REFERENCES events(event_id)
);
CREATE INDEX IF NOT EXISTS curation_status_idx ON curation_queue(status);

-- -------------------------------------------------------- market_snapshots
-- Plain table for now; TimescaleDB hypertable when volume demands (D10).
CREATE TABLE IF NOT EXISTS market_snapshots (
    asset_id       text NOT NULL,
    ts             timestamptz NOT NULL,
    price_usd      numeric,
    volume_24h_usd numeric,
    asset_metrics  jsonb NOT NULL DEFAULT '{}',
    macro_context  jsonb NOT NULL DEFAULT '{}',
    sources        jsonb NOT NULL DEFAULT '{}',   -- metric -> raw_item_id provenance
    PRIMARY KEY (asset_id, ts)
);

-- ------------------------------------------------------------- audit sinks
CREATE TABLE IF NOT EXISTS audit_log (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts          timestamptz NOT NULL,
    actor_kind  text NOT NULL,
    actor       text NOT NULL,
    action      text NOT NULL,
    target      text NOT NULL,
    detail      jsonb NOT NULL DEFAULT '{}'
);
CREATE TRIGGER audit_log_append_only BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION bios_forbid_mutation();

CREATE TABLE IF NOT EXISTS agent_runs (
    run_id          text PRIMARY KEY,
    agent           text NOT NULL,
    started_at      timestamptz NOT NULL,
    ended_at        timestamptz NOT NULL,
    prompt_version  text NOT NULL,
    model           text NOT NULL,
    status          text NOT NULL,
    input_refs      jsonb NOT NULL DEFAULT '[]',
    output_refs     jsonb NOT NULL DEFAULT '[]',
    tokens_in       integer NOT NULL DEFAULT 0,
    tokens_out      integer NOT NULL DEFAULT 0,
    cost_usd        numeric NOT NULL DEFAULT 0,
    schema_validation boolean NOT NULL DEFAULT true,
    error           text
);
CREATE TRIGGER agent_runs_append_only BEFORE UPDATE OR DELETE ON agent_runs
    FOR EACH ROW EXECUTE FUNCTION bios_forbid_mutation();

-- Extraction bookkeeping: which raw items were already processed.
CREATE TABLE IF NOT EXISTS extraction_state (
    raw_item_id  text PRIMARY KEY,
    processed_at timestamptz NOT NULL DEFAULT now()
);
