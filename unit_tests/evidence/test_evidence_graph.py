import pytest

from mercury.graph.evidence import EvidenceGraph


def test_evidence_graph():
	eg = EvidenceGraph(schema = 'any')
	assert type(eg) is EvidenceGraph
	assert EvidenceGraph(extra_args = {'test': True}).conf == {'test': True}

	eg.run({'cmd': 'test'})
	eg._dry_run({'cmd': 'test'})
	assert type(eg.meta) == dict


# if __name__ == "__main__":
# 	pytest.main([__file__])
