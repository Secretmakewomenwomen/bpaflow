from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.services.chapter_flow_service import ChapterFlowService
from app.services.upload_service import UploadService

_FLOW_STOP_TERMS = {
    "根据",
    "文件",
    "文档",
    "生成",
    "流程图",
    "请",
    "帮我",
    "从",
    "用",
}
_FLOW_CANDIDATE_LOOKUP_LIMIT = 200


class FlowChartInterruptService:
    def __init__(
        self,
        *,
        upload_service: UploadService | None,
        chapter_flow_service: ChapterFlowService | None,
    ) -> None:
        self.upload_service = upload_service
        self.chapter_flow_service = chapter_flow_service

    def find_candidate_files(self, *, query: str, user_id: str) -> list[dict[str, Any]]:
        if self.upload_service is None:
            return []

        uploads = self.upload_service.list_uploads(
            user_id=user_id,
            limit=_FLOW_CANDIDATE_LOOKUP_LIMIT,
            file_type="document",
        )
        docx_uploads = [upload for upload in uploads if self._is_docx_upload(upload)]
        if not docx_uploads:
            return []

        terms = self._extract_match_terms(query)
        if not terms:
            return []
        scored: list[tuple[int, datetime | None, dict[str, Any]]] = []
        for upload in docx_uploads:
            file_name = str(getattr(upload, "fileName", "") or "").strip()
            if not file_name:
                continue
            searchable_texts = self._collect_searchable_texts(upload)
            score = 0
            for term in terms:
                lowered_term = term.lower()
                for text in searchable_texts:
                    if lowered_term in text:
                        score += len(term)
            payload = {
                "upload_id": int(getattr(upload, "id")),
                "file_name": file_name,
            }
            created_at = getattr(upload, "createdAt", None)
            if score > 0:
                scored.append((score, created_at, payload))

        if not scored:
            fallback_candidates: list[tuple[datetime | None, dict[str, Any]]] = []
            for upload in docx_uploads:
                file_name = str(getattr(upload, "fileName", "") or "").strip()
                if not file_name:
                    continue
                fallback_candidates.append(
                    (
                        getattr(upload, "createdAt", None),
                        {
                            "upload_id": int(getattr(upload, "id")),
                            "file_name": file_name,
                        },
                    )
                )
            fallback_candidates.sort(key=lambda item: item[0] or datetime.min, reverse=True)
            return [item[1] for item in fallback_candidates[:5]]

        scored.sort(key=lambda item: (item[0], item[1] or datetime.min), reverse=True)
        return [item[2] for item in scored[:5]]

    def build_artifact(self, *, upload_id: int, user_id: str) -> dict[str, Any]:
        if self.chapter_flow_service is None:
            raise RuntimeError("ChapterFlowService is not configured.")
        parsed = self.chapter_flow_service.parse_upload(upload_id=upload_id, user_id=user_id)
        parsed_payload = parsed.model_dump(mode="json")
        return {
            "artifact_type": "chapter_flow_json",
            "graph_payload": parsed_payload.get("graphPayload", {}),
            "payload": parsed_payload,
        }

    def _extract_match_terms(self, query: str) -> list[str]:
        terms: list[str] = []
        normalized = query.strip().lower()
        focus = query
        for stop_term in sorted(_FLOW_STOP_TERMS, key=len, reverse=True):
            focus = focus.replace(stop_term, "")
        focus = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", focus).strip().lower()
        if len(focus) >= 2:
            terms.append(focus)
        focus_match = re.search(r"根据(.+?)(文件|文档)", query)
        if focus_match:
            focus = focus_match.group(1).strip()
            if focus and focus not in _FLOW_STOP_TERMS:
                terms.append(focus)
        for token in re.findall(r"[0-9a-zA-Z\u4e00-\u9fff]+", normalized):
            cleaned = token.strip()
            if len(cleaned) < 2 or cleaned in _FLOW_STOP_TERMS:
                continue
            terms.append(cleaned)
        deduped: list[str] = []
        seen: set[str] = set()
        for term in terms:
            if term in seen:
                continue
            seen.add(term)
            deduped.append(term)
        return deduped

    def _collect_searchable_texts(self, upload: Any) -> list[str]:
        values: list[str] = []
        for attr in ("fileName", "title", "documentTitle", "name"):
            raw_value = getattr(upload, attr, None)
            if not raw_value:
                continue
            text = str(raw_value).strip().lower()
            if not text:
                continue
            values.append(text)
            if text.endswith(".docx"):
                values.append(text[:-5])
        deduped: list[str] = []
        seen: set[str] = set()
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            deduped.append(value)
        return deduped

    def _is_docx_upload(self, upload: Any) -> bool:
        file_ext = str(getattr(upload, "fileExt", "") or "").lower()
        if file_ext == "docx":
            return True
        file_name = str(getattr(upload, "fileName", "") or "").lower()
        return file_name.endswith(".docx")
