import pytest

from mercury.graph.evidence.deciders import XNodesGl2Decider, XEdgesGl2Decider, MatchNodeJevDecider, MatchNodeLayaDecider


def dummy_test_xnodesgl2decider():
    decider = XNodesGl2Decider(schema="test_schema", extra_args={})
    assert decider.name == "test_schema"
    assert decider.conf == {}
    assert decider.question is None


def dummy_test_xedgesgl2decider():
    decider = XEdgesGl2Decider(schema="test_schema", extra_args={})
    assert decider.name == "test_schema"
    assert decider.conf == {}
    assert decider.question is None


def dummy_test_matchnodejevdecider():
    decider = MatchNodeJevDecider(schema="test_schema", extra_args={})
    assert decider.name == "test_schema"
    assert decider.conf == {}
    assert decider.question is None


def dummy_test_matchnodelayadecider():
    decider = MatchNodeLayaDecider(schema="test_schema", extra_args={})
    assert decider.name == "test_schema"
    assert decider.conf == {}
    assert decider.question is None

# if __name__ == "__main__":
# 	pytest.main([__file__])
