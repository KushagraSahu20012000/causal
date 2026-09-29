"""Vercel-compatible FastAPI entrypoint for the Causal API."""

import logging
import os
from functools import lru_cache
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from causal.graph.compiler import compile_graph
from causal.graph.handlers import NodeExecutor
from causal.graph.loader import load_graph_config
from causal.models import GroqModelRuntime, ModelNotConfiguredError
from causal.schemas import (
    HealthResponse,
    PublicReflection,
    ReflectionRequest,
    ReflectionResumeRequest,
    ReflectionTurnResponse,
)

_graph_config = load_graph_config()
_logger = logging.getLogger(__name__)

app = FastAPI(
    title="Causal API",
    version="0.1.0",
    description="Guided reflection graph API. Model execution is disabled until configured.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "Idempotency-Key", "X-CSRF-Token"],
)


@lru_cache(maxsize=1)
def _development_graph() -> Any:
    runtime = GroqModelRuntime(_graph_config)
    return compile_graph(
        _graph_config,
        NodeExecutor(_graph_config, runtime),
        checkpointer=InMemorySaver(),
    )


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
        graph = _development_graph()
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
        _logger.exception("Development reflection invocation failed")
        raise HTTPException(
            status_code=503,
            detail="The reflection service is temporarily unavailable.",
        ) from exc


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


@app.post("/api/v1/dev/reflections", response_model=ReflectionTurnResponse)
async def start_development_reflection(
    payload: ReflectionRequest,
    request: Request,
) -> ReflectionTurnResponse:
    """Run the real model graph locally without exposing a production session API."""
    _require_loopback(request)
    return await _invoke_development_graph(uuid4().hex, {"user_text": payload.text})


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
