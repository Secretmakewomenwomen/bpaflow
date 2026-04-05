ALTER TABLE uploaded_file
  ADD COLUMN IF NOT EXISTS vector_status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
  ADD COLUMN IF NOT EXISTS vector_error VARCHAR(1024) NULL,
  ADD COLUMN IF NOT EXISTS chunk_count INT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS vectorized_at TIMESTAMPTZ NULL;

CREATE INDEX IF NOT EXISTS idx_uploaded_file_vector_status
  ON uploaded_file (vector_status);
