import pytest
from pydantic import ValidationError

from causal.schemas import PublicReflection


def test_weighted_hypotheses_include_unresolved_mass() -> None:
    payload = {
        "status": "complete",
        "summary": "A bounded example.",
        "statements": [],
        "selected_focus_id": None,
        "hypotheses": [
            {
                "id": "h1",
                "summary": "A tentative explanation.",
                "supporting_evidence_ids": [],
                "counter_evidence_ids": [],
                "lineage": [],
                "unsupported_assumptions": [],
                "what_would_strengthen": None,
                "what_would_weaken": None,
                "relative_weight_percent": 60,
                "status": "tentative",
            }
        ],
        "unresolved_percent": 40,
        "understanding": None,
        "boundary": None,
        "responsibility": None,
        "pending_question": None,
        "next_step": None,
    }
    reflection = PublicReflection.model_validate(payload)
    assert reflection.unresolved_percent == 40


def test_invalid_weight_total_is_rejected() -> None:
    with pytest.raises(ValidationError):
        PublicReflection.model_validate(
            {
                "status": "complete",
                "summary": "Invalid total.",
                "statements": [],
                "selected_focus_id": None,
                "hypotheses": [
                    {
                        "id": "h1",
                        "summary": "A tentative explanation.",
                        "supporting_evidence_ids": [],
                        "counter_evidence_ids": [],
                        "lineage": [],
                        "unsupported_assumptions": [],
                        "what_would_strengthen": None,
                        "what_would_weaken": None,
                        "relative_weight_percent": 90,
                        "status": "tentative",
                    }
                ],
                "unresolved_percent": 20,
                "understanding": None,
                "boundary": None,
                "responsibility": None,
                "pending_question": None,
                "next_step": None,
            }
        )
