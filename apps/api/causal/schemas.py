"""Validated domain and public API contracts for Causal."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StatementKind(StrEnum):
    REPORTED_EVENT = "reported_event"
    FEELING = "feeling"
    INTERPRETATION = "interpretation"
    UNRELATABILITY = "unrelatability"
    MISSING_CONTEXT = "missing_context"
    OTHER = "other"
    UNCLEAR = "unclear"


class Lens(StrEnum):
    HURT = "hurt"
    DESIRE = "desire"
    FEAR = "fear"
    JUDGEMENT = "judgement"
    UNRELATABILITY = "unrelatability"
    IGNORANCE = "ignorance"
    GENERAL = "general"


class EpistemicStatus(StrEnum):
    USER_REPORT = "user_report"
    SOURCE_SUPPORTED_CONTEXT = "source_supported_context"
    TENTATIVE_INFERENCE = "tentative_inference"
    UNKNOWN = "unknown"


class Statement(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=6_000)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    kinds: list[StatementKind] = Field(min_length=1)
    lenses: list[Lens]
    speaker: str | None

    @model_validator(mode="after")
    def validate_span(self) -> "Statement":
        if self.end <= self.start:
            raise ValueError("statement end must be greater than start")
        return self


class Evidence(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=6_000)
    status: EpistemicStatus
    statement_id: str | None
    source_id: str | None


class LineageStep(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    proposition: str = Field(min_length=1, max_length=800)
    layer: str = Field(min_length=1, max_length=80)
    status: EpistemicStatus
    evidence_ids: list[str]
    limits: str | None


class Hypothesis(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=800)
    supporting_evidence_ids: list[str]
    counter_evidence_ids: list[str]
    lineage: list[LineageStep]
    unsupported_assumptions: list[str]
    what_would_strengthen: str | None
    what_would_weaken: str | None
    relative_weight_percent: int | None = Field(ge=0, le=100)
    status: Literal["tentative", "supported_by_user", "rejected"]


class PendingQuestion(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=500)
    tested_hypothesis_ids: list[str]
    reason: str = Field(min_length=1, max_length=500)


class SegmentationResult(StrictModel):
    summary: str = Field(max_length=800)
    statements: list[Statement] = Field(min_length=1, max_length=24)


class PathFinding(StrictModel):
    lens: Lens
    observed_pattern: str = Field(max_length=1_200)
    assumed_problem_or_gap: str = Field(max_length=1_200)
    supporting_evidence_ids: list[str]
    counter_evidence_ids: list[str]
    uncertainties: list[str] = Field(max_length=8)
    boundary_implications: list[str] = Field(max_length=6)
    possible_next_lenses: list[Lens] = Field(max_length=3)


class HypothesisResult(StrictModel):
    status: Literal["hypotheses_available", "insufficient_information"]
    hypotheses: Annotated[list[Hypothesis], Field(max_length=3)]
    unresolved_percent: int | None = Field(ge=0, le=100)

    @model_validator(mode="after")
    def validate_hypothesis_weights(self) -> "HypothesisResult":
        if self.status == "insufficient_information":
            if self.hypotheses or self.unresolved_percent is not None:
                raise ValueError("insufficient information cannot include weighted hypotheses")
            return self
        weights = [item.relative_weight_percent for item in self.hypotheses]
        if not self.hypotheses:
            raise ValueError("available status requires at least one hypothesis")
        if any(weight is None for weight in weights):
            if self.unresolved_percent is not None:
                raise ValueError("unresolved_percent requires weights on every hypothesis")
            return self
        if self.unresolved_percent is None:
            raise ValueError("weighted hypotheses require unresolved_percent")
        numeric_weights = [weight for weight in weights if weight is not None]
        if sum(numeric_weights) + self.unresolved_percent != 100:
            raise ValueError("hypothesis weights and unresolved_percent must total 100")
        return self


class DecisionBase(StrictModel):
    evidence_ids: list[str]
    decision_summary: str = Field(max_length=500)


class SafetyDecision(DecisionBase):
    decision: Literal["continue_reflection", "pause_for_support", "unavailable"]


class PathDecision(DecisionBase):
    decision: Literal[
        "request_focus",
        "hurt",
        "desire",
        "fear",
        "judgement",
        "unrelatability",
        "ignorance",
        "general",
    ]


class NextStepDecision(DecisionBase):
    decision: Literal[
        "retrieve_context",
        "build_hypotheses",
        "hurt",
        "desire",
        "fear",
        "judgement",
        "unrelatability",
        "ignorance",
    ]


class InquiryDecision(DecisionBase):
    decision: Literal["ask_question", "summarize", "insufficient_information"]
    tested_hypothesis_ids: list[str]
    missing_distinction: str | None


class AuditIssue(StrictModel):
    code: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=500)
    evidence_ids: list[str]


class AuditDecision(DecisionBase):
    decision: Literal["accept", "repair_once", "safe_fallback"]
    issues: list[AuditIssue] = Field(max_length=12)


class PublicReflection(StrictModel):
    status: Literal[
        "draft",
        "awaiting_focus",
        "awaiting_answer",
        "complete",
        "insufficient_information",
        "supportive_pause",
        "recoverable_error",
    ]
    summary: str
    statements: list[Statement]
    selected_focus_id: str | None
    hypotheses: Annotated[list[Hypothesis], Field(max_length=3)]
    unresolved_percent: int | None = Field(ge=0, le=100)
    understanding: str | None
    boundary: str | None
    responsibility: str | None
    pending_question: PendingQuestion | None
    next_step: str | None

    @model_validator(mode="after")
    def validate_weights(self) -> "PublicReflection":
        weights = [
            item.relative_weight_percent
            for item in self.hypotheses
            if item.relative_weight_percent is not None
        ]
        if not weights:
            if self.unresolved_percent is not None:
                raise ValueError("unresolved_percent requires weighted hypotheses")
            return self
        if len(weights) != len(self.hypotheses):
            raise ValueError("hypothesis weights must be all present or all absent")
        if self.unresolved_percent is None:
            raise ValueError("weighted hypotheses require unresolved_percent")
        if sum(weights) + self.unresolved_percent != 100:
            raise ValueError("hypothesis weights and unresolved_percent must total 100")
        return self


class ReflectionRequest(StrictModel):
    text: str = Field(min_length=1, max_length=6_000)


class ReflectionResumeRequest(StrictModel):
    thread_id: str = Field(min_length=32, max_length=64)
    action: Literal["answer", "correction", "select_focus", "skip", "finish"]
    text: str | None = Field(default=None, max_length=6_000)
    focus_id: str | None = Field(default=None, max_length=200)


class ReflectionTurnResponse(StrictModel):
    thread_id: str
    stage: str
    public_view: PublicReflection
    awaiting_input: bool


class HealthResponse(StrictModel):
    status: Literal["ok"]
    service: Literal["causal-api"]
    graph_version: str
