import pytest

from mercury.graph.evidence import Agent


def test_agent():
	a = Agent(schema = 'any')
	assert type(a) is Agent
	assert Agent(extra_args = {'test': True}).conf == {'test': True}

	a.run({'cmd': 'test'})
	a._dry_run({'cmd': 'test'})
	assert type(a.meta) == dict


# if __name__ == "__main__":
# 	pytest.main([__file__])
