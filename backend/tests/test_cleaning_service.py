from app.services.cleaning_service import TextCleaningService
from app.services.document_types import ParsedSegment


def test_clean_segments_strip_html_page_breaks_and_repeated_headers() -> None:
    service = TextCleaningService()

    segments = [
        ParsedSegment(
            text="统一页眉\n<div>第一段\f内容一</div>\n统一页脚",
            page_start=1,
            page_end=1,
            source_type="pdf_text",
        ),
        ParsedSegment(
            text="统一页眉\n<p>第二段</p>\n内容二\n统一页脚",
            page_start=2,
            page_end=2,
            source_type="pdf_text",
        ),
    ]

    cleaned = service.clean_segments(segments)

    assert [segment.text for segment in cleaned] == ["第一段 内容一", "第二段 内容二"]


def test_clean_segments_drop_blank_results() -> None:
    service = TextCleaningService()

    cleaned = service.clean_segments(
        [
            ParsedSegment(text="   \f   ", page_start=None, page_end=None, source_type="docx"),
        ]
    )

    assert cleaned == []


def test_clean_segments_keep_content_when_repeated_line_is_the_only_text() -> None:
    service = TextCleaningService()

    cleaned = service.clean_segments(
        [
            ParsedSegment(text="系统概览", page_start=1, page_end=1, source_type="pdf_text"),
            ParsedSegment(text="系统概览", page_start=2, page_end=2, source_type="pdf_text"),
        ]
    )

    assert [segment.text for segment in cleaned] == ["系统概览", "系统概览"]
