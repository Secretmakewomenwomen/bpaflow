# Upload And Dual-Channel Vectorization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single-file upload system with immediate upload success, text-channel vectorization for `docx` / `pdf` / `png`, image-channel vectorization for `png`, and dual Milvus collections with HNSW indexing.

**Architecture:** Keep the upload path lightweight: validate file, upload to OSS, write `uploaded_file`, and return success immediately. After the response, run an in-process background task that routes files into a text channel and, for `png`, an additional image channel. The text channel parses, cleans, chunks, embeds, and writes to a Milvus text collection. The image channel calls ARK multimodal embeddings and writes to a separate Milvus image collection. Upload state in MySQL records both channel-specific status and aggregate status.

**Tech Stack:** Vue 3, TypeScript, Rsbuild, Vitest, Python 3, FastAPI, SQLAlchemy, PyMySQL, Alibaba Cloud OSS SDK, PyPDF, python-docx, Pillow, pytesseract, OpenAI-compatible ARK text embedding client, ARK runtime multimodal client, pymilvus

---

### Task 1: Extend Upload Metadata For Dual-Channel Status

**Files:**
- Create: `backend/sql/003_add_dual_channel_vector_fields.sql`
- Modify: `backend/app/models/upload.py`
- Modify: `backend/app/schemas/upload.py`
- Modify: `backend/app/core/database.py`
- Test: `backend/tests/test_database_schema.py`
- Test: `backend/tests/test_upload_service.py`

- [ ] **Step 1: Write the failing schema/status tests**

Extend tests to assert:
- `text_vector_status`, `text_vector_error`, `text_chunk_count` exist
- `image_vector_status`, `image_vector_error`, `image_chunk_count` exist
- `png` uploads start with both channels at `PENDING`

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && pytest tests/test_database_schema.py tests/test_upload_service.py -q`
Expected: FAIL because dual-channel fields are not modeled yet.

- [ ] **Step 3: Add the SQL migration**

Create `backend/sql/003_add_dual_channel_vector_fields.sql` with:

```sql
ALTER TABLE uploaded_file
  ADD COLUMN text_vector_status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
  ADD COLUMN text_vector_error VARCHAR(1024) NULL,
  ADD COLUMN text_chunk_count INT NOT NULL DEFAULT 0,
  ADD COLUMN image_vector_status VARCHAR(32) NULL,
  ADD COLUMN image_vector_error VARCHAR(1024) NULL,
  ADD COLUMN image_chunk_count INT NOT NULL DEFAULT 0,
  ADD KEY idx_uploaded_file_text_vector_status (text_vector_status),
  ADD KEY idx_uploaded_file_image_vector_status (image_vector_status);
```

- [ ] **Step 4: Implement model, schema, and startup auto-migration changes**

Update:
- `backend/app/models/upload.py`
- `backend/app/schemas/upload.py`
- `backend/app/core/database.py`

Add the new columns and extend startup schema repair for existing MySQL tables.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && pytest tests/test_database_schema.py tests/test_upload_service.py -q`
Expected: PASS.

### Task 2: Add Aggregate Status Rules

**Files:**
- Create: `backend/app/services/status_service.py`
- Create: `backend/tests/test_status_service.py`
- Modify: `backend/app/services/vectorization_service.py`

- [ ] **Step 1: Write the failing aggregate-status test**

Create `backend/tests/test_status_service.py` covering:
- `docx` / `pdf` aggregate follows text channel only
- `png` becomes `VECTORIZED` only when both channels succeed
- `png` becomes `FAILED` if either channel fails
- `png` remains `PROCESSING` while one channel is still running

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest tests/test_status_service.py -q`
Expected: FAIL because aggregate-status logic does not exist.

- [ ] **Step 3: Implement status aggregation**

Create `backend/app/services/status_service.py` with a small pure function layer for channel-to-aggregate mapping.

- [ ] **Step 4: Wire aggregate-status updates into vectorization orchestration**

Update `backend/app/services/vectorization_service.py` to use the status service instead of hardcoded aggregate transitions.

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd backend && pytest tests/test_status_service.py -q`
Expected: PASS.

### Task 3: Split Milvus Into Text And Image Collections

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/.env.example`
- Modify: `backend/app/services/milvus_service.py`
- Create: `backend/tests/test_milvus_service.py`

- [ ] **Step 1: Write the failing Milvus config test**

Create `backend/tests/test_milvus_service.py` covering:
- text collection uses text dimension
- image collection uses image dimension
- both collections use HNSW
- delete/replace is routed to the correct collection

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest tests/test_milvus_service.py -q`
Expected: FAIL because Milvus service only supports one collection.

- [ ] **Step 3: Extend config for dual collections**

Update:
- `backend/app/core/config.py`
- `backend/.env.example`

Add:
- `MILVUS_TEXT_COLLECTION`
- `MILVUS_IMAGE_COLLECTION`
- `MILVUS_TEXT_VECTOR_DIMENSION`
- `MILVUS_IMAGE_VECTOR_DIMENSION`

- [ ] **Step 4: Refactor Milvus service**

Update `backend/app/services/milvus_service.py` to support:
- ensure text collection
- ensure image collection
- replace text vectors by file
- replace image vectors by file

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd backend && pytest tests/test_milvus_service.py -q`
Expected: PASS.

### Task 4: Add ARK Image Embedding Service

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/.env.example`
- Create: `backend/app/services/image_embedding_service.py`
- Create: `backend/tests/test_image_embedding_service.py`

- [ ] **Step 1: Write the failing image-embedding test**

Create `backend/tests/test_image_embedding_service.py` covering:
- ARK multimodal client is called with `type=text` and `type=image_url` or file payload
- returned image vector is normalized if needed
- endpoint id comes from image-channel config

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest tests/test_image_embedding_service.py -q`
Expected: FAIL because image embedding service does not exist.

- [ ] **Step 3: Extend config for multimodal endpoint**

Update:
- `backend/app/core/config.py`
- `backend/.env.example`

Add:
- `ARK_MULTIMODAL_EMBEDDING_ENDPOINT_ID`

- [ ] **Step 4: Implement image embedding service**

Create `backend/app/services/image_embedding_service.py` using `volcenginesdkarkruntime.Ark` and `multimodal_embeddings.create(...)`.

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd backend && pytest tests/test_image_embedding_service.py -q`
Expected: PASS.

### Task 5: Extend Text Parsing And Chunking Coverage

**Files:**
- Modify: `backend/app/services/parsing_service.py`
- Modify: `backend/tests/test_parsing_service.py`
- Modify: `backend/tests/test_cleaning_service.py`
- Modify: `backend/tests/test_chunking_service.py`

- [ ] **Step 1: Write the failing regression tests**

Extend tests to cover:
- `docx` table extraction stays intact
- `pdf` OCR fallback still works
- `png` OCR text still enters the text channel

- [ ] **Step 2: Run the tests to verify they fail or protect current behavior**

Run: `cd backend && pytest tests/test_parsing_service.py tests/test_cleaning_service.py tests/test_chunking_service.py -q`
Expected: PASS if behavior is already covered, otherwise add the minimum missing test until behavior is explicit.

- [ ] **Step 3: Keep parsing/chunking interfaces stable**

Only make minimal changes required for the new dual-channel orchestrator to reuse the current text pipeline.

- [ ] **Step 4: Re-run the tests**

Run: `cd backend && pytest tests/test_parsing_service.py tests/test_cleaning_service.py tests/test_chunking_service.py -q`
Expected: PASS.

### Task 6: Refactor Vectorization Orchestrator Into Text And Image Channels

**Files:**
- Modify: `backend/app/services/vectorization_service.py`
- Modify: `backend/app/services/upload_service.py`
- Modify: `backend/tests/test_vectorization_service.py`
- Modify: `backend/tests/test_upload_service.py`

- [ ] **Step 1: Write the failing dual-channel orchestration tests**

Extend `backend/tests/test_vectorization_service.py` to assert:
- `docx` / `pdf` only run the text channel
- `png` runs both text and image channels
- text rows are written to the text collection
- image rows are written to the image collection
- per-channel status and aggregate status update correctly

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && pytest tests/test_vectorization_service.py tests/test_upload_service.py -q`
Expected: FAIL because orchestration is still single-channel.

- [ ] **Step 3: Implement the text channel path**

Keep the current parse → clean → chunk → text embed → text Milvus insert path, but update it to write `text_vector_status`, `text_vector_error`, and `text_chunk_count`.

- [ ] **Step 4: Implement the image channel path**

For `png`, call the new image embedding service, then write rows into the image collection with file metadata and image-channel source type.

- [ ] **Step 5: Implement aggregate completion**

Use the new status service to compute and persist `vector_status`, `vector_error`, and `vectorized_at`.

- [ ] **Step 6: Re-run the tests**

Run: `cd backend && pytest tests/test_vectorization_service.py tests/test_upload_service.py -q`
Expected: PASS.

### Task 7: Keep Upload API Stable

**Files:**
- Modify: `backend/app/api/routes/uploads.py`
- Modify: `backend/tests/test_upload_api.py`

- [ ] **Step 1: Write the failing API compatibility test**

Assert that:
- upload response shape remains backward-compatible
- list response still exposes aggregate `vectorStatus`
- dual-channel backend changes do not change the existing upload contract

- [ ] **Step 2: Run the test to verify it fails only if the contract drifted**

Run: `cd backend && pytest tests/test_upload_api.py -q`
Expected: PASS or a focused FAIL if response mapping needs adjustment.

- [ ] **Step 3: Apply the minimal route/schema changes**

Keep the current frontend contract stable while persisting more backend state internally.

- [ ] **Step 4: Re-run the test**

Run: `cd backend && pytest tests/test_upload_api.py -q`
Expected: PASS.

### Task 8: Update Strategy Documentation

**Files:**
- Modify: `docs/file-vectorization-strategies.md`

- [ ] **Step 1: Update the strategy document**

Document:
- `docx` text-channel strategy
- `pdf` text-channel strategy
- `png` text + image dual-channel strategy
- text and image Milvus collections
- aggregate and per-channel statuses

- [ ] **Step 2: Review the document against the implemented code**

Verify the document matches shipped config names, collection names, and status semantics.

### Task 9: Run Verification

**Files:**
- Modify: `backend/requirements.txt` only if a final dependency correction is needed

- [ ] **Step 1: Run backend tests**

Run: `cd backend && pytest -q`
Expected: PASS.

- [ ] **Step 2: Run frontend tests**

Run: `COREPACK_HOME=/Users/hehuan/Desktop/ai相关/flow_project/.corepack corepack pnpm test`
Expected: PASS.

- [ ] **Step 3: Run frontend build**

Run: `COREPACK_HOME=/Users/hehuan/Desktop/ai相关/flow_project/.corepack corepack pnpm build`
Expected: PASS.
