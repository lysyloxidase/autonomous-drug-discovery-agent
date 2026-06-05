"""Custom deterministic-DAG state machine for the ADDa pipeline."""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from adda.orchestrator.runtime import (
    PIPELINE_STEPS,
    OrchestratorError,
    execute_tool_step,
    run_plan_step,
)
from adda.orchestrator.state import AgentState
from adda.orchestrator.tools import Tool


def checkpoint_slug(disease: str) -> str:
    """Create a stable filesystem-safe checkpoint ID."""

    slug = re.sub(r"[^a-zA-Z0-9]+", "-", disease.strip().lower()).strip("-")
    return slug or "adda-run"


class CustomOrchestrator:
    """Checkpointed, retrying deterministic-DAG orchestrator."""

    def __init__(
        self,
        tools: Sequence[Tool],
        checkpoint_dir: str | Path,
        *,
        max_attempts: int = 3,
        wait_multiplier: float = 0.01,
    ) -> None:
        self.tools = {tool.name: tool for tool in tools}
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.max_attempts = max_attempts
        self.wait_multiplier = wait_multiplier
        self.last_checkpoint_id: str | None = None

    def run(self, disease: str) -> AgentState:
        """Run the full pipeline and return final state."""

        state = AgentState(
            disease_query=disease,
            checkpoint_id=checkpoint_slug(disease),
        )
        self.last_checkpoint_id = state.checkpoint_id
        return self._run_remaining(state)

    def stream(self, disease: str) -> Iterator[dict[str, Any]]:
        """Yield progress events while running the pipeline."""

        state = AgentState(
            disease_query=disease,
            checkpoint_id=checkpoint_slug(disease),
        )
        self.last_checkpoint_id = state.checkpoint_id
        for step_name in PIPELINE_STEPS:
            if step_name in state.completed_steps:
                continue
            yield {"event": "step_started", "step": step_name}
            try:
                state = self._run_one_step(state, step_name)
                status = state.step_log[-1]["status"] if state.step_log else "success"
                yield {
                    "event": "step_finished",
                    "step": step_name,
                    "status": status,
                    "state": state.model_dump(mode="json"),
                }
            except OrchestratorError as exc:
                yield {
                    "event": "step_failed",
                    "step": step_name,
                    "error": str(exc),
                    "state": state.model_dump(mode="json"),
                }
                raise
        yield {
            "event": "complete",
            "state": state.model_dump(mode="json"),
        }

    def resume(self, checkpoint_id: str) -> AgentState:
        """Resume from the last good checkpoint."""

        state = self._load_checkpoint(checkpoint_id)
        self.last_checkpoint_id = state.checkpoint_id or checkpoint_id
        return self._run_remaining(state)

    def _run_remaining(self, state: AgentState) -> AgentState:
        for step_name in PIPELINE_STEPS:
            if step_name in state.completed_steps:
                continue
            state = self._run_one_step(state, step_name)
        return state

    def _run_one_step(self, state: AgentState, step_name: str) -> AgentState:
        if step_name == "plan":
            state = run_plan_step(state)
            self._save_checkpoint(state)
            return state
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
            self._save_checkpoint(state)
            return state
        try:
            state = execute_tool_step(
                state,
                tool,
                max_attempts=self.max_attempts,
                wait_multiplier=self.wait_multiplier,
            )
        finally:
            self._save_checkpoint(state)
        return state

    def _checkpoint_path(self, checkpoint_id: str) -> Path:
        return self.checkpoint_dir / f"{checkpoint_id}.json"

    def _save_checkpoint(self, state: AgentState) -> None:
        checkpoint_id = state.checkpoint_id or checkpoint_slug(state.disease_query)
        state.checkpoint_id = checkpoint_id
        self.last_checkpoint_id = checkpoint_id
        self._checkpoint_path(checkpoint_id).write_text(
            state.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def _load_checkpoint(self, checkpoint_id: str) -> AgentState:
        path = self._checkpoint_path(checkpoint_id)
        if not path.exists():
            raise FileNotFoundError(f"checkpoint not found: {checkpoint_id}")
        return AgentState.model_validate_json(path.read_text(encoding="utf-8"))
