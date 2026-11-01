CREATE TABLE IF NOT EXISTS us_knowledge_documents (
 id text PRIMARY KEY,
 source_url text NOT NULL,
 published_at timestamptz,
 received_at timestamptz NOT NULL,
 topics jsonb NOT NULL,
 document jsonb NOT NULL,
 content_sha256 text NOT NULL,
 stored_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS us_knowledge_published_idx ON us_knowledge_documents(published_at);
CREATE INDEX IF NOT EXISTS us_knowledge_topics_idx ON us_knowledge_documents USING gin(topics);
