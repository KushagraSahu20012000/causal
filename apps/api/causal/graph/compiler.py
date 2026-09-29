"""Compile the validated YAML topology into an executable LangGraph."""

from collections import defaultdict
from collections.abc import Callable
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from causal.graph.handlers import NodeExecutor
from causal.graph.loader import EdgeConfig, GraphConfig
from causal.graph.state import AnalysisState


def _node_callable(
    executor: NodeExecutor,
    node_id: str,
    config: GraphConfig,
) -> Callable[[AnalysisState], Any]:
    node = next(item for item in config.nodes if item.id == node_id)

    async def execute(state: AnalysisState) -> AnalysisState:
        return await executor.execute(node, state)

    execute.__name__ = node_id
    return execute


def _route(state: AnalysisState) -> str:
    route = state.get("route")
    if not route:
        raise ValueError("conditional node did not produce a route")
    return route


def compile_graph(
    config: GraphConfig,
    executor: NodeExecutor,
    *,
    checkpointer: Any | None = None,
) -> Any:
    """Build a graph exclusively from validated configuration and allowlisted handlers."""
    builder = StateGraph(AnalysisState)
    for node in config.nodes:
        builder.add_node(node.id, cast(Any, _node_callable(executor, node.id, config)))

    builder.add_edge(START, config.entrypoint)
    outgoing: dict[str, list[EdgeConfig]] = defaultdict(list)
    for edge in config.edges:
        outgoing[edge.source].append(edge)

    for source, edges in outgoing.items():
        if len(edges) == 1 and edges[0].outcome is None:
            builder.add_edge(source, edges[0].target)
            continue
        path_map = {edge.outcome: edge.target for edge in edges if edge.outcome is not None}
        builder.add_conditional_edges(source, _route, cast(Any, path_map))

    for terminal in config.terminal_nodes:
        builder.add_edge(terminal, END)

    return builder.compile(checkpointer=checkpointer)
