ALTER TABLE uploaded_file
  ADD COLUMN IF NOT EXISTS text_vector_status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
  ADD COLUMN IF NOT EXISTS text_vector_error VARCHAR(1024) NULL,
  ADD COLUMN IF NOT EXISTS text_chunk_count INT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS image_vector_status VARCHAR(32) NULL,
  ADD COLUMN IF NOT EXISTS image_vector_error VARCHAR(1024) NULL,
  ADD COLUMN IF NOT EXISTS image_chunk_count INT NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_uploaded_file_text_vector_status
  ON uploaded_file (text_vector_status);

CREATE INDEX IF NOT EXISTS idx_uploaded_file_image_vector_status
  ON uploaded_file (image_vector_status);
