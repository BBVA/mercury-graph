import pytest

from mercury.graph.evidence import Formalizer


def test_formalizer():
	f = Formalizer(schema = 'any')
	assert type(f) is Formalizer

	f.run({'cmd': 'test'})
	f._dry_run({'cmd': 'test'})
	assert type(f.meta) == dict


# if __name__ == "__main__":
# 	pytest.main([__file__])
