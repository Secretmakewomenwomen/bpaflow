CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS uploaded_file (
  id BIGSERIAL PRIMARY KEY,
  file_name VARCHAR(255) NOT NULL,
  file_ext VARCHAR(32) NOT NULL,
  mime_type VARCHAR(128) NOT NULL,
  file_size BIGINT NOT NULL,
  oss_bucket VARCHAR(128) NOT NULL,
  oss_key VARCHAR(512) NOT NULL UNIQUE,
  public_url VARCHAR(1024) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'UPLOADED',
  vector_status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
  vector_error VARCHAR(1024) NULL,
  chunk_count INT NOT NULL DEFAULT 0,
  text_vector_status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
  text_vector_error VARCHAR(1024) NULL,
  text_chunk_count INT NOT NULL DEFAULT 0,
  image_vector_status VARCHAR(32) NULL,
  image_vector_error VARCHAR(1024) NULL,
  image_chunk_count INT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  vectorized_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS idx_uploaded_file_created_at ON uploaded_file (created_at);
CREATE INDEX IF NOT EXISTS idx_uploaded_file_vector_status ON uploaded_file (vector_status);
CREATE INDEX IF NOT EXISTS idx_uploaded_file_text_vector_status ON uploaded_file (text_vector_status);
CREATE INDEX IF NOT EXISTS idx_uploaded_file_image_vector_status ON uploaded_file (image_vector_status);
