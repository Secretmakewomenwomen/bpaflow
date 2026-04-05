from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.upload import UploadedFile
from app.schemas.flow import (
    ChapterPhaseChapterResponse,
    ChapterPhaseParseResponse,
    ChapterPhaseSectionResponse,
)
from app.services.oss_service import OssService
from app.services.parsing_service import ParsingService

_CHAPTER_RE = re.compile(r"^(?:\d+\.\s*)?(第[一二三四五六七八九十百千]+章\s+.+)$")
_SECTION_RE = re.compile(r"^(\d+\.\d+)\s+(.+)$")
_META_PREFIXES = {
    "岗位": "role",
    "部门": "department",
    "责任人": "owner",
    "职责": "responsibilities",
    "内容": "content",
}


class ChapterFlowService:
    def __init__(
        self,
        settings: Settings,
        db: Session | None = None,
        oss_service: OssService | None = None,
        parsing_service: ParsingService | None = None,
    ) -> None:
        self.settings = settings
        self.db = db
        self.oss_service = oss_service or OssService(settings)
        self.parsing_service = parsing_service or ParsingService(settings)

    def parse_upload(self, *, upload_id: int, user_id: str) -> ChapterPhaseParseResponse:
        if self.db is None:
            raise RuntimeError("Database session is required to parse uploaded files.")
        record = self.db.scalar(
            select(UploadedFile).where(
                UploadedFile.id == upload_id,
                UploadedFile.user_id == user_id,
            )
        )
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在。")
        if record.file_ext.lower() != "docx":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前仅支持 DOCX 章节流程解析。")

        content = self.oss_service.get_object_bytes(record.oss_key)
        return self.parse_document(
            filename=record.file_name,
            file_ext=record.file_ext,
            mime_type=record.mime_type,
            content=content,
        )

    def parse_document(
        self,
        *,
        filename: str,
        file_ext: str,
        mime_type: str,
        content: bytes,
    ) -> ChapterPhaseParseResponse:
        parsed_document = self.parsing_service.parse(
            filename=filename,
            file_ext=file_ext,
            mime_type=mime_type,
            content=content,
        )
        document_title, chapters = self._extract_chapters(parsed_document.segments)
        graph_payload = self._build_graph_payload(chapters)
        return ChapterPhaseParseResponse(
            documentTitle=document_title or filename,
            flowType="chapter_phase_flow",
            chapters=chapters,
            graphPayload=graph_payload,
            warnings=[],
        )

    def _extract_chapters(self, segments: list[Any]) -> tuple[str, list[ChapterPhaseChapterResponse]]:
        document_title = ""
        chapter_payloads: list[dict[str, Any]] = []
        current_chapter: dict[str, Any] | None = None
        current_section: dict[str, Any] | None = None

        for segment in segments:
            text = self._normalize_text(getattr(segment, "text", ""))
            if not text:
                continue

            chapter_match = _CHAPTER_RE.match(text)
            if chapter_match:
                current_chapter = {
                    "id": f"chapter-{len(chapter_payloads) + 1}",
                    "title": chapter_match.group(1),
                    "order": len(chapter_payloads) + 1,
                    "sections": [],
                }
                chapter_payloads.append(current_chapter)
                current_section = None
                continue

            section_match = _SECTION_RE.match(text)
            if section_match:
                if current_chapter is None:
                    current_chapter = {
                        "id": "chapter-0",
                        "title": "未分章内容",
                        "order": 0,
                        "sections": [],
                    }
                    chapter_payloads.append(current_chapter)
                current_section = {
                    "id": section_match.group(1),
                    "title": section_match.group(2).strip(),
                    "order": len(current_chapter["sections"]) + 1,
                    "raw_lines": [],
                }
                current_chapter["sections"].append(current_section)
                continue

            if current_section is not None:
                current_section["raw_lines"].append(text)
                continue

            if not document_title:
                document_title = text

        chapters: list[ChapterPhaseChapterResponse] = []
        for chapter_payload in chapter_payloads:
            sections = [
                self._build_section(section_payload, chapter_payload["sections"], index)
                for index, section_payload in enumerate(chapter_payload["sections"])
            ]
            chapters.append(
                ChapterPhaseChapterResponse(
                    id=chapter_payload["id"],
                    title=chapter_payload["title"],
                    order=chapter_payload["order"],
                    sections=sections,
                )
            )
        return document_title, chapters

    def _build_section(
        self,
        section_payload: dict[str, Any],
        sibling_sections: list[dict[str, Any]],
        index: int,
    ) -> ChapterPhaseSectionResponse:
        raw_lines = list(section_payload.get("raw_lines", []))
        metadata = self._extract_metadata(raw_lines)
        content_lines = metadata["content_lines"]
        content = "\n".join(content_lines).strip() or "\n".join(raw_lines).strip()
        next_ids = []
        if index + 1 < len(sibling_sections):
            next_ids.append(sibling_sections[index + 1]["id"])
        return ChapterPhaseSectionResponse(
            id=section_payload["id"],
            title=section_payload["title"],
            order=section_payload["order"],
            summary=self._build_summary(content),
            role=metadata["role"],
            department=metadata["department"],
            owner=metadata["owner"],
            responsibilities=metadata["responsibilities"],
            content=content,
            next=next_ids,
        )

    def _extract_metadata(self, raw_lines: list[str]) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "role": None,
            "department": None,
            "owner": None,
            "responsibilities": [],
            "content_lines": [],
        }
        for line in raw_lines:
            prefix, _, value = line.partition("：")
            if not _:
                metadata["content_lines"].append(line)
                continue
            field_name = _META_PREFIXES.get(prefix.strip())
            cleaned_value = value.strip()
            if field_name == "responsibilities":
                metadata["responsibilities"] = [item.strip() for item in re.split(r"[；;]", cleaned_value) if item.strip()]
            elif field_name == "content":
                if cleaned_value:
                    metadata["content_lines"].append(cleaned_value)
            elif field_name in {"role", "department", "owner"}:
                metadata[field_name] = cleaned_value or None
            else:
                metadata["content_lines"].append(line)
        return metadata

    def _build_graph_payload(self, chapters: list[ChapterPhaseChapterResponse]) -> dict[str, Any]:
        lanes: list[dict[str, Any]] = []
        edges: list[dict[str, str]] = []
        for chapter in chapters:
            children: list[dict[str, Any]] = []
            for section in chapter.sections:
                children.append(
                    {
                        "id": section.id,
                        "name": section.title,
                        "summary": section.summary,
                        "metadata": {
                            "role": section.role,
                            "department": section.department,
                            "owner": section.owner,
                            "responsibilities": section.responsibilities,
                        },
                    }
                )
                for next_id in section.next:
                    edges.append(
                        {
                            "id": f"edge-{section.id}-{next_id}",
                            "source": section.id,
                            "target": next_id,
                        }
                    )
            lanes.append(
                {
                    "id": chapter.id,
                    "name": chapter.title,
                    "order": chapter.order,
                    "children": children,
                }
            )
        return {"lanes": lanes, "edges": edges}

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _build_summary(content: str) -> str:
        content = content.strip()
        if not content:
            return ""
        for delimiter in ("。", "！", "？", ".", "!", "?"):
            if delimiter in content:
                first_sentence = content.split(delimiter, 1)[0].strip()
                if first_sentence:
                    return f"{first_sentence}{delimiter}"
        return content[:80]
