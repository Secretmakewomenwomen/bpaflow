from __future__ import annotations

import re
from datetime import UTC, datetime
import math

from sqlalchemy import text

from app.core.config import Settings
from app.core.database import ensure_vector_store_schema, get_engine


class PgVectorService:
    _MAX_TOP_K = 1000

    def __init__(self, settings: Settings, engine=None) -> None:
        self.settings = settings
        self.engine = engine or get_engine()

    def _validate_top_k(self, top_k: int) -> None:
        if top_k <= 0 or top_k > self._MAX_TOP_K:
            raise ValueError(f"top_k must be between 1 and {self._MAX_TOP_K}")

    def ensure_text_collection(self) -> None:
        ensure_vector_store_schema(self.engine)

    def ensure_image_collection(self) -> None:
        ensure_vector_store_schema(self.engine)

    def replace_text_chunks(self, file_id: int, rows: list[dict]) -> None:
        self._replace_rows(
            table_name=self._validated_identifier(self.settings.pgvector_text_table),
            file_id=file_id,
            rows=rows,
            created_at_key="created_at",
            expected_embedding_dimension=self.settings.pgvector_text_vector_dimension,
        )

    def replace_image_vectors(self, file_id: int, rows: list[dict]) -> None:
        self._replace_rows(
            table_name=self._validated_identifier(self.settings.pgvector_image_table),
            file_id=file_id,
            rows=rows,
            created_at_key="created_at",
            expected_embedding_dimension=self.settings.pgvector_image_vector_dimension,
        )

    def delete_file_vectors(self, file_id: int) -> None:
        for table_name in (
            self._validated_identifier(self.settings.pgvector_text_table),
            self._validated_identifier(self.settings.pgvector_image_table),
        ):
            with self.engine.begin() as connection:
                connection.execute(
                    text(f"DELETE FROM {table_name} WHERE file_id = :file_id"),
                    {"file_id": file_id},
                )

    def search_text_similar_chunks(
        self,
        *,
        user_id: str,
        query_embedding: list[float],
        top_k: int,
    ) -> list[dict]:
        self._validate_top_k(top_k)
        table_name = self._validated_identifier(self.settings.pgvector_text_table)
        self._validate_vector_dimension(
            query_embedding,
            expected_dimension=self.settings.pgvector_text_vector_dimension,
            context="Query embedding",
        )
        # 中文说明：三路召回最终都要回到统一候选结构，所以这里主动把 BM25 / rule score
        # 也补成空列，后续 AIRagService 可以按同一套 row schema 做映射和融合。
        sql = text(
            f"""
            SELECT
              vectors.file_id AS file_id,
              uf.id AS upload_id,
              vectors.file_name AS file_name,
              vectors.mime_type AS mime_type,
              uf.created_at AS created_at,
              uf.public_url AS download_url,
              vectors.small_chunk_text AS small_chunk_text,
              vectors.large_chunk_text AS large_chunk_text,
              vectors.page_start AS page_start,
              vectors.page_end AS page_end,
              vectors.small_chunk_index AS small_chunk_index,
              (vectors.embedding <=> CAST(:query_embedding AS vector)) AS distance,
              NULL::double precision AS bm25_score,
              NULL::double precision AS rule_score
            FROM {table_name} AS vectors
            JOIN uploaded_file AS uf ON uf.id = vectors.file_id
            WHERE uf.user_id = :user_id
              AND uf.text_vector_status = 'VECTORIZED'
            ORDER BY vectors.embedding <=> CAST(:query_embedding AS vector) ASC
            LIMIT :top_k
            """
        )
        params = {
            "user_id": user_id,
            "query_embedding": self._encode_vector(query_embedding),
            "top_k": top_k,
        }

        with self.engine.begin() as connection:
            result = connection.execute(sql, params)
            return [dict(item) for item in result.mappings().all()]

    def search_text_bm25_chunks(
        self,
        *,
        user_id: str,
        query_text: str,
        top_k: int,
    ) -> list[dict]:
        self._validate_top_k(top_k)
        table_name = self._validated_identifier(self.settings.pgvector_text_table)

        # 中文说明：BM25 仍然复用现有 chunk 表，不单独维护搜索副本。
        # 好处是避免双写和一致性问题，同时让向量召回、BM25、规则召回共享同一份数据域。
        sql = text(
            f"""
            SELECT
              vectors.file_id AS file_id,
              uf.id AS upload_id,
              vectors.file_name AS file_name,
              vectors.mime_type AS mime_type,
              uf.created_at AS created_at,
              uf.public_url AS download_url,
              vectors.small_chunk_text AS small_chunk_text,
              vectors.large_chunk_text AS large_chunk_text,
              vectors.page_start AS page_start,
              vectors.page_end AS page_end,
              vectors.small_chunk_index AS small_chunk_index,
              NULL::double precision AS distance,
              pdb.score(vectors.id) AS bm25_score,
              NULL::double precision AS rule_score
            FROM {table_name} AS vectors
            JOIN uploaded_file AS uf ON uf.id = vectors.file_id
            WHERE uf.user_id = :user_id
              AND uf.text_vector_status = 'VECTORIZED'
              AND (
                -- 中文说明：chunk 文本是主召回字段，文件名额外 boost 2 倍，
                -- 这样术语、缩写、接口名、文件标题类查询会更稳。
                vectors.small_chunk_text ||| :query
                OR vectors.file_name ||| :query::pdb.boost(2)
              )
            ORDER BY pdb.score(vectors.id) DESC, uf.id DESC, vectors.small_chunk_index ASC
            LIMIT :top_k
            """
        )
        params = {
            "user_id": user_id,
            "query": query_text,
            "top_k": top_k,
        }

        with self.engine.begin() as connection:
            result = connection.execute(sql, params)
            return [dict(item) for item in result.mappings().all()]

    def search_rule_candidate_chunks(
        self,
        *,
        user_id: str,
        file_name_tokens: list[str],
        per_file_limit: int,
        top_k: int,
    ) -> list[dict]:
        self._validate_top_k(top_k)
        if per_file_limit <= 0:
            raise ValueError("per_file_limit must be positive")

        tokens = [token.strip().lower() for token in file_name_tokens if token and token.strip()]
        if not tokens:
            return []

        table_name = self._validated_identifier(self.settings.pgvector_text_table)

        token_clauses: list[str] = []
        token_params: dict[str, str] = {}
        for index, token in enumerate(tokens):
            key = f"token_{index}"
            token_clauses.append(f"LOWER(vectors.file_name) LIKE :{key}")
            token_params[key] = f"%{token}%"

        # 中文说明：规则召回只做“确定性补召回”，重点补文件名/编号/术语类请求。
        # 每个文件只取前几个 chunk，避免规则路因为整文件命中而把结果列表刷满。
        sql = text(
            f"""
            WITH ranked AS (
              SELECT
                vectors.file_id AS file_id,
                uf.id AS upload_id,
                vectors.file_name AS file_name,
                vectors.mime_type AS mime_type,
                uf.created_at AS created_at,
                uf.public_url AS download_url,
                vectors.small_chunk_text AS small_chunk_text,
                vectors.large_chunk_text AS large_chunk_text,
                vectors.page_start AS page_start,
                vectors.page_end AS page_end,
                vectors.small_chunk_index AS small_chunk_index,
                ROW_NUMBER() OVER (PARTITION BY vectors.file_id ORDER BY vectors.small_chunk_index ASC) AS rn
              FROM {table_name} AS vectors
              JOIN uploaded_file AS uf ON uf.id = vectors.file_id
              WHERE uf.user_id = :user_id
                AND uf.text_vector_status = 'VECTORIZED'
                AND ({' OR '.join(token_clauses)})
            )
            SELECT
              ranked.file_id AS file_id,
              ranked.upload_id AS upload_id,
              ranked.file_name AS file_name,
              ranked.mime_type AS mime_type,
              ranked.created_at AS created_at,
              ranked.download_url AS download_url,
              ranked.small_chunk_text AS small_chunk_text,
              ranked.large_chunk_text AS large_chunk_text,
              ranked.page_start AS page_start,
              ranked.page_end AS page_end,
              ranked.small_chunk_index AS small_chunk_index,
              NULL::double precision AS distance,
              NULL::double precision AS bm25_score,
              1.0::double precision AS rule_score
            FROM ranked
            WHERE ranked.rn <= :per_file_limit
            ORDER BY ranked.created_at DESC, ranked.file_id DESC, ranked.small_chunk_index ASC
            LIMIT :top_k
            """
        )
        params = {
            "user_id": user_id,
            "per_file_limit": per_file_limit,
            "top_k": top_k,
            **token_params,
        }

        with self.engine.begin() as connection:
            result = connection.execute(sql, params)
            return [dict(item) for item in result.mappings().all()]

    def _replace_rows(
        self,
        *,
        table_name: str,
        file_id: int,
        rows: list[dict],
        created_at_key: str,
        expected_embedding_dimension: int,
    ) -> None:
        table_name = self._validated_identifier(table_name)
        with self.engine.begin() as connection:
            connection.execute(
                text(f"DELETE FROM {table_name} WHERE file_id = :file_id"),
                {"file_id": file_id},
            )

            for row in rows:
                payload = dict(row)
                created_at = payload.get(created_at_key) or datetime.now(UTC).isoformat()
                payload[created_at_key] = created_at
                for key in payload:
                    self._validated_identifier(key)
                if "embedding" in payload:
                    self._validate_vector_dimension(
                        payload["embedding"],
                        expected_dimension=expected_embedding_dimension,
                        context="Embedding",
                    )
                columns = ", ".join(payload.keys())
                bindings = ", ".join(
                    f"CAST(:{key}_vector AS vector)"
                    if key == "embedding"
                    else f":{key}"
                    for key in payload
                )
                params = {
                    f"{key}_vector" if key == "embedding" else key: self._encode_vector(value)
                    if key == "embedding"
                    else value
                    for key, value in payload.items()
                }
                connection.execute(
                    text(
                        f"INSERT INTO {table_name} ({columns}) "
                        f"VALUES ({bindings})"
                    ),
                    params,
                )

    def _encode_vector(self, value: list[float]) -> str:
        encoded_items: list[str] = []
        for index, item in enumerate(value):
            if not isinstance(item, int | float):
                raise ValueError(f"Vector element at index {index} must be numeric")
            numeric = float(item)
            if not math.isfinite(numeric):
                raise ValueError(f"Vector element at index {index} must be finite")
            encoded_items.append(str(numeric))
        return "[" + ",".join(encoded_items) + "]"

    def _validated_identifier(self, identifier: str) -> str:
        # 中文说明：表名/列名不能参数化绑定，只能拼接 SQL。
        # 因此这里必须把标识符限制成简单形式，避免 SQL 注入和错误表名。
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", identifier):
            raise ValueError(f"Unsafe SQL identifier: {identifier}")
        return identifier

    def _validate_vector_dimension(
        self,
        value: list[float],
        *,
        expected_dimension: int,
        context: str,
    ) -> None:
        actual_dimension = len(value)
        if actual_dimension != expected_dimension:
            raise ValueError(
                f"{context} dimension mismatch: expected {expected_dimension}, got {actual_dimension}"
            )
