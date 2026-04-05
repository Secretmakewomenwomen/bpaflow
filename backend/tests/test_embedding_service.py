from types import SimpleNamespace

from app.services.embedding_service import EmbeddingService


class FakeMultimodalEmbeddingsApi:
    def __init__(self, failures_before_success: int = 0) -> None:
        self.calls: list[dict] = []
        self.failures_before_success = failures_before_success

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.failures_before_success > 0:
            self.failures_before_success -= 1
            raise RuntimeError("temporary embedding failure")
        payload = []
        for item in kwargs["input"]:
            if item["text"] == "甲":
                payload.append(SimpleNamespace(embedding=[3.0, 4.0, 0.0]))
            else:
                payload.append(SimpleNamespace(embedding=[0.0, 3.0, 4.0]))
        return SimpleNamespace(data=payload)


class FakeClient:
    def __init__(self, failures_before_success: int = 0) -> None:
        self.multimodal_embeddings = FakeMultimodalEmbeddingsApi(
            failures_before_success=failures_before_success
        )


class FakeSingletonBatchEmbeddingsApi:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(kwargs["input"]) > 1:
            return SimpleNamespace(data=SimpleNamespace(embedding=[3.0, 4.0, 0.0]))

        item = kwargs["input"][0]
        if item["text"] == "甲":
            return SimpleNamespace(data=SimpleNamespace(embedding=[3.0, 4.0, 0.0]))
        return SimpleNamespace(data=SimpleNamespace(embedding=[0.0, 3.0, 4.0]))


class FakeSingletonBatchClient:
    def __init__(self) -> None:
        self.multimodal_embeddings = FakeSingletonBatchEmbeddingsApi()


class EmbeddingServiceHarness(EmbeddingService):
    def __init__(self, settings, client) -> None:
        super().__init__(settings)
        self._client = client
        self.sleep_calls: list[float] = []

    def _create_client(self):
        return self._client

    def _sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)


def test_embedding_service_uses_multimodal_ark_endpoint_and_normalizes_vectors() -> None:
    client = FakeClient()
    service = EmbeddingServiceHarness(
        SimpleNamespace(
            embedding_batch_size=8,
            ark_api_key="demo-key",
            ark_base_url="https://ark.example.com/api/v3",
            ark_embedding_endpoint_id="ep-demo",
            doubao_embedding_api_key=None,
            doubao_embedding_base_url=None,
            doubao_embedding_model=None,
            doubao_embedding_dimension=2,
            embedding_api_key="demo-key",
            embedding_base_url="https://ark.example.com/api/v3",
            embedding_model="ep-demo",
            embedding_dimension=2,
        ),
        client,
    )

    vectors = service.embed_texts(["甲", "乙"])

    assert client.multimodal_embeddings.calls == [
        {
            "model": "ep-demo",
            "input": [
                {"type": "text", "text": "甲"},
                {"type": "text", "text": "乙"},
            ],
            "timeout": 30.0,
        },
    ]
    assert vectors == [[0.6, 0.8], [0.0, 1.0]]


def test_embedding_service_falls_back_to_pgvector_text_dimension_when_embedding_dimension_missing() -> None:
    client = FakeClient()
    service = EmbeddingServiceHarness(
        SimpleNamespace(
            embedding_batch_size=8,
            embedding_api_key="demo-key",
            embedding_base_url="https://ark.example.com/api/v3",
            embedding_model="ep-demo",
            embedding_dimension=None,
            pgvector_text_vector_dimension=2,
        ),
        client,
    )

    vectors = service.embed_texts(["甲"])

    assert vectors == [[0.6, 0.8]]


def test_embedding_service_retries_failed_batch_with_timeout_and_backoff() -> None:
    client = FakeClient(failures_before_success=1)
    service = EmbeddingServiceHarness(
        SimpleNamespace(
            embedding_batch_size=8,
            embedding_api_key="demo-key",
            embedding_base_url="https://ark.example.com/api/v3",
            embedding_model="ep-demo",
            embedding_dimension=2,
            embedding_request_timeout_seconds=12.5,
            embedding_max_retries=2,
            embedding_retry_backoff_seconds=0.25,
        ),
        client,
    )

    vectors = service.embed_texts(["甲", "乙"])

    assert len(client.multimodal_embeddings.calls) == 2
    assert client.multimodal_embeddings.calls[0]["timeout"] == 12.5
    assert client.multimodal_embeddings.calls[1]["timeout"] == 12.5
    assert service.sleep_calls == [0.25]
    assert vectors == [[0.6, 0.8], [0.0, 1.0]]


def test_embedding_service_falls_back_to_single_item_requests_when_batch_returns_one_vector() -> None:
    client = FakeSingletonBatchClient()
    service = EmbeddingServiceHarness(
        SimpleNamespace(
            embedding_batch_size=8,
            embedding_api_key="demo-key",
            embedding_base_url="https://ark.example.com/api/v3",
            embedding_model="ep-demo",
            embedding_dimension=2,
        ),
        client,
    )

    vectors = service.embed_texts(["甲", "乙"])

    assert client.multimodal_embeddings.calls == [
        {
            "model": "ep-demo",
            "input": [
                {"type": "text", "text": "甲"},
                {"type": "text", "text": "乙"},
            ],
            "timeout": 30.0,
        },
        {
            "model": "ep-demo",
            "input": [{"type": "text", "text": "甲"}],
            "timeout": 30.0,
        },
        {
            "model": "ep-demo",
            "input": [{"type": "text", "text": "乙"}],
            "timeout": 30.0,
        },
    ]
    assert vectors == [[0.6, 0.8], [0.0, 1.0]]
