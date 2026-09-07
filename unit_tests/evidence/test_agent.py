import pytest

from mercury.graph.evidence import Agent
from mercury.graph.evidence.agentic import AgenticRunInvalidState


def test_agent():
	a = Agent(schema = 'any', extra_args = {})
	assert type(a) is Agent
	assert Agent(schema = '',extra_args = {'test': True}).conf == {'test': True}

	assert a.meta['state'] == a.states.INITIAL.value

	with pytest.raises(AgenticRunInvalidState):
		a.run({'cmd': 'test'})

	assert a.dry_run({'cmd': 'test'}) == {'status': 0, 'description': 'Valid request.'}
	assert type(a.meta) == dict

	a = Agent(schema = 'any', extra_args = {
		'description': 'Test agent.',
		'upstream': {'name': 'test_agent', 'description': 'Test the agent.'},
		'completion': {'model': 'test/model'}
	})
	a.pilot(a.states.READY.value)

	assert a.meta['state'] == a.states.READY.value
	assert a.meta['description'] == 'Test agent.'
	assert a.meta['capabilities'][0]['function']['name'] == 'test_agent'


# if __name__ == "__main__":
# 	pytest.main([__file__])
