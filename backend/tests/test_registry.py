"""The registry and the risk table must agree.

A tool registered without an explicit risk entry falls through to the default-deny
path, which means the agent silently loses a capability. That is exactly the drift
this test exists to catch.
"""

from app.agent.registry import ALL_TOOLS, TOOL_GROUPS, tool_names
from app.policy.risk import TOOL_RISK, risk_of


def test_every_registered_tool_has_a_declared_risk():
    missing = sorted(set(tool_names()) - set(TOOL_RISK))
    assert not missing, f"tools registered without a risk entry: {missing}"


def test_no_stale_risk_entries():
    stale = sorted(set(TOOL_RISK) - set(tool_names()))
    assert not stale, f"risk entries for tools that no longer exist: {stale}"


def test_unknown_tools_are_treated_as_high_risk():
    assert risk_of("delete_everything") == "HIGH"


def test_no_duplicate_tool_names():
    names = tool_names()
    assert len(names) == len(set(names))


def test_groups_cover_every_tool():
    grouped = {t.tool_name for group in TOOL_GROUPS.values() for t in group}
    assert grouped == set(tool_names())


def test_every_tool_documents_itself():
    """The docstring is the model's only instruction manual for a tool."""
    for tool in ALL_TOOLS:
        spec = tool.tool_spec
        description = spec.get("description") or ""
        assert len(description) > 60, f"{tool.tool_name} needs a fuller description"
