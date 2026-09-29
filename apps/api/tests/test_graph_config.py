from causal.graph.loader import load_graph_config


def test_graph_configuration_is_structurally_valid() -> None:
    graph = load_graph_config()
    assert graph.graph_id == "causal_reflection"
    assert graph.entrypoint == "ingest_turn"
    assert "complete" in graph.terminal_nodes
    assert len(graph.nodes) >= 20
