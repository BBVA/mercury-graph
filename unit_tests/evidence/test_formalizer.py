import pytest

from mercury.graph.evidence import Formalizer
from mercury.graph.evidence.agentic import AgenticRunInvalidState


def test_formalizer():
	f = Formalizer(schema = 'any', extra_args = {'test': True})
	assert type(f) is Formalizer
	assert Formalizer(schema = 'any', extra_args = {'test': True}).conf == {'test': True}

	with pytest.raises(AgenticRunInvalidState):
		f.run({'cmd': 'test'})

	f._dry_run({'cmd': 'test'})
	assert type(f.meta) == dict


# if __name__ == "__main__":
# 	pytest.main([__file__])
