from __future__ import annotations

# 数学库用于计算向量范数，后面会做 L2 归一化。
import math
# 睡眠用于 embedding 重试间隔，避免瞬时抖动时连续打满上游。
import time
# Any 用来兼容第三方 SDK 返回的不完全固定的数据结构。
from typing import Any

# 项目配置对象提供模型、鉴权、批大小和目标维度等参数。
from app.core.config import Settings
# Ark 客户端负责真正调用豆包 embedding 接口。
from volcenginesdkarkruntime import Ark


class EmbeddingService:
    # embedding 服务只负责和豆包模型通信，不关心文件解析、切块或 Milvus 结构。
    def __init__(self, settings: Settings) -> None:
        # 保存配置，后面所有请求参数和维度策略都从这里读取。
        self.settings = settings

    # 按批次生成向量，避免一次性提交过多文本导致请求体过大或接口不稳定。
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        # 没有文本时直接返回空结果，避免发出无意义请求。
        if not texts:
            return []

        # 创建 Ark 客户端，用于后续所有 embedding 调用。
        client = self._create_client()
        # 用列表累计每段文本最终得到的向量。
        embeddings: list[list[float]] = []
        # 批大小至少为 1，防止配置写成 0 导致 range 步长异常。
        batch_size = max(1, self.settings.embedding_batch_size)
        # 读取 embedding 模型 endpoint，没有配置则立即报错。
        model = self._require(self.settings.embedding_model, "ARK_EMBEDDING_ENDPOINT_ID")
        # 解析最终希望写入 pgvector 的向量维度。
        target_dimension = self._resolve_target_dimension()
        timeout_seconds = self._embedding_timeout()

        # 按批次切分输入文本，避免单次处理规模过大。
        for start in range(0, len(texts), batch_size):
            # 取出当前批次的文本子列表。
            batch = texts[start : start + batch_size]
            # 真正的批量 embedding：一个批次只发一次请求，减少网络往返和 QPS 压力。
            response = self._request_batch_embeddings(
                client=client,
                model=model,
                batch=batch,
                timeout_seconds=timeout_seconds,
            )
            vectors = self._extract_embedding_vectors(response.data)
            if len(vectors) != len(batch):
                vectors = self._fallback_to_single_item_embeddings(
                    client=client,
                    model=model,
                    batch=batch,
                    timeout_seconds=timeout_seconds,
                    vectors=vectors,
                )
            for vector in vectors:
                # 如果配置了目标维度，就截断到向量表 schema 期望的长度。
                if target_dimension:
                    vector = vector[:target_dimension]
                # 归一化后再追加到结果列表，方便与余弦相似度匹配。
                embeddings.append(self._normalize_vector(vector))

        # 返回与输入 texts 一一对应的向量列表。
        return embeddings

    def _request_batch_embeddings(
        self,
        *,
        client: Any,
        model: str,
        batch: list[str],
        timeout_seconds: float,
    ) -> Any:
        max_retries = self._embedding_max_retries()
        for attempt in range(max_retries + 1):
            try:
                return client.multimodal_embeddings.create(
                    model=model,
                    input=[{"type": "text", "text": text} for text in batch],
                    timeout=timeout_seconds,
                )
            except Exception:
                if attempt >= max_retries:
                    raise
                backoff = self._embedding_retry_backoff_seconds() * (attempt + 1)
                if backoff > 0:
                    self._sleep(backoff)

    def _fallback_to_single_item_embeddings(
        self,
        *,
        client: Any,
        model: str,
        batch: list[str],
        timeout_seconds: float,
        vectors: list[list[float]],
    ) -> list[list[float]]:
        if len(batch) > 1 and len(vectors) == 1:
            single_vectors: list[list[float]] = []
            for text in batch:
                response = self._request_batch_embeddings(
                    client=client,
                    model=model,
                    batch=[text],
                    timeout_seconds=timeout_seconds,
                )
                one_vectors = self._extract_embedding_vectors(response.data)
                if len(one_vectors) != 1:
                    raise ValueError("Embedding count does not match input batch size")
                single_vectors.append(one_vectors[0])
            return single_vectors

        raise ValueError("Embedding count does not match input batch size")

    # 文本通道直接使用 Ark 客户端，避免 OpenAI 兼容层在方舟 endpoint 上产生请求体差异。
    def _create_client(self):
        # 创建 Ark 客户端时同时校验 API Key 和 Base URL 是否齐全。
        return Ark(
            # API Key 用于访问鉴权。
            api_key=self._require(
                self.settings.embedding_api_key,
                "ARK_API_KEY",
            ),
            # Base URL 指定当前方舟服务地址。
            base_url=self._require(
                self.settings.embedding_base_url,
                "ARK_BASE_URL",
            ),
        )

    # 对必须配置项做硬校验，避免向量化流程在真正发请求时才出现难定位的问题。
    def _require(self, value: str | None, key: str) -> str:
        # 配置缺失时直接抛错，让调用链尽快失败并暴露具体缺的是哪个键。
        if not value:
            raise RuntimeError(f"{key} is not configured")
        # 返回已确认非空的配置值。
        return value

    # 兼容 Ark 多模态接口可能返回单对象或列表对象两种结构，统一提取 embedding 数组。
    def _extract_embedding_vector(self, data: Any) -> list[float]:
        # 如果返回对象本身带有 embedding 属性，直接取出即可。
        if hasattr(data, "embedding"):
            return list(data.embedding)
        # 如果返回的是列表，就取第一项继续判断。
        if isinstance(data, list) and data:
            # 读取列表中的第一项作为当前 embedding 结果。
            first_item = data[0]
            # 第一项存在 embedding 属性时，转成普通列表返回。
            if hasattr(first_item, "embedding"):
                return list(first_item.embedding)
        # 两种结构都不匹配时，抛出类型异常提醒上层接口变更了。
        raise TypeError("Unsupported multimodal embedding response payload")

    def _extract_embedding_vectors(self, data: Any) -> list[list[float]]:
        # 批量模式下优先处理列表响应，保持每个输入对应一个向量。
        if isinstance(data, list):
            vectors: list[list[float]] = []
            for item in data:
                if hasattr(item, "embedding"):
                    vectors.append(list(item.embedding))
                else:
                    raise TypeError("Unsupported multimodal embedding item payload")
            return vectors
        # 兼容某些测试或 SDK 退回单对象结构时，仍然按单条结果处理。
        return [self._extract_embedding_vector(data)]

    def _embedding_timeout(self) -> float:
        return float(getattr(self.settings, "embedding_request_timeout_seconds", 30.0))

    def _embedding_max_retries(self) -> int:
        return max(0, int(getattr(self.settings, "embedding_max_retries", 2)))

    def _embedding_retry_backoff_seconds(self) -> float:
        return max(0.0, float(getattr(self.settings, "embedding_retry_backoff_seconds", 0.5)))

    def _sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    # 文本向量默认以 pgvector 文本表维度为准，避免模型输出维度和库表 schema 脱节。
    def _resolve_target_dimension(self) -> int | None:
        # 先尝试读取专门的 embedding 维度配置。
        embedding_dimension = getattr(self.settings, "embedding_dimension", None)
        # 如果显式配置了 embedding_dimension，就优先使用它。
        if embedding_dimension:
            return embedding_dimension
        # 否则回退到 pgvector 文本表定义的维度。
        return getattr(self.settings, "pgvector_text_vector_dimension", None)

    # 统一做 L2 归一化，保证写入 pgvector 的向量和余弦相似度检索假设一致。
    def _normalize_vector(self, vector: list[float]) -> list[float]:
        # 空向量直接返回，避免对空列表求范数。
        if not vector:
            return vector
        # 计算向量的 L2 范数，也就是平方和开根号。
        norm = math.sqrt(sum(value * value for value in vector))
        # 范数为 0 时无法归一化，直接保留原值。
        if norm == 0:
            return vector
        # 用每个分量除以范数，得到单位长度向量。
        return [value / norm for value in vector]
