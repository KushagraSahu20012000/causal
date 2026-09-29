"""LangGraph state contract and deterministic merge helpers."""

from typing import Any, TypedDict


class AnalysisState(TypedDict, total=False):
    schema_version: str
    graph_version: str
    prompt_version: str
    user_text: str
    input_summary: str
    statements: dict[str, dict[str, Any]]
    evidence: dict[str, dict[str, Any]]
    selected_focus_id: str | None
    selected_lens: str | None
    path_findings: dict[str, Any]
    hypotheses: dict[str, dict[str, Any]]
    hypothesis_status: str
    unresolved_percent: int | None
    pending_input: dict[str, Any] | None
    resume_payload: Any
    route: str
    inquiry_decision: dict[str, Any]
    audit_issues: list[dict[str, Any]]
    retrieved_context: list[dict[str, Any]]
    question_count: int
    redirect_count: int
    repair_count: int
    model_attempt_count: int
    visited_lenses: list[str]
    safety_status: str
    stage: str
    revision: int
    public_view: dict[str, Any]


def upsert_by_id(
    current: dict[str, dict[str, Any]] | None,
    updates: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    """Merge stable-ID records without accumulating duplicate entries."""
    merged = dict(current or {})
    merged.update(updates or {})
    return merged
