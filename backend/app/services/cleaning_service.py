from __future__ import annotations

# 正则用于去 HTML 标签和压缩空白字符。
import re
# Counter 用于统计重复页眉页脚出现次数。
from collections import Counter

# ParsedSegment 是清洗前后统一使用的标准片段结构。
from app.services.document_types import ParsedSegment


class TextCleaningService:
    # 统一清洗入口：把不同来源的原始文本先标准化，再做页眉页脚去重，避免脏数据进入切块和 embedding。
    def clean_segments(self, segments: list[ParsedSegment]) -> list[ParsedSegment]:
        # 先逐段做基础标准化，例如去分页符、去 HTML、压缩空白。
        normalized_segments = [self._normalize_segment(segment) for segment in segments]
        # 再基于分页信息去掉多页重复出现的页眉页脚。
        normalized_segments = self._remove_repeated_headers_and_footers(normalized_segments)
        # 最后过滤掉已经清洗成空文本的片段。
        return [segment for segment in normalized_segments if segment.text]

    # 单段清洗：先去分页符和 HTML，再把换行与空白压平，为后面的跨页规则处理打基础。
    def _normalize_segment(self, segment: ParsedSegment) -> ParsedSegment:
        # 把分页符先替换成换行，便于统一按行处理。
        text = segment.text.replace("\f", "\n")
        # 去掉可能混在文本里的 HTML 标签。
        text = self._strip_html(text)
        # 逐行压缩行内空白，保留“按行”这一层结构。
        lines = [self._normalize_inline_whitespace(line) for line in text.splitlines()]
        # 删除清洗后为空的行。
        lines = [line for line in lines if line]
        # 返回新的 ParsedSegment，页码和来源类型保持不变。
        return ParsedSegment(
            # 重新用换行把有效行拼接回来。
            text="\n".join(lines),
            # 保留原始起始页码，后续切块和回溯定位还要用。
            page_start=segment.page_start,
            # 保留原始结束页码。
            page_end=segment.page_end,
            # 保留原始来源类型，例如 pdf_text 或 ocr。
            source_type=segment.source_type,
        )

    # 对分页文本做轻量页眉页脚去重：只移除多页重复出现的首行/尾行，避免误删正文。
    def _remove_repeated_headers_and_footers(
        self,
        segments: list[ParsedSegment],
    ) -> list[ParsedSegment]:
        # 只挑出带页码的片段，因为只有分页文本才有页眉页脚这个概念。
        page_segments = [segment for segment in segments if segment.page_start is not None]
        # 如果分页片段不足两页，就没有“重复页眉页脚”可言，直接压平成单行返回。
        if len(page_segments) < 2:
            return [self._flatten_segment(segment) for segment in segments]

        # 统计每一页首行重复了多少次。
        header_counter = Counter()
        # 统计每一页尾行重复了多少次。
        footer_counter = Counter()
        # line_map 保存每个片段拆分后的行列表，后面真正清洗时复用。
        line_map: list[list[str]] = []

        # 遍历所有片段，收集每段的首行和尾行。
        for segment in segments:
            # 去掉空行后保留该片段所有有效文本行。
            lines = [line for line in segment.text.splitlines() if line]
            # 把当前片段的行列表保存起来，后面不用再重复 splitlines。
            line_map.append(lines)
            # 只有既有行又带页码的片段，才参与页眉页脚统计。
            if lines and segment.page_start is not None:
                # 第一行作为候选页眉计数。
                header_counter[lines[0]] += 1
                # 最后一行作为候选页脚计数。
                footer_counter[lines[-1]] += 1

        # 出现至少两次的首行，被认为是重复页眉。
        repeated_headers = {
            line for line, count in header_counter.items() if count >= 2
        }
        # 出现至少两次的尾行，被认为是重复页脚。
        repeated_footers = {
            line for line, count in footer_counter.items() if count >= 2
        }

        # 保存清洗后的片段列表。
        cleaned_segments: list[ParsedSegment] = []
        # 将原始片段和对应的行列表一一配对处理。
        for segment, lines in zip(segments, line_map, strict=False):
            # 复制一份当前行列表，避免直接修改原数据。
            current_lines = lines[:]
            # 如果首行属于重复页眉，就把它移除。
            if current_lines and current_lines[0] in repeated_headers:
                current_lines = current_lines[1:]
            # 如果尾行属于重复页脚，就把它移除。
            if current_lines and current_lines[-1] in repeated_footers:
                current_lines = current_lines[:-1]
            # 如果删完后整段为空，就退回原始行列表，避免误删整页正文。
            if not current_lines:
                current_lines = lines
            # 把清洗后的行重新拼成新的片段对象。
            cleaned_segments.append(
                ParsedSegment(
                    # 页眉页脚移除后，把剩余行合并成单行文本。
                    text=self._normalize_inline_whitespace(" ".join(current_lines)),
                    # 保留原始起始页码。
                    page_start=segment.page_start,
                    # 保留原始结束页码。
                    page_end=segment.page_end,
                    # 保留原始来源类型。
                    source_type=segment.source_type,
                )
            )

        # 再次过滤掉空文本片段，确保下游拿到的都是有效内容。
        return [segment for segment in cleaned_segments if segment.text]

    # 非分页场景直接把多行压成单行，保证后续切块长度更稳定。
    def _flatten_segment(self, segment: ParsedSegment) -> ParsedSegment:
        # 构造新的单行片段，页码和来源信息原样保留。
        return ParsedSegment(
            # 先把换行替换为空格，再统一压缩连续空白。
            text=self._normalize_inline_whitespace(segment.text.replace("\n", " ")),
            # 保留起始页码。
            page_start=segment.page_start,
            # 保留结束页码。
            page_end=segment.page_end,
            # 保留来源类型。
            source_type=segment.source_type,
        )

    # 优先用 HTML 解析器做结构展开；如果环境里没有 bs4，就退化成正则去标签。
    def _strip_html(self, text: str) -> str:
        # 没有尖括号时可直接认为不是 HTML，原样返回更高效。
        if "<" not in text or ">" not in text:
            return text

        try:
            # 优先使用 BeautifulSoup 做更可靠的 HTML 解析。
            from bs4 import BeautifulSoup
        except ImportError:
            # 如果没有安装 bs4，就用正则粗略去掉标签。
            return re.sub(r"<[^>]+>", " ", text)

        # 把 HTML 展开成纯文本，并用换行保留一定结构感。
        return BeautifulSoup(text, "html.parser").get_text("\n")

    # 统一空白字符，避免 OCR、PDF 抽取和 HTML 展开后的噪声影响切块边界。
    def _normalize_inline_whitespace(self, text: str) -> str:
        # 把连续空白折叠成单个空格，再去掉首尾空白。
        return re.sub(r"\s+", " ", text).strip()
