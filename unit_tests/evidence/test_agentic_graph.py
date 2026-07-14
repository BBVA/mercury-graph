import pytest

from mercury.graph.evidence import AgenticGraph


def test_agentic_graph():
	ag = AgenticGraph(schema = 'any')
	assert type(ag) is AgenticGraph
	assert AgenticGraph(extra_args = {'test': True}).conf == {'test': True}

	ag.run({'cmd': 'test'})
	ag._dry_run({'cmd': 'test'})
	assert type(ag.meta) == dict


# if __name__ == "__main__":
# 	pytest.main([__file__])
