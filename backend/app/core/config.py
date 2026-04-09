from functools import lru_cache
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    postgres_database_url: str
    postgres_admin_url: str | None = None
    default_tenant_id: str = "default"
    tenant_auto_create_database: bool = True
    tenant_database_name_prefix: str = "tenant_"
    tenant_database_url_template: str | None = None
    app_env: str = "development"
    startup_schema_bootstrap: bool | None = None

    oss_region: str
    oss_bucket: str
    oss_endpoint: str
    oss_access_key_id: str
    oss_access_key_secret: str
    oss_public_base_url: str

    max_upload_size: int = 10 * 1024 * 1024
    allowed_extensions: tuple[str, ...] = ("docx", "png", "pdf")
    recent_upload_limit: int = 12
    ark_base_url: str | None = None
    ark_api_key: str | None = None
    ark_embedding_endpoint_id: str | None = None
    ark_multimodal_embedding_endpoint_id: str | None = None
    doubao_embedding_base_url: str | None = None
    doubao_embedding_api_key: str | None = None
    doubao_embedding_model: str | None = None
    doubao_embedding_dimension: int | None = None
    assistant_retrieval_top_k: int = 6
    assistant_max_context_blocks: int = 4
    assistant_max_related_files: int = 5
    assistant_enable_bm25: bool = True
    assistant_enable_rule_retrieval: bool = True
    assistant_min_similarity_score: float = 0.40
    assistant_min_final_score: float = 0.25
    assistant_vector_retrieval_top_k: int = 18
    assistant_bm25_retrieval_top_k: int = 18
    assistant_rule_retrieval_top_k: int = 12
    assistant_rule_chunks_per_file: int = 2
    assistant_vector_weight: float = 0.45
    assistant_bm25_weight: float = 0.40
    assistant_rule_weight: float = 0.15
    assistant_bonus_file_name_exact: float = 0.12
    assistant_bonus_term_hit: float = 0.08
    assistant_bonus_recent: float = 0.05
    assistant_bonus_type_match: float = 0.05
    assistant_recent_window_days: int = 7
    assistant_llm_base_url: str | None = None
    assistant_llm_api_key: str | None = None
    assistant_llm_model: str | None = None
    assistant_backend_base_url: str = "http://127.0.0.1:8000"
    assistant_mcp_rag_url: str | None = None
    assistant_mcp_memory_url: str | None = None
    assistant_mcp_llm_gateway_url: str | None = None
    assistant_mcp_business_tools_url: str | None = None
    assistant_mcp_request_timeout_seconds: float = 20.0
    assistant_mcp_llm_timeout_seconds: float = 120.0
    embedding_batch_size: int = 16
    embedding_request_timeout_seconds: float = 30.0
    embedding_max_retries: int = 2
    embedding_retry_backoff_seconds: float = 0.5
    pgvector_text_table: str = "uploaded_file_text_vector"
    pgvector_image_table: str = "uploaded_file_image_vector"
    pgvector_text_vector_dimension: int = 1024
    pgvector_image_vector_dimension: int = 1024
    pgvector_distance_operator: str = "vector_cosine_ops"
    pgvector_hnsw_m: int = 16
    pgvector_hnsw_ef_construction: int = 200
    small_chunk_size: int = 700
    small_chunk_overlap: int = 120
    large_chunk_size: int = 2100
    ocr_language: str = "chi_sim+eng"
    jwt_secret_key: str = "dev-jwt-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60 * 24

    @field_validator("allowed_extensions", mode="before")
    @classmethod
    def normalize_extensions(cls, value: object) -> tuple[str, ...]:
        if isinstance(value, str):
            return tuple(
                item.strip().lower().lstrip(".")
                for item in value.split(",")
                if item.strip()
            )

        return tuple(value)  # type: ignore[arg-type]

    @model_validator(mode="after")
    def populate_assistant_mcp_urls(self) -> "Settings":
        base_url = self.assistant_backend_base_url.rstrip("/")
        if not self.assistant_mcp_rag_url:
            self.assistant_mcp_rag_url = f"{base_url}/api/mcp/rag"
        if not self.assistant_mcp_memory_url:
            self.assistant_mcp_memory_url = f"{base_url}/api/mcp/memory"
        if not self.assistant_mcp_llm_gateway_url:
            self.assistant_mcp_llm_gateway_url = f"{base_url}/api/mcp/llm-gateway"
        if not self.assistant_mcp_business_tools_url:
            self.assistant_mcp_business_tools_url = f"{base_url}/api/mcp/business-tools"
        return self

    @field_validator("assistant_min_similarity_score", "assistant_min_final_score", mode="after")
    @classmethod
    def validate_similarity_score(cls, value: float) -> float:
        if not 0 <= value <= 1:
            raise ValueError("assistant_min_similarity_score and assistant_min_final_score must be between 0 and 1")
        return value

    @field_validator(
        "assistant_vector_retrieval_top_k",
        "assistant_bm25_retrieval_top_k",
        "assistant_rule_retrieval_top_k",
        "assistant_rule_chunks_per_file",
        mode="after",
    )
    @classmethod
    def validate_positive_counts(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("retrieval counts must be positive")
        return value

    @field_validator("assistant_recent_window_days", mode="after")
    @classmethod
    def validate_recent_window(cls, value: int) -> int:
        if value < 0:
            raise ValueError("assistant_recent_window_days must be at least 0")
        return value

    @field_validator("embedding_request_timeout_seconds", mode="after")
    @classmethod
    def validate_embedding_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("embedding timeout must be positive")
        return value

    @field_validator("assistant_mcp_request_timeout_seconds", mode="after")
    @classmethod
    def validate_mcp_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("assistant_mcp_request_timeout_seconds must be positive")
        return value

    @field_validator("assistant_mcp_llm_timeout_seconds", mode="after")
    @classmethod
    def validate_mcp_llm_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("assistant_mcp_llm_timeout_seconds must be positive")
        return value

    @field_validator("embedding_max_retries", mode="after")
    @classmethod
    def validate_embedding_retries(cls, value: int) -> int:
        if value < 0:
            raise ValueError("embedding retries must be at least 0")
        return value

    @field_validator("embedding_retry_backoff_seconds", mode="after")
    @classmethod
    def validate_embedding_backoff(cls, value: float) -> float:
        if value < 0:
            raise ValueError("embedding backoff must be at least 0")
        return value

    @field_validator(
        "assistant_vector_weight",
        "assistant_bm25_weight",
        "assistant_rule_weight",
        mode="after",
    )
    @classmethod
    def validate_weights(cls, value: float) -> float:
        if value < 0:
            raise ValueError("retrieval weights must be non-negative")
        return value

    @field_validator(
        "assistant_bonus_file_name_exact",
        "assistant_bonus_term_hit",
        "assistant_bonus_recent",
        "assistant_bonus_type_match",
        mode="after",
    )
    @classmethod
    def validate_bonuses(cls, value: float) -> float:
        if value < 0:
            raise ValueError("bonus scores must be non-negative")
        return value

    @property
    def database_url(self) -> str:
        if self.postgres_database_url.startswith("postgresql://"):
            return self.postgres_database_url.replace(
                "postgresql://",
                "postgresql+psycopg://",
                1,
            )
        return self.postgres_database_url

    @property
    def embedding_base_url(self) -> str | None:
        return self.ark_base_url or self.doubao_embedding_base_url

    @property
    def embedding_api_key(self) -> str | None:
        return self.ark_api_key or self.doubao_embedding_api_key

    @property
    def embedding_model(self) -> str | None:
        return self.ark_embedding_endpoint_id or self.doubao_embedding_model

    @property
    def embedding_dimension(self) -> int | None:
        return self.doubao_embedding_dimension

    @property
    def should_bootstrap_schema(self) -> bool:
        if self.startup_schema_bootstrap is not None:
            return self.startup_schema_bootstrap
        return self.app_env.lower() in {"dev", "development", "local", "test"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
