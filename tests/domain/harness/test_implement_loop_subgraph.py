from poor_code.domain.harness.subgraphs.implement_loop import build_implement_loop
from poor_code.domain.session.models import Layer, Phase


def test_implement_loop_inner_topology():
    cg = build_implement_loop(llm=None, cwd=".")
    inner = cg._graph
    fwd = inner.edges.forward
    assert inner.entry == "task_selector"
    assert fwd[("task_selector", "task")] == "composer"
    assert ("task_selector", "done") not in fwd       # done exits the subgraph (forward miss)
    assert fwd[("composer", None)] == "implementer"
    assert fwd[("implementer", None)] == "eng_gate"
    assert fwd[("eng_gate", None)] == "validator"
    assert fwd[("validator", None)] == "validation_runner"
    assert fwd[("validation_runner", "pass")] == "completion_gate"
    assert fwd[("validation_runner", "fail")] == "failure_analyst"
    assert fwd[("failure_analyst", None)] == "completion_gate"
    assert fwd[("completion_gate", "done")] == "task_selector"
    # IMPLEMENTATION repairs handled inside; other layers bubble out (not present)
    assert inner.edges.back_edges == {Layer.IMPLEMENTATION: "implementer"}
    # the loop node is a Node with the IMPLEMENTING phase
    assert cg.name == "implement_loop"
    assert cg.phase is Phase.IMPLEMENTING


def test_implement_loop_registers_all_inner_nodes():
    cg = build_implement_loop(llm=None, cwd=".")
    for n in ("task_selector", "composer", "implementer", "eng_gate", "validator",
              "validation_runner", "failure_analyst", "completion_gate"):
        assert cg._graph.nodes.get(n) is not None
