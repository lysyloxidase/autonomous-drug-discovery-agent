"""Shared runtime helpers for custom and LangGraph orchestrators."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from adda.orchestrator.state import AgentState
from adda.orchestrator.tools import Tool

PIPELINE_STEPS: tuple[str, ...] = (
    "plan",
    "retrieve",
    "extract",
    "build_kg",
    "score_evidence",
    "rank_targets",
    "triage_molecules",
    "write_report",
    "verify_citations",
)

TOOL_STEPS: tuple[str, ...] = PIPELINE_STEPS[1:]


class TransientToolError(RuntimeError):
    """A retryable tool failure."""


class OrchestratorError(RuntimeError):
    """A non-recoverable orchestrator failure."""


def utc_now_iso() -> str:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC).isoformat()


def append_log(
    state: AgentState,
    *,
    step_name: str,
    status: str,
    started_at: str,
    elapsed_ms: float,
    attempts: int,
    error: str | None = None,
) -> None:
    """Append per-step execution accounting."""

    entry: dict[str, Any] = {
        "step": step_name,
        "status": status,
        "started_at": started_at,
        "ended_at": utc_now_iso(),
        "elapsed_ms": round(elapsed_ms, 3),
        "attempts": attempts,
        "tokens": 0,
    }
    if error is not None:
        entry["error"] = error
    state.step_log.append(entry)


def run_plan_step(state: AgentState) -> AgentState:
    """Record the deterministic plan node."""

    started_at = utc_now_iso()
    start = time.perf_counter()
    state.iteration_count += 1
    state.mark_completed("plan")
    append_log(
        state,
        step_name="plan",
        status="success",
        started_at=started_at,
        elapsed_ms=(time.perf_counter() - start) * 1000,
        attempts=1,
    )
    return state


def execute_tool_step(
    state: AgentState,
    tool: Tool,
    *,
    max_attempts: int = 3,
    wait_multiplier: float = 0.01,
) -> AgentState:
    """Run one tool with retry, logging, and optional degraded continuation."""

    started_at = utc_now_iso()
    start = time.perf_counter()
    attempts = 0
    try:
        retrying = Retrying(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=wait_multiplier, min=0, max=1),
            retry=retry_if_exception_type(TransientToolError),
            reraise=True,
        )
        updated = state
        for attempt in retrying:
            attempts = attempt.retry_state.attempt_number
            with attempt:
                updated = tool.run(updated)
        updated.iteration_count += 1
        updated.mark_completed(tool.name)
        append_log(
            updated,
            step_name=tool.name,
            status="success",
            started_at=started_at,
            elapsed_ms=(time.perf_counter() - start) * 1000,
            attempts=attempts,
        )
        return updated
    except Exception as exc:
        state.iteration_count += 1
        error = {
            "step": tool.name,
            "error": str(exc),
            "type": type(exc).__name__,
            "recoverable": tool.continue_on_error,
            "timestamp": utc_now_iso(),
        }
        state.errors.append(error)
        status = "degraded" if tool.continue_on_error else "failed"
        if tool.continue_on_error:
            state.mark_completed(tool.name)
        append_log(
            state,
            step_name=tool.name,
            status=status,
            started_at=started_at,
            elapsed_ms=(time.perf_counter() - start) * 1000,
            attempts=max(attempts, 1),
            error=str(exc),
        )
        if tool.continue_on_error:
            return state
        raise OrchestratorError(f"step failed: {tool.name}") from exc
