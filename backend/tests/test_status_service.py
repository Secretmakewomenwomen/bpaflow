from app.services.status_service import calculate_aggregate_vector_status


def test_docx_aggregate_status_follows_text_channel() -> None:
    status, error = calculate_aggregate_vector_status(
        file_ext="docx",
        text_status="VECTORIZED",
        text_error=None,
        image_status=None,
        image_error=None,
    )

    assert status == "VECTORIZED"
    assert error is None


def test_png_aggregate_status_requires_both_channels_success() -> None:
    status, error = calculate_aggregate_vector_status(
        file_ext="png",
        text_status="VECTORIZED",
        text_error=None,
        image_status="PROCESSING",
        image_error=None,
    )

    assert status == "PROCESSING"
    assert error is None


def test_png_aggregate_status_fails_if_either_channel_fails() -> None:
    status, error = calculate_aggregate_vector_status(
        file_ext="png",
        text_status="VECTORIZED",
        text_error=None,
        image_status="FAILED",
        image_error="multimodal failed",
    )

    assert status == "FAILED"
    assert error == "multimodal failed"


def test_png_aggregate_status_is_vectorized_when_both_channels_succeed() -> None:
    status, error = calculate_aggregate_vector_status(
        file_ext="png",
        text_status="VECTORIZED",
        text_error=None,
        image_status="VECTORIZED",
        image_error=None,
    )

    assert status == "VECTORIZED"
    assert error is None
