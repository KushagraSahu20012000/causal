import pytest
from fastapi.testclient import TestClient

import main
from main import app


def test_health() -> None:
    response = TestClient(app).get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "causal-api",
        "graph_version": "0.1.0",
    }


class PublicGraphFixture:
    async def ainvoke(self, graph_input: object, **kwargs: object) -> dict[str, object]:
        del graph_input, kwargs
        return {
            "stage": "public_view_ready",
            "public_view": {
                "status": "complete",
                "summary": "Several different experiences may be compressed into one claim.",
                "statements": [],
                "selected_focus_id": None,
                "hypotheses": [],
                "unresolved_percent": None,
                "understanding": "The generalization needs more specific context.",
                "boundary": None,
                "responsibility": "Avoid treating either gender as a single group.",
                "pending_question": None,
                "next_step": None,
            },
        }


def development_graph_fixture() -> PublicGraphFixture:
    return PublicGraphFixture()


def test_start_development_reflection_returns_only_public_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "_development_graph", development_graph_fixture)

    response = TestClient(app).post(
        "/api/v1/dev/reflections",
        json={"text": "Why do some men feel lonely today?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["stage"] == "public_view_ready"
    assert payload["public_view"]["status"] == "complete"
    assert payload["awaiting_input"] is False
    assert set(payload) == {"thread_id", "stage", "public_view", "awaiting_input"}
