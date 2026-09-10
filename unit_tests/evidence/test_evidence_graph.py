from mercury.graph.evidence import EvidenceGraph

def test_evidence_graph():
	""" Verifies EvidenceGraph construction and configuration. """
	eg = EvidenceGraph(schema = 'any', extra_args = {'test': True})
	assert type(eg) is EvidenceGraph
	assert EvidenceGraph(schema = 'any', extra_args = {'test': True}).conf == {'test': True}


# if __name__ == "__main__":
# 	pytest.main([__file__])
