from types import SimpleNamespace

from app.services.image_embedding_service import ImageEmbeddingService


class FakeMultimodalApi:
    def __init__(self) -> None:
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.0, 3.0, 4.0])])


class FakeArkClient:
    def __init__(self) -> None:
        self.multimodal_embeddings = FakeMultimodalApi()


class ImageEmbeddingServiceHarness(ImageEmbeddingService):
    def __init__(self, settings, client) -> None:
        super().__init__(settings)
        self._client = client

    def _create_client(self):
        return self._client


def test_image_embedding_service_calls_multimodal_endpoint() -> None:
    client = FakeArkClient()
    service = ImageEmbeddingServiceHarness(
        SimpleNamespace(
            ark_api_key="demo-key",
            ark_base_url="https://ark.example.com/api/v3",
            ark_multimodal_embedding_endpoint_id="ep-image-demo",
        ),
        client,
    )

    vector = service.embed_image(
        image_url="https://example.com/demo.png",
        prompt_text="系统架构图",
    )

    assert client.multimodal_embeddings.calls == [
        {
            "model": "ep-image-demo",
            "input": [
                {"type": "text", "text": "系统架构图"},
                {
                    "type": "image_url",
                    "image_url": {"url": "https://example.com/demo.png"},
                },
            ],
        }
    ]
    assert vector == [0.0, 0.6, 0.8]


def test_image_embedding_service_truncates_to_pgvector_image_dimension() -> None:
    client = FakeArkClient()
    service = ImageEmbeddingServiceHarness(
        SimpleNamespace(
            ark_api_key="demo-key",
            ark_base_url="https://ark.example.com/api/v3",
            ark_multimodal_embedding_endpoint_id="ep-image-demo",
            pgvector_image_vector_dimension=2,
        ),
        client,
    )

    vector = service.embed_image(
        image_url="https://example.com/demo.png",
        prompt_text="系统架构图",
    )

    assert vector == [0.0, 1.0]
