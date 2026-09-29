"""FastAPI entrypoint for the Causal API."""

import asyncio
import logging
import os
import secrets
import sys
import warnings
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from functools import lru_cache
from typing import Any

from fastapi import FastAPI, HTTPException, Path, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.encrypted import EncryptedSerializer
from langgraph.types import Command
from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

from causal.graph.compiler import compile_graph
from causal.graph.handlers import NodeExecutor
from causal.graph.loader import load_graph_config
from causal.models import GroqModelRuntime, ModelNotConfiguredError
from causal.persistence import (
    MemorySessionRepository,
    PostgresSessionRepository,
    SessionRepository,
    SessionStatus,
)
from causal.schemas import (
    HealthResponse,
    PublicReflection,
    ReflectionRequest,
    ReflectionResumeRequest,
    ReflectionTurnResponse,
)

if sys.platform == "win32":
    # Psycopg async requires a selector loop on Windows. This project supports
    # Python <3.15, where the policy API remains the available process-wide hook.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        policy_factory = getattr(asyncio, "WindowsSelectorEventLoopPolicy")  # noqa: B009
        set_event_loop_policy = getattr(asyncio, "set_event_loop_policy")  # noqa: B009
        set_event_loop_policy(policy_factory())

_graph_config = load_graph_config()
_logger = logging.getLogger(__name__)
_session_ttl = timedelta(hours=int(os.getenv("SESSION_TTL_HOURS", "24")))


def _allowed_origins() -> list[str]:
    raw_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")
    return [origin.strip().rstrip("/") for origin in raw_origins.split(",") if origin.strip()]


def _compiled_graph(checkpointer: Any) -> Any:
    runtime = GroqModelRuntime(_graph_config)
    return compile_graph(
        _graph_config,
        NodeExecutor(_graph_config, runtime),
        checkpointer=checkpointer,
    )


def _checkpoint_serializer() -> EncryptedSerializer | None:
    key = os.getenv("LANGGRAPH_AES_KEY")
    if not key:
        if os.getenv("ENVIRONMENT", "development").lower() == "production":
            raise RuntimeError("LANGGRAPH_AES_KEY is required in production")
        return None
    return EncryptedSerializer.from_pycryptodome_aes(key=key.encode())


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    database_url = os.getenv("DATABASE_URL")
    environment = os.getenv("ENVIRONMENT", "development").lower()
    if not database_url:
        if environment == "production":
            raise RuntimeError("DATABASE_URL is required in production")
        sessions = MemorySessionRepository(_session_ttl)
        await sessions.setup()
        application.state.graph = _development_graph()
        application.state.sessions = sessions
        yield
        return

    pool = AsyncConnectionPool[AsyncConnection[DictRow]](
        database_url,
        min_size=1,
        max_size=int(os.getenv("DATABASE_POOL_SIZE", "5")),
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool.open(wait=True)
    try:
        saver = AsyncPostgresSaver(pool, serde=_checkpoint_serializer())
        sessions = PostgresSessionRepository(pool, _session_ttl)
        await saver.setup()
        await sessions.setup()
        application.state.graph = _compiled_graph(saver)
        application.state.sessions = sessions
        yield
    finally:
        await pool.close()

app = FastAPI(
    title="Causal API",
    version="0.1.0",
    description="Guided reflection graph API.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "Idempotency-Key", "X-CSRF-Token"],
)


@lru_cache(maxsize=1)
def _development_graph() -> Any:
    return _compiled_graph(InMemorySaver())


@lru_cache(maxsize=1)
def _development_sessions() -> MemorySessionRepository:
    return MemorySessionRepository(_session_ttl)


def _active_graph() -> Any:
    graph = getattr(app.state, "graph", None)
    return graph if graph is not None else _development_graph()


def _active_sessions() -> SessionRepository:
    sessions = getattr(app.state, "sessions", None)
    return sessions if sessions is not None else _development_sessions()


def _require_loopback(request: Request) -> None:
    host = request.client.host if request.client else None
    if host not in {"127.0.0.1", "::1", "testclient"}:
        raise HTTPException(status_code=404, detail="Not found")


def _public_turn(thread_id: str, result: dict[str, Any]) -> ReflectionTurnResponse:
    raw_view = result.get("public_view")
    if not raw_view:
        raise RuntimeError("graph did not produce a public view")
    return ReflectionTurnResponse(
        thread_id=thread_id,
        stage=str(result.get("stage", "unknown")),
        public_view=PublicReflection.model_validate(raw_view),
        awaiting_input="__interrupt__" in result,
    )


async def _invoke_development_graph(
    thread_id: str,
    graph_input: dict[str, Any] | Command,
) -> ReflectionTurnResponse:
    try:
        graph = _active_graph()
        result = await graph.ainvoke(
            graph_input,
            config={
                "configurable": {"thread_id": thread_id},
                "recursion_limit": _graph_config.budgets.recursion_limit,
            },
            durability="sync",
        )
        return _public_turn(thread_id, result)
    except ModelNotConfiguredError as exc:
        raise HTTPException(
            status_code=503,
            detail="Live model execution is not configured.",
        ) from exc
    except Exception as exc:
        _logger.exception("Reflection invocation failed")
        raise HTTPException(
            status_code=503,
            detail="The reflection service is temporarily unavailable.",
        ) from exc


async def _require_active_session(thread_id: str) -> None:
    session_status = await _active_sessions().status(thread_id)
    if session_status == SessionStatus.EXPIRED:
        await _delete_checkpoint(thread_id)
        await _active_sessions().delete(thread_id)
        raise HTTPException(status_code=410, detail="This reflection session has expired.")
    if session_status == SessionStatus.MISSING:
        raise HTTPException(status_code=404, detail="Reflection session not found.")


async def _delete_checkpoint(thread_id: str) -> None:
    checkpointer = getattr(_active_graph(), "checkpointer", None)
    if checkpointer is not None and hasattr(checkpointer, "adelete_thread"):
        await checkpointer.adelete_thread(thread_id)


def _snapshot_turn(thread_id: str, snapshot: Any) -> ReflectionTurnResponse:
    values = dict(snapshot.values)
    awaiting_input = any(getattr(task, "interrupts", ()) for task in snapshot.tasks)
    if awaiting_input:
        values["__interrupt__"] = True
    return _public_turn(thread_id, values)


@app.get("/api/v1/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="causal-api",
        graph_version=_graph_config.graph_version,
    )


@app.get("/api/v1/graph")
async def graph_metadata() -> dict[str, object]:
    """Expose non-sensitive graph metadata for deployment checks."""
    return {
        "graph_id": _graph_config.graph_id,
        "graph_version": _graph_config.graph_version,
        "node_count": len(_graph_config.nodes),
        "graph_compiler_ready": True,
        "model_execution_enabled": bool(os.getenv("GROQ_API_KEY")),
        "durable_persistence_enabled": bool(os.getenv("DATABASE_URL")),
    }


@app.post("/api/v1/reflections", response_model=ReflectionTurnResponse)
async def start_reflection(payload: ReflectionRequest) -> ReflectionTurnResponse:
    """Start an anonymous reflection session that expires automatically."""
    thread_id = secrets.token_hex(24)
    await _active_sessions().create(thread_id)
    return await _invoke_development_graph(thread_id, {"user_text": payload.text})


@app.post("/api/v1/reflections/resume", response_model=ReflectionTurnResponse)
async def resume_reflection(payload: ReflectionResumeRequest) -> ReflectionTurnResponse:
    """Resume an active reflection from a LangGraph interrupt."""
    await _require_active_session(payload.thread_id)
    resume_payload = {
        key: value
        for key, value in {
            "action": payload.action,
            "text": payload.text,
            "focus_id": payload.focus_id,
        }.items()
        if value is not None
    }
    return await _invoke_development_graph(
        payload.thread_id,
        Command(resume=resume_payload),
    )


@app.get("/api/v1/reflections/{thread_id}", response_model=ReflectionTurnResponse)
async def get_reflection(
    thread_id: str = Path(pattern=r"^[0-9a-f]{48}$"),
) -> ReflectionTurnResponse:
    """Read only the public projection of an active session."""
    await _require_active_session(thread_id)
    snapshot = await _active_graph().aget_state(
        {"configurable": {"thread_id": thread_id}}
    )
    if not snapshot.values:
        raise HTTPException(status_code=404, detail="Reflection session not found.")
    return _snapshot_turn(thread_id, snapshot)


@app.delete("/api/v1/reflections/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reflection(
    thread_id: str = Path(pattern=r"^[0-9a-f]{48}$"),
) -> Response:
    """Delete the anonymous session index and all associated checkpoints."""
    await _require_active_session(thread_id)
    await _delete_checkpoint(thread_id)
    await _active_sessions().delete(thread_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/v1/dev/reflections", response_model=ReflectionTurnResponse)
async def start_development_reflection(
    payload: ReflectionRequest,
    request: Request,
) -> ReflectionTurnResponse:
    """Run the real model graph locally without exposing a production session API."""
    _require_loopback(request)
    return await _invoke_development_graph(secrets.token_hex(24), {"user_text": payload.text})


@app.post("/api/v1/dev/reflections/resume", response_model=ReflectionTurnResponse)
async def resume_development_reflection(
    payload: ReflectionResumeRequest,
    request: Request,
) -> ReflectionTurnResponse:
    """Resume a local in-memory interrupt using public user input only."""
    _require_loopback(request)
    resume_payload = {
        key: value
        for key, value in {
            "action": payload.action,
            "text": payload.text,
            "focus_id": payload.focus_id,
        }.items()
        if value is not None
    }
    return await _invoke_development_graph(
        payload.thread_id,
        Command(resume=resume_payload),
    )
