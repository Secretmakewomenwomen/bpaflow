from datetime import UTC, datetime
from uuid import uuid4

from app.utils.file_validation import get_extension


def build_object_key(filename: str, now: datetime | None = None) -> str:
    current = now or datetime.now(UTC)
    extension = get_extension(filename)
    object_id = uuid4().hex
    return (
        f"uploads/{current:%Y/%m/%d}/{object_id}.{extension}"
        if extension
        else f"uploads/{current:%Y/%m/%d}/{object_id}"
    )
