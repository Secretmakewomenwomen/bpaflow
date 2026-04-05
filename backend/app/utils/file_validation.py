from pathlib import Path


class FileValidationError(ValueError):
    """Raised when an uploaded file does not satisfy policy."""


def get_extension(filename: str) -> str:
    return Path(filename).suffix.lower().lstrip(".")


def validate_extension(filename: str, allowed: set[str] | tuple[str, ...]) -> None:
    extension = get_extension(filename)
    if extension not in set(allowed):
        raise FileValidationError(f"Unsupported file type: .{extension or 'unknown'}")


def validate_size(size: int, max_size: int) -> None:
    if size <= 0:
        raise FileValidationError("Uploaded file is empty")
    if size > max_size:
        raise FileValidationError(f"File exceeds the maximum size of {max_size} bytes")
