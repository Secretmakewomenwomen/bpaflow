import logging
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.ai.services.langgraph_assistant import initialize_postgres_checkpointer
from app.ai.event_stream import AgentEventStream
from app.api.routes.agent import router as agent_router
from app.api.routes.uploads import router as upload_router
from app.api.routes.auth import router as auth_router
from app.api.routes.canvas import router as canvas_router
from app.api.routes.work import router as work_router
from app.api.routes.ai import router as ai_router
from app.api.routes.tenants import router as tenant_router
from app.api.routes.mcp_rag import router as mcp_rag_router
from app.api.routes.mcp_memory import router as mcp_memory_router
from app.api.routes.mcp_llm_gateway import router as mcp_llm_gateway_router
from app.api.routes.mcp_business_tools import router as mcp_business_tools_router
from app.mcp.client import McpSessionClient
from app.core.config import get_settings
from app.core.database import (
    create_tables,
    ensure_tenant_registry_schema,
    ensure_ai_message_schema,
    ensure_ai_agent_trace_schema,
    ensure_canvas_schema,
    ensure_pg_search_ready,
    ensure_pgvector_extension,
    ensure_worker_file_schema,
    ensure_uploaded_file_schema,
    ensure_vector_store_schema,
    get_engine,
)

app = FastAPI(title="Architecture Workbench Backend")
app.state.agent_event_stream = AgentEventStream()
logger = logging.getLogger(__name__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "http://localhost:8080"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api")
app.include_router(canvas_router, prefix="/api")
app.include_router(upload_router, prefix="/api")
app.include_router(work_router, prefix="/api")
app.include_router(ai_router, prefix="/api")
app.include_router(agent_router, prefix="/api")
app.include_router(tenant_router, prefix="/api")
app.include_router(mcp_rag_router, prefix="/api")
app.include_router(mcp_memory_router, prefix="/api")
app.include_router(mcp_llm_gateway_router, prefix="/api")
app.include_router(mcp_business_tools_router, prefix="/api")


@app.on_event("startup")
def startup() -> None:
    app.state.agent_event_stream = AgentEventStream()
    settings = get_settings()
    engine = get_engine()
    if settings.should_bootstrap_schema:
        ensure_tenant_registry_schema(engine)
        ensure_pgvector_extension(engine)
        ensure_uploaded_file_schema(engine)
        ensure_worker_file_schema(engine)
        create_tables(engine)
        ensure_ai_message_schema(engine)
        ensure_ai_agent_trace_schema(engine)
        ensure_canvas_schema(engine)
        ensure_vector_store_schema(engine)
    else:
        logger.info("startup schema bootstrap is disabled; skipping DDL bootstrap steps")
    ensure_pg_search_ready(engine)
    initialize_postgres_checkpointer(settings)


@app.on_event("shutdown")
def shutdown() -> None:
    McpSessionClient.close_pool()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> dict[str, Any]:
    return {
        "status": "ok",
        "mcp_session_pool": McpSessionClient.get_metrics(),
    }
