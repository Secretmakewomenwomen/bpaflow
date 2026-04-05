\set pgvector_text_table 'uploaded_file_text_vector'

CREATE EXTENSION IF NOT EXISTS pg_search;

SELECT format(
  'CREATE INDEX CONCURRENTLY IF NOT EXISTS %I ON %I USING bm25 (id, file_id, file_name, small_chunk_index, created_at, small_chunk_text) WITH (key_field = %L)',
  'idx_' || :'pgvector_text_table' || '_bm25',
  :'pgvector_text_table',
  'id'
) \gexec
