-- 0004: Virtual portfolio (IES §13.3) + alerts (append-only event log).

CREATE TABLE IF NOT EXISTS virtual_positions (
    asset_id      text PRIMARY KEY,
    units         numeric NOT NULL DEFAULT 0,
    avg_price_usd numeric,
    updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS virtual_trades (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    decision_id   text NOT NULL REFERENCES decisions(decision_id),
    asset_id      text NOT NULL,
    ts            timestamptz NOT NULL,
    action        text NOT NULL CHECK (action IN ('BUY','TAKE_PROFIT')),
    price_usd     numeric NOT NULL,
    units         numeric NOT NULL,
    UNIQUE (decision_id)
);
CREATE TRIGGER virtual_trades_append_only BEFORE UPDATE OR DELETE ON virtual_trades
    FOR EACH ROW EXECUTE FUNCTION bios_forbid_mutation();

CREATE TABLE IF NOT EXISTS alerts (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts          timestamptz NOT NULL DEFAULT now(),
    asset_id    text NOT NULL,
    severity    text NOT NULL CHECK (severity IN ('info','warning','critical')),
    category    text NOT NULL,   -- signal | breaker | invalidation | data_gap
    message     text NOT NULL,
    ref         text            -- e.g. decision_id, source_id, signal_id
);
CREATE TRIGGER alerts_append_only BEFORE UPDATE OR DELETE ON alerts
    FOR EACH ROW EXECUTE FUNCTION bios_forbid_mutation();
