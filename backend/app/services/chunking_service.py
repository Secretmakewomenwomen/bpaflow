from __future__ import annotations

# ParsedSegment 是清洗后的标准输入结构，VectorChunk 是切块后的标准输出结构。
from app.services.document_types import ParsedSegment, VectorChunk


class ChunkingService:
    # 切块参数在初始化时固定下来，方便通过配置统一调优召回粒度和大模型上下文粒度。
    def __init__(
        self,
        small_chunk_size: int = 700,
        small_chunk_overlap: int = 120,
        large_chunk_size: int = 2100,
    ) -> None:
        # 小块长度决定检索粒度，越小越容易命中细节，但上下文也更碎。
        self.small_chunk_size = small_chunk_size
        # 小块重叠长度用于保留相邻块之间的连续上下文。
        self.small_chunk_overlap = small_chunk_overlap
        # 大块长度决定命中后回填给模型的上下文规模。
        self.large_chunk_size = large_chunk_size

    # 统一把清洗后的段落转成“小块检索 + 大块回填”的双层结构。
    def build_chunks(self, segments: list[ParsedSegment]) -> list[VectorChunk]:
        # 没有输入片段时，直接返回空列表。
        if not segments:
            return []

        # draft_chunks 先保存只含 small_chunk 的中间结果，后面再补 large_chunk 信息。
        draft_chunks: list[VectorChunk] = []
        # chunk_index 为所有小块生成连续编号。
        chunk_index = 0
        # 实际滑动步长等于小块长度减去重叠长度，至少保证为 1。
        step = max(1, self.small_chunk_size - self.small_chunk_overlap)

        # 逐段处理清洗后的文本片段。
        for segment in segments:
            # 去掉片段首尾空白，避免切出纯空格块。
            text = segment.text.strip()
            # 当前片段为空时直接跳过。
            if not text:
                continue

            # 如果整个片段长度已经不超过小块上限，就直接作为一个小块输出。
            if len(text) <= self.small_chunk_size:
                draft_chunks.append(
                    VectorChunk(
                        # 这个字段存储真正拿去做 embedding 的小块文本。
                        small_chunk_text=text,
                        # 大块文本后面统一回填，这里先放空字符串。
                        large_chunk_text="",
                        # 写入当前小块编号。
                        small_chunk_index=chunk_index,
                        # 大块编号后续统一补齐。
                        large_chunk_id="",
                        # 保留片段起始页码，方便检索结果定位回原文。
                        page_start=segment.page_start,
                        # 保留片段结束页码。
                        page_end=segment.page_end,
                        # 保留当前片段来源类型。
                        source_type=segment.source_type,
                    )
                )
                # 一个小块已经写出，编号自增。
                chunk_index += 1
                # 当前片段处理完成，进入下一个片段。
                continue

            # 对超长片段启用滑动窗口切分。
            start = 0
            # 只要起始下标还在文本范围内，就继续切块。
            while start < len(text):
                # 按当前窗口截取一段文本，并去掉两端空白。
                piece = text[start : start + self.small_chunk_size].strip()
                # 只把非空片段写成小块。
                if piece:
                    draft_chunks.append(
                        VectorChunk(
                            # 当前窗口截出的文本作为小块内容。
                            small_chunk_text=piece,
                            # 大块文本先占位，后面回填。
                            large_chunk_text="",
                            # 记录全局连续小块编号。
                            small_chunk_index=chunk_index,
                            # 大块编号先留空。
                            large_chunk_id="",
                            # 继承原始片段起始页码。
                            page_start=segment.page_start,
                            # 继承原始片段结束页码。
                            page_end=segment.page_end,
                            # 继承原始片段来源类型。
                            source_type=segment.source_type,
                        )
                    )
                    # 每成功产出一个小块，编号就自增一次。
                    chunk_index += 1
                # 如果当前窗口已经覆盖到文本末尾，就结束循环。
                if start + self.small_chunk_size >= len(text):
                    break
                # 否则按步长向前滑动，保留配置好的重叠部分。
                start += step

        # 如果所有片段最终都没切出有效小块，直接返回空列表。
        if not draft_chunks:
            return []

        # 大块不重新切文本，而是由连续小块拼起来，保证检索命中后能直接回捞连续上下文。
        group_start = 0
        # 大块编号单独递增，和小块编号分开管理。
        large_chunk_index = 0
        # 只要还有未分组的小块，就继续组装大块。
        while group_start < len(draft_chunks):
            # 当前大块从当前 group_start 开始。
            group_end = group_start
            # current_size 用于累计当前大块已经占用的总长度。
            current_size = 0
            # 尽量向后吸收更多连续小块，直到达到大块长度上限。
            while group_end < len(draft_chunks):
                # 读取下一个待拼接小块的文本长度。
                next_size = len(draft_chunks[group_end].small_chunk_text)
                # 只要已经有内容且再加一个小块会超限，就停止扩容当前大块。
                if current_size and current_size + next_size > self.large_chunk_size:
                    break
                # 把当前小块长度累计进大块长度。
                current_size += next_size
                # 继续尝试纳入下一个小块。
                group_end += 1

            # 把当前分组范围内的连续小块文本拼成大块文本。
            large_chunk_text = "".join(
                chunk.small_chunk_text for chunk in draft_chunks[group_start:group_end]
            )
            # 为这个大块生成唯一编号。
            large_chunk_id = f"large-{large_chunk_index}"
            # 回填当前大块覆盖到的每个小块，让它们都能指向同一个大块上下文。
            for chunk in draft_chunks[group_start:group_end]:
                # 给小块写入所属大块编号。
                chunk.large_chunk_id = large_chunk_id
                # 给小块写入对应的大块全文。
                chunk.large_chunk_text = large_chunk_text
            # 当前大块处理完成，下一个大块从尚未分配的小块开始。
            group_start = group_end
            # 大块编号递增。
            large_chunk_index += 1

        # 返回已经补齐大小块信息的最终结果。
        return draft_chunks
