import pytest

from mercury.graph.evidence import Source


def test_source():
	s = Source(schema = 'any')
	assert type(s) is Source
	assert Source(extra_args = {'test': True}).conf == {'test': True}

	s.run({'cmd': 'test'})
	s._dry_run({'cmd': 'test'})
	assert type(s.meta) == dict


# if __name__ == "__main__":
# 	pytest.main([__file__])
