"""Bounded node execution for the declarative reflection graph."""

from collections.abc import Callable, Mapping
from typing import Any, cast

from langgraph.types import interrupt
from pydantic import BaseModel

from causal.graph.loader import GraphConfig, NodeConfig
from causal.graph.state import AnalysisState
from causal.models import StructuredModelRuntime
from causal.schemas import (
    AuditDecision,
    HypothesisResult,
    InquiryDecision,
    NextStepDecision,
    PathDecision,
    PathFinding,
    PublicReflection,
    SafetyDecision,
    SegmentationResult,
)

SCHEMA_REGISTRY: dict[str, type[BaseModel]] = {
    "SafetyDecision": SafetyDecision,
    "SegmentationResult": SegmentationResult,
    "PathDecision": PathDecision,
    "PathFinding": PathFinding,
    "NextStepDecision": NextStepDecision,
    "HypothesisResult": HypothesisResult,
    "InquiryDecision": InquiryDecision,
    "PublicReflection": PublicReflection,
    "AuditDecision": AuditDecision,
}
SPECIALIST_NODES = {
    "inspect_hurt": "hurt",
    "inspect_desire": "desire",
    "inspect_fear": "fear",
    "inspect_judgement": "judgement",
    "inspect_unrelatability": "unrelatability",
    "inspect_ignorance": "ignorance",
    "inspect_general": "general",
}


def _public_view(
    *,
    status: str,
    summary: str,
    statements: list[dict[str, Any]] | None = None,
    pending_question: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "summary": summary,
        "statements": statements or [],
        "selected_focus_id": None,
        "hypotheses": [],
        "unresolved_percent": None,
        "understanding": None,
        "boundary": None,
        "responsibility": None,
        "pending_question": pending_question,
        "next_step": None,
    }


class NodeExecutor:
    def __init__(self, config: GraphConfig, model_runtime: StructuredModelRuntime) -> None:
        self.config = config
        self.model_runtime = model_runtime

    async def execute(self, node: NodeConfig, state: AnalysisState) -> AnalysisState:
        if node.kind.startswith("llm_"):
            return await self._execute_model_node(node, state)
        handler = getattr(self, f"_handle_{node.handler}", None)
        if handler is None:
            raise ValueError(f"handler is not allowlisted: {node.handler}")
        deterministic_handler = cast(Callable[[AnalysisState], AnalysisState], handler)
        return deterministic_handler(state)

    async def _execute_model_node(
        self, node: NodeConfig, state: AnalysisState
    ) -> AnalysisState:
        attempts = state.get("model_attempt_count", 0)
        if attempts >= self.config.budgets.max_model_attempts:
            return {"route": "unavailable", "stage": "model_budget_exhausted"}
        if not node.prompt_ref or not node.output_schema:
            raise ValueError(f"LLM node is missing prompt/schema: {node.id}")
        schema = SCHEMA_REGISTRY[node.output_schema]
        result = await self.model_runtime.ainvoke(node.id, node.prompt_ref, schema, state)
        update: AnalysisState = {"model_attempt_count": attempts + 1, "stage": node.id}
        update.update(self._apply_model_result(node.id, result, state))
        return update

    def _apply_model_result(
        self, node_id: str, result: BaseModel, state: AnalysisState
    ) -> AnalysisState:
        data = result.model_dump(mode="json")
        if isinstance(result, SegmentationResult):
            statements = {item["id"]: item for item in data["statements"]}
            evidence = {
                f"evidence_{item_id}": {
                    "id": f"evidence_{item_id}",
                    "text": item["text"],
                    "status": "user_report",
                    "statement_id": item_id,
                    "source_id": None,
                }
                for item_id, item in statements.items()
            }
            return {
                "statements": statements,
                "evidence": evidence,
                "input_summary": data["summary"],
            }
        if isinstance(result, PathFinding):
            findings = dict(state.get("path_findings", {}))
            findings[node_id] = data
            visited = list(state.get("visited_lenses", []))
            if result.lens.value not in visited:
                visited.append(result.lens.value)
            return {"path_findings": findings, "visited_lenses": visited}
        if isinstance(result, HypothesisResult):
            return {
                "hypotheses": {item["id"]: item for item in data["hypotheses"]},
                "unresolved_percent": data["unresolved_percent"],
                "hypothesis_status": data["status"],
            }
        if isinstance(result, PublicReflection):
            pending = data.get("pending_question")
            question_count = state.get("question_count", 0) + (1 if pending else 0)
            return {
                "public_view": data,
                "pending_input": pending,
                "question_count": question_count,
            }
        if isinstance(result, SafetyDecision):
            return {"route": result.decision, "safety_status": result.decision}
        if isinstance(result, PathDecision):
            return {"route": result.decision, "selected_lens": result.decision}
        if isinstance(result, NextStepDecision):
            decision = result.decision
            redirects = state.get("redirect_count", 0)
            visited = state.get("visited_lenses", [])
            if decision in visited or (
                decision not in {"retrieve_context", "build_hypotheses"}
                and redirects >= self.config.budgets.max_redirects
            ):
                decision = "build_hypotheses"
            return {
                "route": decision,
                "redirect_count": redirects
                + (decision not in {"retrieve_context", "build_hypotheses"}),
            }
        if isinstance(result, InquiryDecision):
            decision = result.decision
            question_limit_reached = (
                state.get("question_count", 0) >= self.config.budgets.max_questions
            )
            if decision == "ask_question" and question_limit_reached:
                decision = "summarize"
            return {"route": decision, "inquiry_decision": data}
        if isinstance(result, AuditDecision):
            decision = result.decision
            repairs = state.get("repair_count", 0)
            if decision == "repair_once" and repairs >= self.config.budgets.max_repairs:
                decision = "safe_fallback"
            return {
                "route": decision,
                "repair_count": repairs + (decision == "repair_once"),
                "audit_issues": data["issues"],
            }
        raise TypeError(f"unhandled model output: {type(result).__name__}")

    def _handle_ingest_turn(self, state: AnalysisState) -> AnalysisState:
        text = state.get("user_text", "").strip()
        if not text or len(text) > self.config.budgets.max_input_chars:
            raise ValueError("user_text must be between 1 and the configured input limit")
        return {
            "schema_version": self.config.schema_version,
            "graph_version": self.config.graph_version,
            "prompt_version": self.config.graph_version,
            "statements": state.get("statements", {}),
            "evidence": state.get("evidence", {}),
            "path_findings": state.get("path_findings", {}),
            "hypotheses": state.get("hypotheses", {}),
            "question_count": state.get("question_count", 0),
            "redirect_count": state.get("redirect_count", 0),
            "repair_count": state.get("repair_count", 0),
            "model_attempt_count": state.get("model_attempt_count", 0),
            "visited_lenses": state.get("visited_lenses", []),
            "revision": state.get("revision", 0) + 1,
            "stage": "ingested",
        }

    def _handle_request_focus(self, state: AnalysisState) -> AnalysisState:
        statements = list(state.get("statements", {}).values())
        pending = {
            "id": f"focus_r{state.get('revision', 0)}",
            "kind": "focus",
            "options": [{"id": item["id"], "text": item["text"]} for item in statements],
        }
        return {
            "pending_input": pending,
            "public_view": _public_view(
                status="awaiting_focus",
                summary="Choose the strand you want to examine first.",
                statements=statements,
            ),
            "stage": "awaiting_focus",
        }

    def _handle_retrieve_context(self, _state: AnalysisState) -> AnalysisState:
        del _state
        return {"retrieved_context": [], "stage": "context_not_required_or_unavailable"}

    def _handle_prepare_public_view(self, state: AnalysisState) -> AnalysisState:
        status = state.get("public_view", {}).get("status")
        route = "await_input" if status in {"awaiting_focus", "awaiting_answer"} else "complete"
        return {"route": route, "stage": "public_view_ready"}

    def _handle_await_input(self, state: AnalysisState) -> AnalysisState:
        payload = state.get("pending_input")
        if not payload:
            raise ValueError("await_input requires a pending input payload")
        response = interrupt(payload)
        return {"resume_payload": response, "stage": "input_received"}

    def _handle_integrate_reply(self, state: AnalysisState) -> AnalysisState:
        raw = state.get("resume_payload")
        if not isinstance(raw, Mapping):
            raise ValueError("resume payload must be an object")
        action = raw.get("action")
        update: AnalysisState = {"pending_input": None, "stage": "reply_integrated"}
        if action in {"answer", "correction"}:
            text = str(raw.get("text", "")).strip()
            if not text or len(text) > self.config.budgets.max_input_chars:
                raise ValueError("resume text is invalid")
            update["user_text"] = f"{state.get('user_text', '')}\n\nFollow-up: {text}".strip()
            update["route"] = action
        elif action == "select_focus":
            focus_id = str(raw.get("focus_id", ""))
            if focus_id not in state.get("statements", {}):
                raise ValueError("selected focus does not exist")
            update["selected_focus_id"] = focus_id
            update["route"] = "answer"
        elif action in {"skip", "finish"}:
            update["route"] = action
        else:
            raise ValueError("unsupported resume action")
        return update

    def _handle_supportive_pause(self, _state: AnalysisState) -> AnalysisState:
        del _state
        return {
            "public_view": _public_view(
                status="supportive_pause",
                summary="This reflection has paused so immediate human support can take priority.",
            ),
            "stage": "supportive_pause",
        }

    def _handle_safe_fallback(self, _state: AnalysisState) -> AnalysisState:
        del _state
        return {
            "public_view": _public_view(
                status="insufficient_information",
                summary=(
                    "There is not enough grounded information to offer a careful "
                    "explanation yet."
                ),
            ),
            "stage": "safe_fallback",
        }

    def _handle_recoverable_error(self, _state: AnalysisState) -> AnalysisState:
        del _state
        return {
            "public_view": _public_view(
                status="recoverable_error",
                summary=(
                    "The reflection could not continue because a required service "
                    "was unavailable."
                ),
            ),
            "stage": "recoverable_error",
        }

    def _handle_complete(self, _state: AnalysisState) -> AnalysisState:
        del _state
        return {"stage": "complete"}
