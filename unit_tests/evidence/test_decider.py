import pytest

from mercury.graph.evidence import Decider

def dummy_test_decider():
    decider = Decider(schema="test_schema", extra_args={})
    assert decider.name == "test_schema"
    assert decider.conf == {}
    assert decider.question is None


# if __name__ == "__main__":
# 	pytest.main([__file__])
