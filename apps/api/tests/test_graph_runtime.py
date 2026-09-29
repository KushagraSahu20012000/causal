from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import BaseModel

from causal.graph.compiler import compile_graph
from causal.graph.handlers import NodeExecutor
from causal.graph.loader import load_graph_config
from causal.graph.state import AnalysisState

STATEMENT = {
    "id": "s1",
    "text": "I feel hurt after the meeting was cancelled.",
    "start": 0,
    "end": 46,
    "kinds": ["feeling", "reported_event"],
    "lenses": ["hurt"],
    "speaker": "user",
}
HYPOTHESIS = {
    "id": "h1",
    "summary": "The cancellation may have felt like a loss of consideration.",
    "supporting_evidence_ids": ["evidence_s1"],
    "counter_evidence_ids": [],
    "lineage": [
        {
            "id": "l1",
            "proposition": "A meeting was reported as cancelled.",
            "layer": "event",
            "status": "user_report",
            "evidence_ids": ["evidence_s1"],
            "limits": "The reason for cancellation is unknown.",
        }
    ],
    "unsupported_assumptions": [],
    "what_would_strengthen": "The cancellation occurred without notice or explanation.",
    "what_would_weaken": "The meeting was moved with clear notice and agreement.",
    "relative_weight_percent": 60,
    "status": "tentative",
}
QUESTION = {
    "id": "q1",
    "text": (
        "Was the hurt stronger because of the lost time or the way the change "
        "was communicated?"
    ),
    "tested_hypothesis_ids": ["h1"],
    "reason": "The answer distinguishes practical loss from perceived lack of consideration.",
}


class FixtureRuntime:
    fixtures: dict[str, dict[str, Any]] = {
        "safety_decision": {
            "decision": "continue_reflection",
            "evidence_ids": [],
            "decision_summary": "No immediate safety concern is present in the fixture.",
        },
        "segment_statements": {"summary": "Hurt after a cancellation.", "statements": [STATEMENT]},
        "choose_path": {
            "decision": "hurt",
            "evidence_ids": ["evidence_s1"],
            "decision_summary": "The user explicitly describes hurt.",
        },
        "inspect_hurt": {
            "lens": "hurt",
            "observed_pattern": "A cancellation is associated with hurt.",
            "assumed_problem_or_gap": "Consideration or predictability may feel absent.",
            "supporting_evidence_ids": ["evidence_s1"],
            "counter_evidence_ids": [],
            "uncertainties": ["The reason and communication context are unknown."],
            "boundary_implications": [],
            "possible_next_lenses": [],
        },
        "choose_next": {
            "decision": "build_hypotheses",
            "evidence_ids": ["evidence_s1"],
            "decision_summary": "The available statement supports bounded synthesis.",
        },
        "build_hypotheses": {
            "status": "hypotheses_available",
            "hypotheses": [HYPOTHESIS],
            "unresolved_percent": 40,
        },
        "decide_inquiry": {
            "decision": "ask_question",
            "evidence_ids": ["evidence_s1"],
            "decision_summary": "One distinction could change the explanation.",
            "tested_hypothesis_ids": ["h1"],
            "missing_distinction": "Practical loss compared with communication meaning.",
        },
        "compose_response": {
            "status": "awaiting_answer",
            "summary": "The cancellation may have affected consideration or predictability.",
            "statements": [STATEMENT],
            "selected_focus_id": "s1",
            "hypotheses": [HYPOTHESIS],
            "unresolved_percent": 40,
            "understanding": "The reaction may be connected to how the change was experienced.",
            "boundary": "A request for timely communication remains reasonable.",
            "responsibility": "The reason for cancellation is still unknown.",
            "pending_question": QUESTION,
            "next_step": "Answer the question or end the reflection.",
        },
        "audit_response": {
            "decision": "accept",
            "evidence_ids": ["evidence_s1"],
            "decision_summary": "The response is bounded and evidence-linked.",
            "issues": [],
        },
    }

    async def ainvoke(
        self,
        node_id: str,
        prompt_ref: str,
        schema: type[BaseModel],
        state: AnalysisState,
    ) -> BaseModel:
        del prompt_ref, state
        return schema.model_validate(self.fixtures[node_id])


@pytest.mark.asyncio
async def test_yaml_graph_interrupts_and_resumes() -> None:
    config = load_graph_config()
    graph = compile_graph(
        config,
        NodeExecutor(config, FixtureRuntime()),
        checkpointer=InMemorySaver(),
    )
    run_config = {
        "configurable": {"thread_id": "runtime-test"},
        "recursion_limit": config.budgets.recursion_limit,
    }

    paused = await graph.ainvoke(
        {"user_text": STATEMENT["text"]},
        config=run_config,
        durability="sync",
    )

    assert paused["stage"] == "public_view_ready"
    assert paused["public_view"]["status"] == "awaiting_answer"
    assert paused["model_attempt_count"] == 9
    assert "__interrupt__" in paused

    completed = await graph.ainvoke(
        Command(resume={"action": "finish"}),
        config=run_config,
        durability="sync",
    )

    assert completed["stage"] == "complete"
    assert completed["pending_input"] is None
