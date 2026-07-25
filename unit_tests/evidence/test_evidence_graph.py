import pytest

from mercury.graph.evidence import EvidenceGraph
from mercury.graph.evidence.agentic import AgenticRunInvalidState

def test_evidence_graph():
	eg = EvidenceGraph(schema = 'any', extra_args = {'test': True})
	assert type(eg) is EvidenceGraph
	assert EvidenceGraph(schema = 'any', extra_args = {'test': True}).conf == {'test': True}

	with pytest.raises(AgenticRunInvalidState):
		eg.run({'cmd': 'test'})

	eg._dry_run({'cmd': 'test'})
	assert type(eg.meta) == dict


# if __name__ == "__main__":
# 	pytest.main([__file__])
