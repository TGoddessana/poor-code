import asyncio
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import BaseModel

from poor_code.extensions import (
    AgentNode, NodeContext, NodeResult, StructuredCompletion, NodeRegistry,
    SessionState, register_artifact,
)
from poor_code.domain.session.models import Request, RequestKind
from poor_code.domain.session.store import _session_state_to_dict, _dict_to_session_state
from poor_code.domain.harness.contracts import contract_warnings
from poor_code.provider.events import (
    ToolCallStarted, ToolCallInputDelta, ToolCallEnded, FinishedReason,
)


# --- a user's custom artifact (NO core file edited) ---
@dataclass(frozen=True)
class SuiteArtifact:
    cases: tuple[str, ...] = ()

    def to_json_dict(self) -> dict:
        return {"cases": list(self.cases)}

    @classmethod
    def from_json_dict(cls, d: dict) -> "SuiteArtifact":
        return cls(cases=tuple(d.get("cases", [])))

    def apply_to(self, s: SessionState) -> SessionState:
        return s.put(self)


register_artifact("dogfood_test_suite", SuiteArtifact)


class _SuiteOut(BaseModel):
    cases: list[str]


# --- a user's custom node ---
class SuiteWriter(AgentNode):
    name = "suite_writer"
    requires = (Request,)
    produces = (SuiteArtifact,)

    def build_messages(self, state):
        req = state.require(Request)
        return [{"role": "system", "content": "write tests"},
                {"role": "user", "content": req.raw_text}]

    def output_tool(self):
        return {"type": "function",
                "function": {"name": "emit_suite", "parameters": _SuiteOut.model_json_schema()}}

    def _completion(self):
        return StructuredCompletion(
            tool=self.output_tool(), model=_SuiteOut,
            parse=lambda raw: SuiteArtifact(cases=tuple(_SuiteOut.model_validate_json(raw).cases)))

    async def run(self, ctx):
        return await self._terminal(ctx, self._completion())


class _SuiteLLM:
    async def stream(self, messages, tools, response_format=None):
        yield ToolCallStarted(call_id="c", name=tools[0]["function"]["name"])
        yield ToolCallInputDelta(call_id="c", json_delta='{"cases": ["t_add", "t_sub"]}')
        yield ToolCallEnded(call_id="c")
        yield FinishedReason(reason="tool_calls")


@pytest.mark.asyncio
async def test_custom_node_produces_artifact_and_applies_to_state():
    node = SuiteWriter(_SuiteLLM())
    st = SessionState().with_request(Request(raw_text="add+sub", kind=RequestKind.ENGINEERING))
    ctx = NodeContext(state=st, cancel=asyncio.Event())
    res = await node.run(ctx)
    assert isinstance(res, NodeResult)
    suite = res.output
    assert isinstance(suite, SuiteArtifact)
    assert suite.cases == ("t_add", "t_sub")
    st2 = suite.apply_to(st)
    assert st2.require(SuiteArtifact) == suite


def test_custom_artifact_survives_json_roundtrip():
    st = SessionState().put(SuiteArtifact(cases=("a", "b")))
    out = _session_state_to_dict(st)
    assert out["extensions"] == {"dogfood_test_suite": {"cases": ["a", "b"]}}
    back = _dict_to_session_state(out, Path("dummy"))
    assert back.require(SuiteArtifact) == SuiteArtifact(cases=("a", "b"))


def test_custom_node_passes_contract_check_when_producer_present():
    class _ReqProducer:
        name = "seed"
        requires = ()
        produces = (Request,)
    reg = NodeRegistry()
    reg.register(_ReqProducer())
    reg.register(SuiteWriter(_SuiteLLM()))
    assert contract_warnings(reg) == []


def test_custom_node_flagged_when_producer_absent():
    reg = NodeRegistry()
    reg.register(SuiteWriter(_SuiteLLM()))
    warnings = contract_warnings(reg)
    assert any("suite_writer" in w and "Request" in w for w in warnings)
