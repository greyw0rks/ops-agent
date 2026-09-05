"""Audit recording.

`RunObserver` is a Strands hook provider that writes an `agent_actions` row for
every tool the agent actually executes. Blocked and escalated calls are recorded
by the policy gate instead, so this hook skips those to avoid double entries.

The result is that the dashboard's activity feed is generated from what happened,
not from the model's own account of what happened.
"""

import json
import logging

from strands.hooks import AfterToolCallEvent, HookProvider, HookRegistry

from app.db.enums import ActionStatus
from app.db.session import session_scope
from app.services import runs as run_service
from app.tools import _context as run_context

logger = logging.getLogger(__name__)

# The gate has already written a row for these outcomes.
GATE_HANDLED_PREFIXES = ("DENIED:", "CONFIRMATION_FAILED:", "GUIDANCE:")


class RunObserver(HookProvider):
    """Records each executed tool call against the current agent run."""

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(AfterToolCallEvent, self.on_after_tool_call)

    def on_after_tool_call(self, event: AfterToolCallEvent) -> None:
        ctx = run_context.current_or_none()
        if ctx is None:
            return

        tool_use = event.tool_use
        tool_name = tool_use.get("name", "")
        tool_use_id = tool_use.get("toolUseId", "")

        cancel_message = getattr(event, "cancel_message", None)
        if cancel_message and str(cancel_message).startswith(GATE_HANDLED_PREFIXES):
            return

        status, output = _summarise(event)
        latency_ms = int((getattr(event, "duration", 0) or 0) * 1000)

        try:
            with session_scope() as db:
                run_service.record_action(
                    db,
                    run_id=ctx.run_id,
                    tool=tool_name,
                    tool_input=tool_use.get("input") or {},
                    output=output,
                    status=status,
                    risk_level=_risk(tool_name),
                    policy_decision="allow",
                    tool_use_id=tool_use_id,
                    latency_ms=latency_ms,
                )
        except Exception:  # pragma: no cover - never let auditing break a run
            logger.exception("failed to record action tool=%s run=%s", tool_name, ctx.run_id)


def _risk(tool_name: str) -> str:
    from app.policy.risk import risk_of

    return risk_of(tool_name)


def _summarise(event: AfterToolCallEvent) -> tuple[str, dict]:
    """Reduce a tool result to a status and a JSON-safe payload."""
    result = event.result

    if isinstance(result, Exception):
        return ActionStatus.ERROR, {"error": f"{type(result).__name__}: {result}"}

    if isinstance(result, dict):
        status = ActionStatus.ERROR if result.get("status") == "error" else ActionStatus.SUCCESS
        content = result.get("content") or []
        extracted: dict = {}
        texts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if "json" in block and isinstance(block["json"], dict):
                extracted = block["json"]
            elif "text" in block:
                texts.append(str(block["text"]))
        if extracted:
            return status, extracted
        if texts:
            joined = "\n".join(texts)
            # Function tools return dicts, which Strands JSON-dumps into a text
            # block. Parse it back so the audit row keeps real structure.
            try:
                parsed = json.loads(joined)
            except (ValueError, TypeError):
                return status, {"text": joined[:2000]}
            return status, parsed if isinstance(parsed, dict) else {"result": parsed}
        return status, {}

    return ActionStatus.SUCCESS, {"result": str(result)[:2000]}
