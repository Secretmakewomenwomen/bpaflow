from __future__ import annotations

# 数学库用于计算向量的 L2 范数，后面会用它做归一化。
import math

# 读取项目配置，统一拿多模态向量接口的鉴权与维度参数。
from app.core.config import Settings


class ImageEmbeddingService:
    # 图片通道单独封装 ARK 多模态向量接口，避免和文本 embedding 逻辑耦合。
    def __init__(self, settings: Settings) -> None:
        # 保存全局配置，后续创建客户端和截断向量维度都从这里读取。
        self.settings = settings

    # 当前阶段使用“文本提示 + 图片 URL”的多模态向量请求，为图搜图能力预留空间。
    def embed_image(self, *, image_url: str, prompt_text: str) -> list[float]:
        # 先创建 Ark 客户端，后面所有多模态 embedding 请求都通过它发出。
        client = self._create_client()
        # 把提示词和图片地址一起发给多模态 embedding 接口，获取图文联合语义向量。
        response = client.multimodal_embeddings.create(
            # 指定多模态 embedding 所使用的模型 endpoint。
            model=self._require(
                self.settings.ark_multimodal_embedding_endpoint_id,
                "ARK_MULTIMODAL_EMBEDDING_ENDPOINT_ID",
            ),
            # 输入同时包含文本提示和图片 URL，接口会基于这两部分内容生成向量。
            input=[
                # 文本提示用于告诉模型当前要强调的语义方向。
                {"type": "text", "text": prompt_text},
                # 图片 URL 指向真正要向量化的图片内容。
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        )
        # 从响应对象中取出第一条 embedding，并转成普通 Python 列表。
        vector = list(response.data[0].embedding)
        # 读取 pgvector 图片表要求的目标维度；如果未配置就保持模型原始维度。
        target_dimension = getattr(self.settings, "pgvector_image_vector_dimension", None)
        # 如果配置了目标维度，就把向量截断到库表 schema 需要的长度。
        if target_dimension:
            vector = vector[:target_dimension]
        # 返回归一化后的向量，保证后续余弦相似度检索更稳定。
        return self._normalize_vector(vector)

    def _create_client(self):
        try:
            # 延迟导入 Ark SDK，避免测试环境在未安装依赖时一导入模块就报错。
            from volcenginesdkarkruntime import Ark
        except ImportError as exc:
            # 如果 SDK 缺失，就抛出更明确的运行时异常。
            raise RuntimeError("volcenginesdkarkruntime is not installed") from exc

        # 创建 Ark 客户端，并从配置中读取访问所需的 API Key。
        return Ark(api_key=self._require(self.settings.ark_api_key, "ARK_API_KEY"))

    def _require(self, value: str | None, key: str) -> str:
        # 配置为空时立即失败，避免真正发请求时才出现难定位的问题。
        if not value:
            raise RuntimeError(f"{key} is not configured")
        # 返回已经校验过的配置值，调用方可以放心使用。
        return value

    def _normalize_vector(self, vector: list[float]) -> list[float]:
        # 空向量直接返回，避免后续求范数时出现无意义计算。
        if not vector:
            return vector
        # 计算向量的 L2 范数，作为归一化除数。
        norm = math.sqrt(sum(value * value for value in vector))
        # 如果范数为 0，说明向量没有有效长度，直接原样返回。
        if norm == 0:
            return vector
        # 用每个分量除以范数，得到单位向量。
        return [value / norm for value in vector]
