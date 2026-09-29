"""Safe loader and structural validator for the canonical graph YAML."""

from collections import deque
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_GRAPH_BYTES = 128_000
ALLOWED_NODE_KINDS = {"deterministic", "llm_action", "llm_decision", "retrieval", "interrupt"}
ALLOWED_HANDLERS = {
    "ingest_turn",
    "run_action",
    "run_decision",
    "request_focus",
    "retrieve_context",
    "prepare_public_view",
    "await_input",
    "integrate_reply",
    "supportive_pause",
    "safe_fallback",
    "recoverable_error",
    "complete",
}
LiteralVersion = Literal["1"]


class StrictConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BudgetConfig(StrictConfig):
    max_input_chars: int = Field(gt=0, le=20_000)
    max_model_attempts: int = Field(gt=0, le=50)
    max_questions: int = Field(ge=0, le=5)
    max_redirects: int = Field(ge=0, le=5)
    max_repairs: int = Field(ge=0, le=2)
    recursion_limit: int = Field(gt=0, le=100)
    call_timeout_seconds: int = Field(gt=0, le=120)
    soft_deadline_seconds: int = Field(gt=0, le=240)
    hard_deadline_seconds: int = Field(gt=0, le=290)

    @model_validator(mode="after")
    def validate_deadlines(self) -> "BudgetConfig":
        if self.soft_deadline_seconds >= self.hard_deadline_seconds:
            raise ValueError("soft deadline must be below hard deadline")
        return self


class NodeConfig(StrictConfig):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    kind: str
    handler: str
    prompt_ref: str | None = None
    output_schema: str | None = None

    @model_validator(mode="after")
    def validate_kind(self) -> "NodeConfig":
        if self.kind not in ALLOWED_NODE_KINDS:
            raise ValueError(f"unsupported node kind: {self.kind}")
        if self.handler not in ALLOWED_HANDLERS:
            raise ValueError(f"unsupported handler: {self.handler}")
        if self.kind.startswith("llm_") and (not self.prompt_ref or not self.output_schema):
            raise ValueError("LLM nodes require prompt_ref and output_schema")
        return self


class EdgeConfig(StrictConfig):
    source: str
    target: str
    outcome: str | None = None


class GraphConfig(StrictConfig):
    schema_version: LiteralVersion
    graph_id: str
    graph_version: str
    state_schema: str
    entrypoint: str
    terminal_nodes: list[str]
    budgets: BudgetConfig
    nodes: list[NodeConfig]
    edges: list[EdgeConfig]
    prompt_manifest: dict[str, str]

    @model_validator(mode="after")
    def validate_topology(self) -> "GraphConfig":
        ids = [node.id for node in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("node IDs must be unique")
        known = set(ids)
        if self.entrypoint not in known:
            raise ValueError("entrypoint must reference a node")
        if not set(self.terminal_nodes).issubset(known):
            raise ValueError("terminal_nodes must reference known nodes")
        for edge in self.edges:
            if edge.source not in known or edge.target not in known:
                raise ValueError(f"edge references unknown node: {edge.source} -> {edge.target}")

        outgoing: dict[str, list[EdgeConfig]] = {node_id: [] for node_id in known}
        for edge in self.edges:
            outgoing[edge.source].append(edge)
        for node_id, edges in outgoing.items():
            if node_id in self.terminal_nodes:
                if edges:
                    raise ValueError(f"terminal node has outgoing edges: {node_id}")
                continue
            if not edges:
                raise ValueError(f"non-terminal node has no outgoing edge: {node_id}")
            outcomes = [edge.outcome for edge in edges]
            if len(edges) == 1 and outcomes[0] is None:
                continue
            if any(outcome is None for outcome in outcomes):
                raise ValueError(f"conditional edge group has a missing outcome: {node_id}")
            if len(outcomes) != len(set(outcomes)):
                raise ValueError(f"conditional outcomes must be unique: {node_id}")

        adjacency: dict[str, set[str]] = {node_id: set() for node_id in known}
        for edge in self.edges:
            adjacency[edge.source].add(edge.target)
        reachable: set[str] = set()
        queue = deque([self.entrypoint])
        while queue:
            current = queue.popleft()
            if current in reachable:
                continue
            reachable.add(current)
            queue.extend(adjacency[current] - reachable)
        unreachable = known - reachable
        if unreachable:
            raise ValueError(f"unreachable nodes: {sorted(unreachable)}")

        reverse: dict[str, set[str]] = {node_id: set() for node_id in known}
        for edge in self.edges:
            reverse[edge.target].add(edge.source)
        can_terminate: set[str] = set()
        queue = deque(self.terminal_nodes)
        while queue:
            current = queue.popleft()
            if current in can_terminate:
                continue
            can_terminate.add(current)
            queue.extend(reverse[current] - can_terminate)
        without_terminal_path = known - can_terminate
        if without_terminal_path:
            raise ValueError(f"nodes without a terminal path: {sorted(without_terminal_path)}")
        return self


def _validate_prompt_files(config: GraphConfig, graph_path: Path) -> None:
    package_root = graph_path.parent.parent.resolve()
    for node in config.nodes:
        if not node.prompt_ref:
            continue
        relative_path = config.prompt_manifest.get(node.prompt_ref)
        if relative_path is None:
            raise ValueError(f"prompt is missing from manifest: {node.prompt_ref}")
        prompt_path = (graph_path.parent / relative_path).resolve()
        if not prompt_path.is_relative_to(package_root):
            raise ValueError(f"prompt path escapes package root: {node.prompt_ref}")
        if not prompt_path.is_file():
            raise ValueError(f"prompt file does not exist: {node.prompt_ref}")


def load_graph_config(path: Path | None = None) -> GraphConfig:
    graph_path = path or Path(__file__).with_name("graph.yaml")
    raw = graph_path.read_bytes()
    if len(raw) > MAX_GRAPH_BYTES:
        raise ValueError("graph configuration exceeds size limit")
    data: dict[str, Any] = yaml.safe_load(raw.decode("utf-8"))
    config = GraphConfig.model_validate(data)
    _validate_prompt_files(config, graph_path)
    return config
