import pytest

from mercury.graph.evidence import Source


def test_source():
	s = Source(schema = 'any', extra_args = {'test': True})
	assert type(s) is Source
	assert Source(schema = 'any', extra_args = {'test': True}).conf == {'test': True}
	assert s.state_name(0) == 'INITIAL'

	s.run({'cmd': 'test'})
	s._dry_run({'cmd': 'test'})
	assert type(s.meta) == dict

	s.pilot(0)
	s._meta_['state'] = -1
	s.pilot(0)


# if __name__ == "__main__":
# 	pytest.main([__file__])
