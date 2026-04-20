BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS rag_embeddings (
    id          BIGSERIAL PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    chunk_index INT  NOT NULL,
    content     TEXT NOT NULL,
    embedding   vector(768),
    metadata    JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS rag_embeddings_hnsw_idx
    ON rag_embeddings USING hnsw (embedding vector_cosine_ops);

CREATE UNIQUE INDEX IF NOT EXISTS rag_embeddings_upsert_idx
    ON rag_embeddings (source_type, source_id, chunk_index);

COMMIT;
