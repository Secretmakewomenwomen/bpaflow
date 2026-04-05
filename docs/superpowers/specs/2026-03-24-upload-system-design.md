# Upload And Vectorization System Design

## Overview

This document defines the upload and post-upload vectorization system for the architecture workbench.

The upload entry lives in the top-right area of the frontend as an `Upload` button. Clicking it opens an upload modal. The frontend sends the selected file to the `backend/` FastAPI service. The backend validates the file, uploads it to Alibaba Cloud OSS, writes file metadata into MySQL, returns the uploaded record immediately, and then vectorizes the file asynchronously.

This iteration supports:

- Single-file upload only
- Allowed file types: `docx`, `png`, `pdf`
- Maximum file size: `10 MB`
- OSS objects are publicly readable
- Dual-channel vectorization for `png`
- Milvus storage with HNSW index

## Goals

- Add a usable upload flow from the current frontend shell
- Store file binaries in Alibaba Cloud OSS
- Persist lightweight file metadata in MySQL
- Return success immediately after OSS + MySQL succeed
- Vectorize `docx`, `pdf`, and `png` asynchronously
- Split `png` vectorization into text and image channels
- Clean extracted content before chunking, including page breaks, HTML structure, page headers, and page footers
- Store retrieval vectors and chunk metadata in Milvus

## Non-Goals

- Batch uploads
- Folder uploads
- Delete, rename, or replace flows
- Dedicated queue or worker infrastructure
- Query-side RAG orchestration
- File-to-business-object binding

## Architecture

### Frontend

The frontend keeps the current upload modal flow. Upload success means the file binary and original metadata are persisted successfully. The frontend does not block on vectorization.

### Backend

The backend handles:

1. file extension and size validation
2. OSS object key generation
3. upload to Alibaba Cloud OSS
4. MySQL metadata insert
5. immediate response mapping for the frontend
6. in-process background vectorization
7. text-channel and image-channel orchestration
8. Milvus insert and HNSW index bootstrap
9. vectorization status updates back into MySQL

### Storage

- Binary file data: Alibaba Cloud OSS
- File metadata and vectorization state: MySQL
- Text vectors and retrieval metadata: Milvus text collection
- Image vectors and retrieval metadata: Milvus image collection

## Data Model

### Table: `uploaded_file`

Required columns:

- `id` bigint primary key auto increment
- `file_name` varchar(255) not null
- `file_ext` varchar(32) not null
- `mime_type` varchar(128) not null
- `file_size` bigint not null
- `oss_bucket` varchar(128) not null
- `oss_key` varchar(512) not null
- `public_url` varchar(1024) not null
- `status` varchar(32) not null default `UPLOADED`
- `vector_status` varchar(32) not null default `PENDING`
- `vector_error` varchar(1024) null
- `chunk_count` int not null default `0`
- `text_vector_status` varchar(32) not null default `PENDING`
- `text_vector_error` varchar(1024) null
- `text_chunk_count` int not null default `0`
- `image_vector_status` varchar(32) null
- `image_vector_error` varchar(1024) null
- `image_chunk_count` int not null default `0`
- `created_at` datetime not null default current timestamp
- `updated_at` datetime not null default current timestamp on update current timestamp
- `vectorized_at` datetime null

Indexes:

- unique index on `oss_key`
- index on `created_at`
- index on `vector_status`
- index on `text_vector_status`
- index on `image_vector_status`

`status` and `vector_status` are separate because upload success must not depend on vectorization success. `vector_status` is the aggregate state exposed to the current frontend. `text_vector_status` and `image_vector_status` record per-channel detail.

## Async Upload Flow

`POST /api/uploads` follows this order:

1. validate extension and size
2. upload file bytes to OSS
3. insert `uploaded_file` row with `status=UPLOADED` and channel statuses
4. return the upload response
5. trigger a FastAPI background task for vectorization

If vectorization later fails, upload success remains valid and MySQL stores the failure state.

Aggregate status rule:

- `docx` / `pdf`: aggregate follows the text channel
- `png`: aggregate is `VECTORIZED` only when both text and image channels succeed
- `png`: aggregate is `FAILED` if either channel fails
- `png`: aggregate may be `PARTIAL_SUCCESS` in storage, but the current frontend can still render it as a non-success diagnostic state

## Parsing Strategy

### `docx`

- Extract paragraph text from the document body
- Ignore empty paragraphs after normalization
- Preserve logical paragraph boundaries for downstream chunking

### `pdf`

- Extract text page by page
- Preserve page numbers in intermediate segments
- Remove repeated headers and footers across pages before chunking
- Remove page break markers

### `png`

- Run OCR first
- Treat OCR output as plain text content
- Mark source metadata as OCR-derived
- Run a second image-channel embedding directly on the original image bytes

## Cleaning Strategy

All extracted text passes through the same cleaning stage before chunking:

1. remove page-break characters such as `\f`
2. strip HTML tags and flatten HTML structure into plain text
3. normalize line endings and repeated whitespace
4. trim repeated page headers and footers when the source is page-based
5. drop empty or near-empty text segments

This keeps markup, duplicated chrome, and layout noise out of the embedding pipeline.

## Chunking Strategy

The system uses dual-size chunking.

### Small Chunks

- Purpose: retrieval recall
- Vectorized and stored in Milvus
- Built with fixed-size windows and overlap

### Large Chunks

- Purpose: downstream LLM context
- Built by grouping adjacent small chunks
- Not vectorized separately in this iteration

Each small chunk stores:

- `small_chunk_text`
- `small_chunk_index`
- `large_chunk_id`
- `large_chunk_text`
- `page_start`
- `page_end`

Retrieval later can search small chunks and then expand to large-chunk context.

## Embedding Strategy

The system uses two embedding channels.

### Text Channel

- Used by `docx`, `pdf`, and `png`
- Input: cleaned small chunks only
- API: ARK text embedding endpoint
- Embedding calls are batched
- Embedding dimension is configuration-driven

### Image Channel

- Used by `png` only
- Input: original image bytes or OSS URL
- API: ARK `multimodal_embeddings.create(...)`
- Stores one or a few image vectors per source image in this iteration

Text and image channels must not be mixed in one Milvus collection because the model space, metadata, and future query semantics differ.

The implementation must not hardcode model dimension into application logic beyond Milvus schema creation.

## Milvus Strategy

Two Milvus collections are used.

### Text Collection

Stores text-channel vectors from `docx`, `pdf`, and `png OCR`.

Required metadata fields:

- `id`
- `file_id`
- `file_name`
- `file_ext`
- `mime_type`
- `page_start`
- `page_end`
- `small_chunk_index`
- `large_chunk_id`
- `small_chunk_text`
- `large_chunk_text`
- `source_type`
- `created_at`

The vector field uses an HNSW index with:

```text
index_type = HNSW
metric_type = COSINE
M = 16
efConstruction = 200
```

### Image Collection

Stores image-channel vectors from `png`.

Required metadata fields:

- `id`
- `file_id`
- `file_name`
- `file_ext`
- `mime_type`
- `image_index`
- `source_type`
- `created_at`

The image collection also uses HNSW, but its vector dimension is independently configurable because it may differ from the text model.

If a collection already exists, the backend reuses it. If vectors for the same file already exist, the backend deletes them before inserting the new rows.

## API Design

### `POST /api/uploads`

Request:

- `multipart/form-data`
- field name: `file`

Success response:

```json
{
  "id": 1,
  "fileName": "system-overview.pdf",
  "fileExt": "pdf",
  "mimeType": "application/pdf",
  "fileSize": 452188,
  "url": "https://<public-domain>/uploads/2026/03/24/file.pdf",
  "vectorStatus": "PENDING",
  "createdAt": "2026-03-24T12:00:00"
}
```

Failure responses:

- `400`: invalid file type or size
- `500`: configuration missing or database write failed
- `502`: OSS upload failed

The upload endpoint does not wait for vectorization completion.

### `GET /api/uploads`

Returns recent uploaded files ordered by newest first, including `vectorStatus`.

This iteration does not expose `textVectorStatus` and `imageVectorStatus` to the frontend yet, but the backend should persist them for diagnostics and future UI.

## Error Handling

### Upload Path

- Validation failures return `400`
- OSS failures return `502`
- Database failures return `500`

### Vectorization Path

- Vectorization failures update `vector_status=FAILED`
- A bounded `vector_error` is stored for diagnostics
- Channel-specific failures also update `text_vector_error` or `image_vector_error`
- Upload success is not rolled back

## Configuration

Required settings include:

- MySQL connection settings
- OSS bucket settings
- ARK text embedding endpoint, API key, and model
- ARK multimodal embedding endpoint for image vectors
- Milvus URI, token, text collection name, image collection name, vector dimensions, and HNSW parameters
- Chunk size and overlap settings

## Testing Strategy

- Unit test text cleaning for page breaks, HTML cleanup, and repeated headers/footers
- Unit test chunking for small and large chunk linkage
- Unit test upload orchestration to ensure background vectorization is scheduled after DB success
- Unit test vectorization orchestration with fake parser, text embedding, image embedding, and Milvus services
- Unit test aggregate status calculation for `png` dual-channel completion and partial failure
- Keep API tests focused on upload success and response shape
