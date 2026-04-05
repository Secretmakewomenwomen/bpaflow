import pytest

from app.utils.file_validation import (
    FileValidationError,
    get_extension,
    validate_extension,
    validate_size,
)


def test_get_extension_returns_lowercase_suffix() -> None:
    assert get_extension("System.DOCX") == "docx"


def test_validate_extension_accepts_allowed_file() -> None:
    validate_extension("report.docx", {"docx", "png", "pdf"})


def test_validate_extension_rejects_disallowed_file() -> None:
    with pytest.raises(FileValidationError):
        validate_extension("report.exe", {"docx", "png", "pdf"})


def test_validate_size_rejects_large_file() -> None:
    with pytest.raises(FileValidationError):
        validate_size((10 * 1024 * 1024) + 1, 10 * 1024 * 1024)
