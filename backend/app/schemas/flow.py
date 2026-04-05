from typing import Any

from pydantic import BaseModel, Field


class ChapterPhaseSectionResponse(BaseModel):
    id: str
    title: str
    order: int
    summary: str
    role: str | None = None
    department: str | None = None
    owner: str | None = None
    responsibilities: list[str] = Field(default_factory=list)
    content: str
    next: list[str] = Field(default_factory=list)


class ChapterPhaseChapterResponse(BaseModel):
    id: str
    title: str
    order: int
    sections: list[ChapterPhaseSectionResponse] = Field(default_factory=list)


class ChapterPhaseParseResponse(BaseModel):
    documentTitle: str
    flowType: str
    chapters: list[ChapterPhaseChapterResponse] = Field(default_factory=list)
    graphPayload: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)
