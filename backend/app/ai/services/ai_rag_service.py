from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from openai import OpenAI

from app.core.config import Settings
from app.schemas.ai import AssistantResponse, AssistantSnippet, Intent, RelatedFile
from app.services.embedding_service import EmbeddingService
from app.services.pgvector_service import PgVectorService

_TOKEN_PATTERN = re.compile(r"[a-z0-9_\-]+|[\u4e00-\u9fff]+", re.IGNORECASE)
_IDENTIFIER_PATTERN = re.compile(r"[a-z0-9_\-]+", re.IGNORECASE)
_PURE_CJK_PATTERN = re.compile(r"^[\u4e00-\u9fff]+$")
_CJK_EDGE_NOISE = "的了呢吗吧啊呀嘛哈哦哇喔"
_CJK_SPLIT_MARKERS = (
    "怎么办",
    "怎么样",
    "怎么",
    "如何",
    "怎样",
    "咋办",
    "请问",
    "帮我",
    "我该",
    "我想",
    "我要",
    "我的",
    "一下子",
    "一下",
)
_CJK_STOPWORDS = {
    "请问",
    "帮我",
    "我的",
    "我该",
    "我想",
    "我要",
    "怎么",
    "如何",
    "怎样",
    "咋办",
    "怎么办",
    "怎么样",
    "一下",
    "一下子",
}
_RECENT_INDICATORS = {
    "最近",
    "最新",
    "近期",
    "新近",
    "新上传",
    "刚上传",
    "最近上传",
    "刚刚",
    "近日",
    "recent",
    "latest",
    "new",
    "just",
}
_FILE_TYPE_KEYWORDS = {
    "pdf": "pdf",
    "document": "document",
    "doc": "document",
    "docx": "document",
    "ppt": "document",
    "pptx": "document",
    "excel": "document",
    "xlsx": "document",
    "附件": "document",
    "文档": "document",
    "资料": "document",
    "image": "image",
    "images": "image",
    "picture": "image",
    "pictures": "image",
    "图": "image",
    "图片": "image",
    "架构图": "image",
    "png": "image",
    "jpg": "image",
    "jpeg": "image",
    "photo": "image",
    "photos": "image",
}
logger = logging.getLogger(__name__)

@dataclass(slots=True)
class QueryFeatures:
    normalized_query: str
    keywords: list[str]
    identifier_tokens: list[str]
    wants_recent: bool
    requested_file_types: set[str]
    wants_image: bool
    wants_pdf: bool
    wants_document: bool


@dataclass(slots=True)
class RetrievedCandidate:
    file_id: int
    file_name: str
    mime_type: str
    created_at: datetime | None
    small_chunk_index: int
    text: str
    page_start: int | None
    page_end: int | None
    vector_score: float = 0.0
    bm25_score: float = 0.0
    rule_score: float = 0.0
    final_score: float = 0.0


def _normalize_text(text: str) -> str:
    return text.strip().lower()


def _tokenize_query(text: str) -> list[str]:
    return [token for token in _TOKEN_PATTERN.findall(text) if token]


def _extract_keywords(tokens: list[str]) -> list[str]:
    keywords: list[str] = []
    seen: set[str] = set()

    def add_keyword(keyword: str) -> None:
        normalized = keyword.strip().lower()
        if len(normalized) < 2:
            return
        if normalized in _CJK_STOPWORDS:
            return
        if normalized in seen:
            return
        seen.add(normalized)
        keywords.append(normalized)

    for token in tokens:
        add_keyword(token)
        for expanded in _expand_cjk_keywords(token):
            add_keyword(expanded)

    return keywords


def _trim_cjk_segment(segment: str) -> str:
    trimmed = segment.strip()
    while trimmed and trimmed[0] in _CJK_EDGE_NOISE:
        trimmed = trimmed[1:]
    while trimmed and trimmed[-1] in _CJK_EDGE_NOISE:
        trimmed = trimmed[:-1]
    return trimmed


def _expand_cjk_keywords(token: str) -> list[str]:
    normalized = token.strip()
    if len(normalized) < 4:
        return []
    if not _PURE_CJK_PATTERN.fullmatch(normalized):
        return []

    expanded: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        normalized_term = _trim_cjk_segment(term)
        if len(normalized_term) < 2:
            return
        if normalized_term in _CJK_STOPWORDS:
            return
        if normalized_term in seen:
            return
        seen.add(normalized_term)
        expanded.append(normalized_term)

    split_text = normalized
    for marker in _CJK_SPLIT_MARKERS:
        split_text = split_text.replace(marker, " ")
    for part in split_text.split():
        cleaned = _trim_cjk_segment(part)
        if len(cleaned) < 2:
            continue
        add(cleaned)
        if len(cleaned) >= 4:
            add(cleaned[:2])
            add(cleaned[-2:])

    add(normalized[:2])
    add(normalized[-2:])
    return expanded


def _extract_identifier_tokens(tokens: list[str]) -> list[str]:
    return [token for token in tokens if _IDENTIFIER_PATTERN.fullmatch(token)]


def _is_valid_rule_token(token: str) -> bool:
    normalized = token.strip()
    return len(normalized) >= 2


def _detect_requested_file_types(*, normalized_text: str, tokens: list[str]) -> set[str]:
    token_set = set(tokens)
    requested_types: set[str] = set()
    for keyword, file_type in _FILE_TYPE_KEYWORDS.items():
        if keyword.isascii():
            if keyword in token_set:
                requested_types.add(file_type)
        elif keyword in normalized_text:
            requested_types.add(file_type)
    return requested_types


def _contains_recent_hint(text: str) -> bool:
    return any(keyword in text for keyword in _RECENT_INDICATORS)


def build_similarity_score(distance: float) -> float:
    score = 1 - distance
    return max(0.0, min(1.0, score))


class AIRagService:
    def __init__(
        self,
        settings: Settings,
        embedding_service: EmbeddingService | None = None,
        pgvector_service: PgVectorService | None = None,
        openai_client: OpenAI | None = None,
    ) -> None:
        self.settings = settings
        self.embedding_service = embedding_service or EmbeddingService(settings)
        self.pgvector_service = pgvector_service or PgVectorService(settings)
        self._openai_client = openai_client

    def retrieve(self, *, query: str, user_id: str, top_k: int | None = None) -> AssistantResponse:
        features = self._analyze_query(query)
        rewritten_queries = self._rewrite_queries(query)
        final_top_k = top_k if top_k is not None else int(self.settings.assistant_retrieval_top_k)
        query_embedding_list = self.embedding_service.embed_texts(rewritten_queries)
        if not query_embedding_list:
            raise RuntimeError("Embedding service returned no query embeddings")

        # 中文说明：每一路先放大召回，再在融合后截断 final_top_k。
        # 这样可以避免某一路刚好压线被裁掉，给 rerank 留出足够候选空间。
        vector_top_k = self._get_route_top_k("assistant_vector_retrieval_top_k")
        bm25_top_k = self._get_route_top_k("assistant_bm25_retrieval_top_k")
        rule_top_k = self._get_route_top_k("assistant_rule_retrieval_top_k")
        rule_chunks_per_file = int(getattr(self.settings, "assistant_rule_chunks_per_file", 2))

        vector_candidates: list[RetrievedCandidate] = []
        bm25_candidates: list[RetrievedCandidate] = []
        rule_candidates: list[RetrievedCandidate] = []

        for rewritten_query, query_embedding in zip(rewritten_queries, query_embedding_list, strict=False):
            rewritten_features = self._analyze_query(rewritten_query)
            vector_candidates.extend(
                self._retrieve_vector_candidates(
                    user_id=user_id,
                    query_embedding=query_embedding,
                    top_k=vector_top_k,
                )
            )
            bm25_candidates.extend(
                self._retrieve_bm25_candidates(
                    user_id=user_id,
                    query_text=rewritten_features.normalized_query,
                    top_k=bm25_top_k,
                )
            )
            rule_candidates.extend(
                self._retrieve_rule_candidates(
                    user_id=user_id,
                    features=rewritten_features,
                    per_file_limit=rule_chunks_per_file,
                    top_k=rule_top_k,
                )
            )

        merged = self._merge_candidates(vector_candidates, bm25_candidates, rule_candidates)
        ranked = self._rerank_candidates(merged, features)
        return self._build_response_from_candidates(ranked, final_top_k=final_top_k)

    def _empty_response(self) -> AssistantResponse:
        return AssistantResponse(
            intent=Intent.rag_retrieval,
            message="未检索到相关资料。",
            answer="",
            snippets=[],
            related_files=[],
        )

    def _normalize_page(self, page: int | None) -> int | None:
        if page == 0:
            return None
        return page

    def _min_similarity_score(self) -> float:
        value = getattr(self.settings, "assistant_min_similarity_score", 0.45)
        return max(0.0, min(1.0, float(value)))

    def _get_route_top_k(self, setting_name: str) -> int:
        base = int(getattr(self.settings, "assistant_retrieval_top_k", 6))
        value = getattr(self.settings, setting_name, base)
        try:
            value_int = int(value)
        except (TypeError, ValueError):
            return base
        return value_int if value_int > 0 else base

    def _min_final_score(self) -> float:
        value = getattr(self.settings, "assistant_min_final_score", 0.25)
        return max(0.0, min(1.0, float(value)))

    @staticmethod
    def _analyze_query(query: str) -> QueryFeatures:
        # 中文说明：这里故意只做轻量 query analysis，不引入 LLM 改写。
        # 目标是给三路召回和 bonus 打稳定特征，避免把检索前置逻辑做得过重。
        normalized = _normalize_text(query)
        tokens = _tokenize_query(normalized)
        keywords = _extract_keywords(tokens)
        identifier_tokens = _extract_identifier_tokens(tokens)
        requested_file_types = _detect_requested_file_types(
            normalized_text=normalized,
            tokens=tokens,
        )
        wants_pdf = "pdf" in requested_file_types
        wants_image = "image" in requested_file_types
        wants_document = "document" in requested_file_types
        wants_recent = _contains_recent_hint(normalized)
        return QueryFeatures(
            normalized_query=normalized,
            keywords=keywords,
            identifier_tokens=identifier_tokens,
            wants_recent=wants_recent,
            requested_file_types=requested_file_types,
            wants_image=wants_image,
            wants_pdf=wants_pdf,
            wants_document=wants_document,
        )

    def _rewrite_queries(self, query: str) -> list[str]:
        normalized = query.strip()
        if not normalized:
            return [query]
        if not self._is_query_rewrite_model_configured():
            return [normalized]
        try:
            completion = self._get_openai_client().chat.completions.create(
                model=self.settings.assistant_llm_model,
                temperature=0,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是企业知识库检索 query rewrite 助手。"
                            "请把用户输入改写成 1 到 4 个可直接用于文件检索的查询短语。"
                            "只有在用户明确包含多个并列主题时才拆成多个查询。"
                            "不要解释，不要补充新信息，只输出严格 JSON，格式为 "
                            '{"queries":["query1","query2"]}。'
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"用户原始检索请求：{normalized}",
                    },
                ],
            )
        except Exception:
            logger.warning("Query rewrite failed, fallback to original query.", exc_info=True)
            return [normalized]
        content = self._extract_completion_text(completion)
        return self._parse_rewritten_queries(content, fallback=normalized)

    def _get_openai_client(self) -> OpenAI:
        if self._openai_client is None:
            self._openai_client = OpenAI(
                base_url=self._normalize_assistant_base_url(self.settings.assistant_llm_base_url),
                api_key=self.settings.assistant_llm_api_key,
            )
        return self._openai_client

    def _is_query_rewrite_model_configured(self) -> bool:
        return bool(
            getattr(self.settings, "assistant_llm_base_url", None)
            and getattr(self.settings, "assistant_llm_api_key", None)
            and getattr(self.settings, "assistant_llm_model", None)
        )

    @staticmethod
    def _normalize_assistant_base_url(base_url: str | None) -> str | None:
        if base_url is None:
            return None
        normalized = base_url.rstrip("/")
        if normalized.endswith("/api/coding"):
            return f"{normalized[:-len('/api/coding')]}/api/v3"
        return normalized

    @staticmethod
    def _read_provider_field(obj: object, field_name: str) -> object | None:
        if isinstance(obj, dict):
            return obj.get(field_name)
        return getattr(obj, field_name, None)

    def _extract_completion_text(self, response: object) -> str:
        choices = self._read_provider_field(response, "choices")
        if not isinstance(choices, list) or not choices:
            return ""
        first_choice = choices[0]
        message = self._read_provider_field(first_choice, "message")
        if message is None:
            return ""
        content = self._read_provider_field(message, "content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            chunks: list[str] = []
            for item in content:
                text = self._read_provider_field(item, "text")
                if isinstance(text, str) and text.strip():
                    chunks.append(text.strip())
            return "\n".join(chunks)
        return ""

    def _parse_rewritten_queries(self, content: str, *, fallback: str) -> list[str]:
        if not content:
            return [fallback]
        normalized_content = content.strip()
        if normalized_content.startswith("```"):
            normalized_content = re.sub(r"^```(?:json)?\s*|\s*```$", "", normalized_content).strip()
        try:
            payload = json.loads(normalized_content)
        except json.JSONDecodeError:
            logger.warning("Query rewrite returned invalid JSON payload: %s", content)
            return [fallback]
        queries = payload.get("queries") if isinstance(payload, dict) else None
        if not isinstance(queries, list):
            return [fallback]
        deduped: list[str] = []
        seen: set[str] = set()
        for item in queries:
            if not isinstance(item, str):
                continue
            cleaned = item.strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            deduped.append(cleaned)
            if len(deduped) >= 4:
                break
        return deduped or [fallback]

    @staticmethod
    def _normalize_bm25_scores(scores: list[float]) -> list[float]:
        if not scores:
            return []
        if len(scores) == 1:
            return [1.0]
        min_score = min(scores)
        max_score = max(scores)
        if max_score <= min_score:
            return [0.0 for _ in scores]
        span = max_score - min_score
        return [(score - min_score) / span for score in scores]

    @staticmethod
    def _stable_tie_break_key(
        created_at: datetime | None,
        file_id: int,
        small_chunk_index: int,
    ) -> tuple[float, int, int]:
        if created_at is None:
            timestamp = 0.0
        else:
            normalized_created_at = (
                created_at.replace(tzinfo=UTC)
                if created_at.tzinfo is None
                else created_at.astimezone(UTC)
            )
            timestamp = normalized_created_at.timestamp()
        return -timestamp, -file_id, small_chunk_index

    def _retrieve_vector_candidates(
        self,
        *,
        user_id: str,
        query_embedding: list[float],
        top_k: int,
    ) -> list[RetrievedCandidate]:
        rows = self.pgvector_service.search_text_similar_chunks(
            user_id=user_id,
            query_embedding=query_embedding,
            top_k=top_k,
        )
        if not rows:
            return []

        min_similarity_score = self._min_similarity_score()
        candidates: list[RetrievedCandidate] = []
        for row in rows:
            file_id = self._row_file_id(row)
            vector_score = build_similarity_score(float(row["distance"]))
            if vector_score < min_similarity_score:
                continue
            candidates.append(
                RetrievedCandidate(
                    file_id=file_id,
                    file_name=row["file_name"],
                    mime_type=row["mime_type"],
                    created_at=self._uploaded_file_created_at(row),
                    small_chunk_index=int(row["small_chunk_index"]),
                    text=row["small_chunk_text"],
                    page_start=self._normalize_page(row.get("page_start")),
                    page_end=self._normalize_page(row.get("page_end")),
                    vector_score=vector_score,
                    bm25_score=0.0,
                    rule_score=0.0,
                )
            )
        return candidates

    def _retrieve_bm25_candidates(
        self,
        *,
        user_id: str,
        query_text: str,
        top_k: int,
    ) -> list[RetrievedCandidate]:
        if not bool(getattr(self.settings, "assistant_enable_bm25", False)):
            return []
        if not query_text.strip():
            return []

        rows = self.pgvector_service.search_text_bm25_chunks(
            user_id=user_id,
            query_text=query_text,
            top_k=top_k,
        )

        if not rows:
            return []

        # 中文说明：pg_search 的原始分数是相对值，不适合直接和 0~1 的向量/规则分数混算。
        # 这里先做当前批次的 min-max 归一化，再交给统一融合层计算 final_score。
        raw_scores: list[float] = []
        for row in rows:
            try:
                raw_scores.append(float(row.get("bm25_score") or 0.0))
            except (TypeError, ValueError):
                raw_scores.append(0.0)
        normalized = self._normalize_bm25_scores(raw_scores)

        candidates: list[RetrievedCandidate] = []
        for row, bm25_score in zip(rows, normalized, strict=False):
            file_id = self._row_file_id(row)
            candidates.append(
                RetrievedCandidate(
                    file_id=file_id,
                    file_name=row["file_name"],
                    mime_type=row["mime_type"],
                    created_at=self._uploaded_file_created_at(row),
                    small_chunk_index=int(row["small_chunk_index"]),
                    text=row["small_chunk_text"],
                    page_start=self._normalize_page(row.get("page_start")),
                    page_end=self._normalize_page(row.get("page_end")),
                    vector_score=0.0,
                    bm25_score=float(bm25_score),
                    rule_score=0.0,
                )
            )
        return candidates

    def _retrieve_rule_candidates(
        self,
        *,
        user_id: str,
        features: QueryFeatures,
        per_file_limit: int,
        top_k: int,
    ) -> list[RetrievedCandidate]:
        if not bool(getattr(self.settings, "assistant_enable_rule_retrieval", True)):
            return []

        # 中文说明：规则召回使用 identifier + keyword 的去重并集，重点覆盖文件名、
        # 编号、错误码、接口名这类“语义模型不一定稳，但字面非常关键”的查询。
        tokens: list[str] = []
        seen: set[str] = set()
        for token in [*features.identifier_tokens, *features.keywords]:
            normalized = token.strip().lower()
            if not normalized:
                continue
            if not _is_valid_rule_token(normalized):
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            tokens.append(normalized)

        if not tokens:
            return []

        rows = self.pgvector_service.search_rule_candidate_chunks(
            user_id=user_id,
            file_name_tokens=tokens,
            per_file_limit=per_file_limit,
            top_k=top_k,
        )

        candidates: list[RetrievedCandidate] = []
        for row in rows:
            file_id = self._row_file_id(row)
            try:
                rule_score = float(row.get("rule_score") if row.get("rule_score") is not None else 1.0)
            except (TypeError, ValueError):
                rule_score = 1.0
            rule_score = max(0.0, min(1.0, rule_score))
            candidates.append(
                RetrievedCandidate(
                    file_id=file_id,
                    file_name=row["file_name"],
                    mime_type=row["mime_type"],
                    created_at=self._uploaded_file_created_at(row),
                    small_chunk_index=int(row["small_chunk_index"]),
                    text=row["small_chunk_text"],
                    page_start=self._normalize_page(row.get("page_start")),
                    page_end=self._normalize_page(row.get("page_end")),
                    vector_score=0.0,
                    bm25_score=0.0,
                    rule_score=rule_score,
                )
            )
        return candidates

    @staticmethod
    def _candidate_key(candidate: RetrievedCandidate) -> tuple[int, int]:
        # 中文说明：去重粒度不是 file_id，而是 (file_id, chunk_index)。
        # 因为多路召回可能命中同一文件的不同 chunk，直接按文件去重会丢证据片段。
        return candidate.file_id, candidate.small_chunk_index

    def _merge_candidates(
        self,
        vector_candidates: list[RetrievedCandidate],
        bm25_candidates: list[RetrievedCandidate],
        rule_candidates: list[RetrievedCandidate],
    ) -> list[RetrievedCandidate]:
        merged: dict[tuple[int, int], RetrievedCandidate] = {}

        def merge_into(candidate: RetrievedCandidate) -> None:
            key = self._candidate_key(candidate)
            existing = merged.get(key)
            if existing is None:
                merged[key] = candidate
                return
            # 中文说明：合并阶段只做“分数聚合 + 元数据补全”，不在这里排序，
            # 保证 rerank 可以看到同一个 chunk 在不同召回路上的完整命中信息。
            existing.vector_score = max(existing.vector_score, candidate.vector_score)
            existing.bm25_score = max(existing.bm25_score, candidate.bm25_score)
            existing.rule_score = max(existing.rule_score, candidate.rule_score)
            if not existing.file_name and candidate.file_name:
                existing.file_name = candidate.file_name
            if not existing.mime_type and candidate.mime_type:
                existing.mime_type = candidate.mime_type
            if existing.created_at is None and candidate.created_at is not None:
                existing.created_at = candidate.created_at
            if not existing.text and candidate.text:
                existing.text = candidate.text
            if existing.page_start is None and candidate.page_start is not None:
                existing.page_start = candidate.page_start
            if existing.page_end is None and candidate.page_end is not None:
                existing.page_end = candidate.page_end

        for candidate in vector_candidates:
            merge_into(candidate)
        for candidate in bm25_candidates:
            merge_into(candidate)
        for candidate in rule_candidates:
            merge_into(candidate)

        return list(merged.values())

    def _rerank_candidates(
        self,
        candidates: list[RetrievedCandidate],
        features: QueryFeatures,
    ) -> list[RetrievedCandidate]:
        if not candidates:
            return []

        vector_weight = float(getattr(self.settings, "assistant_vector_weight", 0.45))
        bm25_weight = float(getattr(self.settings, "assistant_bm25_weight", 0.40))
        rule_weight = float(getattr(self.settings, "assistant_rule_weight", 0.15))

        for candidate in candidates:
            # 中文说明：base score 负责融合三路召回主分，bonus 只做小幅业务纠偏，
            # 不让“最新/文件类型/文件名完全一致”这种规则信号完全覆盖主召回结果。
            base = (
                vector_weight * candidate.vector_score
                + bm25_weight * candidate.bm25_score
                + rule_weight * candidate.rule_score
            )
            bonus = self._compute_bonus(candidate, features)
            candidate.final_score = self._clamp_unit_score(base + bonus)

        candidates.sort(
            key=lambda item: (
                -item.final_score,
                *self._stable_tie_break_key(item.created_at, item.file_id, item.small_chunk_index),
            )
        )
        return candidates

    @staticmethod
    def _clamp_unit_score(value: float) -> float:
        if not math.isfinite(value):
            return 0.0
        return max(0.0, min(1.0, float(value)))

    def _compute_bonus(self, candidate: RetrievedCandidate, features: QueryFeatures) -> float:
        total = 0.0
        bonus_file_name_exact = float(getattr(self.settings, "assistant_bonus_file_name_exact", 0.12))
        bonus_term_hit = float(getattr(self.settings, "assistant_bonus_term_hit", 0.08))
        bonus_recent = float(getattr(self.settings, "assistant_bonus_recent", 0.05))
        bonus_type_match = float(getattr(self.settings, "assistant_bonus_type_match", 0.05))

        query_text = features.normalized_query
        file_name = _normalize_text(candidate.file_name or "")
        if query_text and file_name:
            stem = file_name.rsplit(".", 1)[0]
            if query_text == file_name or query_text == stem:
                total += bonus_file_name_exact

        # Term hit: any identifier/keyword appears in the chunk text.
        text = _normalize_text(candidate.text or "")
        if text:
            tokens = []
            seen: set[str] = set()
            for token in [*features.identifier_tokens, *features.keywords]:
                normalized = token.strip().lower()
                if not normalized or len(normalized) < 2:
                    continue
                if normalized in seen:
                    continue
                seen.add(normalized)
                tokens.append(normalized)
            if any(token in text for token in tokens):
                total += bonus_term_hit

        if features.wants_recent and candidate.created_at is not None:
            days = int(getattr(self.settings, "assistant_recent_window_days", 7))
            days = max(0, days)
            created_at = (
                candidate.created_at.replace(tzinfo=UTC)
                if candidate.created_at.tzinfo is None
                else candidate.created_at.astimezone(UTC)
            )
            cutoff = datetime.now(UTC) - timedelta(days=days)
            if created_at >= cutoff:
                total += bonus_recent

        if features.requested_file_types:
            if (features.wants_pdf and self._is_pdf(candidate)) or (
                features.wants_image and self._is_image(candidate)
            ) or (features.wants_document and self._is_document(candidate)):
                total += bonus_type_match

        # 中文说明：bonus 上限固定，避免规则加分把低质量候选硬顶到第一名。
        return min(total, 0.25)

    @staticmethod
    def _row_file_id(row: dict) -> int:
        raw_file_id = row["file_id"] if "file_id" in row and row["file_id"] is not None else row["upload_id"]
        return int(raw_file_id)

    @staticmethod
    def _uploaded_file_created_at(row: dict) -> datetime | None:
        # 中文说明：这里明确要求 retrieval row 一定带 uploaded_file.created_at。
        # recent bonus、文件级排序、related_files tie-break 都依赖这个时间字段。
        if "created_at" not in row:
            raise ValueError("uploaded_file.created_at is required in retrieval rows")
        return row["created_at"]

    @staticmethod
    def _is_pdf(candidate: RetrievedCandidate) -> bool:
        name = _normalize_text(candidate.file_name or "")
        mime = _normalize_text(candidate.mime_type or "")
        return name.endswith(".pdf") or "pdf" in mime

    @staticmethod
    def _is_image(candidate: RetrievedCandidate) -> bool:
        name = _normalize_text(candidate.file_name or "")
        mime = _normalize_text(candidate.mime_type or "")
        return mime.startswith("image/") or name.endswith((".png", ".jpg", ".jpeg"))

    def _is_document(self, candidate: RetrievedCandidate) -> bool:
        if self._is_pdf(candidate):
            return True
        name = _normalize_text(candidate.file_name or "")
        mime = _normalize_text(candidate.mime_type or "")
        return name.endswith((".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx")) or (
            "officedocument" in mime or "msword" in mime or "presentation" in mime or "spreadsheet" in mime
        )

    def _build_response_from_candidates(
        self,
        candidates: list[RetrievedCandidate],
        *,
        final_top_k: int,
    ) -> AssistantResponse:
        min_final_score = self._min_final_score()
        filtered_candidates = [
            candidate for candidate in candidates if candidate.final_score >= min_final_score
        ]
        if not filtered_candidates:
            return self._empty_response()

        snippets: list[AssistantSnippet] = []
        file_scores: dict[int, float] = {}
        file_metadata: dict[int, dict] = {}
        seen_snippet_keys: set[tuple[int, int]] = set()

        # 中文说明：多路融合后再做一次 final_score 阈值裁剪，主要用于清掉尾部低分噪声。
        # 这样像 20% 这类弱相关结果不会继续进入 snippets 和 related_files。
        for candidate in filtered_candidates[: max(0, int(final_top_k))]:
            upload_id = candidate.file_id
            snippet_key = (upload_id, candidate.small_chunk_index)
            if snippet_key in seen_snippet_keys:
                continue
            seen_snippet_keys.add(snippet_key)
            snippets.append(
                AssistantSnippet(
                    upload_id=upload_id,
                    file_name=candidate.file_name,
                    text=candidate.text,
                    page_start=self._normalize_page(candidate.page_start),
                    page_end=self._normalize_page(candidate.page_end),
                    small_chunk_index=candidate.small_chunk_index,
                    score=candidate.final_score,
                )
            )

            current_max = file_scores.get(upload_id)
            if current_max is None or candidate.final_score > current_max:
                file_scores[upload_id] = candidate.final_score

            if upload_id not in file_metadata:
                file_metadata[upload_id] = {
                    "file_name": candidate.file_name,
                    "mime_type": candidate.mime_type,
                    "created_at": candidate.created_at,
                }

        if not snippets:
            return self._empty_response()

        max_related = int(getattr(self.settings, "assistant_max_related_files", 5))
        # 中文说明：snippet 是 chunk 级，related_files 是文件级。
        # 这里取每个文件命中的最高 chunk 分数，既保留证据片段，又能给前端稳定的文件排序。
        ranked_files = sorted(
            file_scores.items(),
            key=lambda item: (
                -item[1],
                *self._stable_tie_break_key(file_metadata[item[0]].get("created_at"), item[0], 0),
            ),
        )[: max(0, max_related)]

        related_files = [
            RelatedFile(
                upload_id=upload_id,
                file_name=file_metadata[upload_id]["file_name"],
                mime_type=file_metadata[upload_id]["mime_type"],
                created_at=file_metadata[upload_id]["created_at"],
                download_url=f"/api/uploads/{upload_id}/download",
            )
            for upload_id, _ in ranked_files
        ]

        return AssistantResponse(
            intent=Intent.rag_retrieval,
            answer="",
            snippets=snippets,
            related_files=related_files,
        )
