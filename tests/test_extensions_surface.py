def test_extensions_facade_exports_core_primitives():
    from poor_code.extensions import (
        AgentNode, NodeContext, NodeResult, Node, Completion, StructuredCompletion,
        Graph, EdgeTable, CompiledGraph, NodeRegistry,
        SessionState, MissingInput, register_artifact, artifact_name, artifact_class,
    )
    from poor_code.domain.harness.node import AgentNode as _AN
    from poor_code.domain.session.models import MissingInput as _MI
    assert AgentNode is _AN
    assert MissingInput is _MI


def test_harness_all_includes_extension_primitives():
    import poor_code.domain.harness as h
    for name in ("AgentNode", "Completion", "StructuredCompletion", "CompiledGraph"):
        assert name in h.__all__
        assert hasattr(h, name)


def test_session_all_includes_artifact_and_missing_input():
    import poor_code.domain.session as s
    for name in ("MissingInput", "register_artifact", "artifact_name", "artifact_class"):
        assert name in s.__all__
        assert hasattr(s, name)
