"""LangGraph implementation mirroring the custom orchestrator nodes."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from itertools import pairwise
from pathlib import Path
from typing import Any, TypedDict, cast

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph

from adda.orchestrator.custom import checkpoint_slug
from adda.orchestrator.runtime import (
    PIPELINE_STEPS,
    OrchestratorError,
    execute_tool_step,
    run_plan_step,
)
from adda.orchestrator.state import AgentState
from adda.orchestrator.tools import Tool


class GraphState(TypedDict):
    """LangGraph state wrapper around serialized AgentState."""

    state: dict[str, Any]


class LangGraphOrchestrator:
    """LangGraph version of the same deterministic Phase 6 pipeline."""

    def __init__(
        self,
        tools: Sequence[Tool],
        checkpoint_path: str | Path,
        *,
        max_attempts: int = 3,
        wait_multiplier: float = 0.01,
        iteration_cap: int = 32,
    ) -> None:
        self.tools = {tool.name: tool for tool in tools}
        self.checkpoint_path = Path(checkpoint_path)
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_attempts = max_attempts
        self.wait_multiplier = wait_multiplier
        self.iteration_cap = iteration_cap
        self.connection = sqlite3.connect(
            self.checkpoint_path,
            check_same_thread=False,
        )
        self.checkpointer = SqliteSaver(self.connection)
        self.graph = self._compile_graph()

    def run(self, disease: str) -> AgentState:
        """Run the LangGraph pipeline and return an AgentState."""

        initial: GraphState = {
            "state": AgentState(
                disease_query=disease,
                checkpoint_id=checkpoint_slug(disease),
            ).model_dump(mode="json")
        }
        config = {
            "configurable": {"thread_id": checkpoint_slug(disease)},
            "recursion_limit": self.iteration_cap,
        }
        try:
            result = cast(GraphState, self.graph.invoke(initial, config=config))
        except GraphRecursionError as exc:
            raise OrchestratorError("iteration cap exceeded") from exc
        return AgentState.model_validate(result["state"])

    def close(self) -> None:
        """Close the SQLite checkpointer connection."""

        self.connection.close()

    def _compile_graph(self) -> Any:
        graph: StateGraph[GraphState] = StateGraph(GraphState)
        for step_name in PIPELINE_STEPS:
            graph.add_node(step_name, self._node(step_name))
        graph.add_edge(START, "plan")
        for left, right in pairwise(PIPELINE_STEPS):
            graph.add_edge(left, right)
        graph.add_edge(PIPELINE_STEPS[-1], END)
        return graph.compile(checkpointer=self.checkpointer)

    def _node(self, step_name: str) -> Any:
        def run_node(raw_state: GraphState) -> GraphState:
            state = AgentState.model_validate(raw_state["state"])
            if state.iteration_count >= self.iteration_cap:
                raise OrchestratorError("iteration cap exceeded")
            if step_name in state.completed_steps:
                return {"state": state.model_dump(mode="json")}
            if step_name == "plan":
                updated = run_plan_step(state)
                return {"state": updated.model_dump(mode="json")}
            tool = self.tools.get(step_name)
            if tool is None:
                state.errors.append(
                    {
                        "step": step_name,
                        "error": "missing tool",
                        "type": "MissingTool",
                        "recoverable": True,
                    }
                )
                state.mark_completed(step_name)
                return {"state": state.model_dump(mode="json")}
            updated = execute_tool_step(
                state,
                tool,
                max_attempts=self.max_attempts,
                wait_multiplier=self.wait_multiplier,
            )
            return {"state": updated.model_dump(mode="json")}

        return cast(Any, run_node)
