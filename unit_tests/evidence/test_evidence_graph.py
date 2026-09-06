import pytest

from mercury.graph.evidence import EvidenceGraph
from mercury.graph.evidence.agentic import AgenticRunInvalidState

def test_evidence_graph():
	""" Verifies EvidenceGraph metadata, unavailable execution, and crawl behavior. """
	eg = EvidenceGraph(schema = 'any', extra_args = {'test': True})
	assert type(eg) is EvidenceGraph
	assert EvidenceGraph(schema = 'any', extra_args = {'test': True}).conf == {'test': True}

	with pytest.raises(AgenticRunInvalidState):
		eg.run({'cmd': 'test'})

	eg._dry_run({'cmd': 'test'})
	assert type(eg.meta) == dict


def test_evidence_graph_joins_description_and_rejects_crawling():
	""" Verifies multiline descriptions and the explicitly unavailable crawl operation. """
	eg = EvidenceGraph(schema = 'any', extra_args = {'description': ['First line.', 'Second line.']})

	assert eg.meta['description'] == 'First line.\nSecond line.'
	with pytest.raises(NotImplementedError):
		eg.crawl('source|section')


# if __name__ == "__main__":
# 	pytest.main([__file__])
