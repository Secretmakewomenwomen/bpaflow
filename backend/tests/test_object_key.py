from datetime import datetime
import re

from app.utils.object_key import build_object_key


def test_build_object_key_uses_date_partition_and_uuid_suffix() -> None:
    key = build_object_key("diagram.pdf", now=datetime(2026, 3, 24, 12, 0, 0))

    assert re.fullmatch(
        r"uploads/2026/03/24/[0-9a-f]{32}\.pdf",
        key,
    )
