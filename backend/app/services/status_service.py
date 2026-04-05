from __future__ import annotations


def calculate_aggregate_vector_status(
    *,
    file_ext: str,
    text_status: str | None,
    text_error: str | None,
    image_status: str | None,
    image_error: str | None,
) -> tuple[str, str | None]:
    # 先标准化扩展名，统一大小写和前导点写法。
    extension = file_ext.lower().lstrip(".")
    # 非 PNG 文件只有文本通道，直接走单通道状态规则。
    if extension != "png":
        return _single_channel_status(text_status, text_error)

    # PNG 走双通道，任一子通道失败都应把总状态标记为 FAILED。
    if text_status == "FAILED":
        return "FAILED", text_error
    # 文本没失败但图片失败时，总状态同样失败并返回图片错误。
    if image_status == "FAILED":
        return "FAILED", image_error
    # 文本和图片都完成时，总状态为 VECTORIZED。
    if text_status == "VECTORIZED" and image_status == "VECTORIZED":
        return "VECTORIZED", None
    # 只要任一通道还在处理中（或文本已完成另一通道处理中），总状态保持 PROCESSING。
    if text_status in {"PROCESSING", "VECTORIZED"} or image_status in {"PROCESSING", "VECTORIZED"}:
        return "PROCESSING", None
    # 其他情况视为未开始，返回 PENDING。
    return "PENDING", None


def _single_channel_status(status: str | None, error: str | None) -> tuple[str, str | None]:
    # 单通道失败时，总状态就是 FAILED 并携带错误信息。
    if status == "FAILED":
        return "FAILED", error
    # 单通道完成时，总状态为 VECTORIZED。
    if status == "VECTORIZED":
        return "VECTORIZED", None
    # 单通道处理中时，总状态为 PROCESSING。
    if status == "PROCESSING":
        return "PROCESSING", None
    # 其余情况默认为 PENDING。
    return "PENDING", None
