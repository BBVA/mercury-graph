import pytest

from mercury.graph.evidence import AgenticGraph
from mercury.graph.evidence.agentic import AgenticRunInvalidState


def test_agentic_graph():
	ag = AgenticGraph(schema = 'any', extra_args = {'test': True})
	assert type(ag) is AgenticGraph
	assert AgenticGraph(schema = 'any', extra_args = {'test': True}).conf == {'test': True}

	with pytest.raises(AgenticRunInvalidState):
		ag.run({'cmd': 'test'})

	ag._dry_run({'cmd': 'test'})
	assert type(ag.meta) == dict


# if __name__ == "__main__":
# 	pytest.main([__file__])
