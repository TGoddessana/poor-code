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
    # eng_gate removed: its only live effect was a git-diff "Attempt has no patch" floor
    # that false-abandoned git-invisible work (chmod/out-of-tree). The implementer now
    # flows straight to the observation-grounded Verifier, which judges from real disk
    # behaviour rather than the reconstructed patch.
    assert fwd[("implementer", None)] == "verifier"
    assert fwd[("verifier", "done")] == "task_selector"
    # eng_gate is no longer wired in the live loop
    assert ("eng_gate", None) not in fwd
    assert ("implementer", None) != "eng_gate"
    # the old chain nodes are no longer wired in the loop
    assert ("validator", None) not in fwd
    assert ("validation_runner", "pass") not in fwd
    assert ("completion_gate", "done") not in fwd
    # IMPLEMENTATION repairs handled inside; other layers bubble out (not present)
    assert inner.edges.back_edges == {Layer.IMPLEMENTATION: "implementer"}
    # the loop node is a Node with the IMPLEMENTING phase
    assert cg.name == "implement_loop"
    assert cg.phase is Phase.IMPLEMENTING


def test_implement_loop_registers_all_inner_nodes():
    cg = build_implement_loop(llm=None, cwd=".")
    for n in ("task_selector", "composer", "implementer", "verifier"):
        assert cg._graph.nodes.get(n) is not None
    # eng_gate is removed from the live loop (no longer registered)
    assert cg._graph.nodes.get("eng_gate") is None


def test_implementer_has_read_and_search_tools():
    from poor_code.domain.harness.subgraphs.implement_loop import _implementer_tools
    names = {s["function"]["name"] for s in _implementer_tools().schemas()}
    assert {"read", "grep", "glob", "list", "write", "edit", "bash"} <= names
