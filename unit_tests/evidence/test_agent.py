import pytest

from mercury.graph.evidence import Agent
from mercury.graph.evidence.agentic import AgenticRunInvalidState


def test_agent():
	a = Agent(schema = 'any')
	assert type(a) is Agent
	assert Agent(extra_args = {'test': True}).conf == {'test': True}

	assert a.meta['state'] < 0

	with pytest.raises(AgenticRunInvalidState):
		a.run({'cmd': 'test'})

	a._dry_run({'cmd': 'test'})
	assert type(a.meta) == dict

	a = Agent(schema = 'any', extra_args = {'api_base': '', 'capabilities': ['cap1', 'cap2'], 'model_name': ''})

	assert a.meta['state'] > 0


# if __name__ == "__main__":
# 	pytest.main([__file__])
