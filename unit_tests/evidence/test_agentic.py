import pytest

from mercury.graph.evidence import Agentic


class DummyAgentic(Agentic):
	""" Test implementation of the Agentic abstract interface. """

	def __init__(self, my_class = 'dummy', schema = None, endpoint = None, logger = None):
		""" Initializes a test double with counters for delegated calls. """
		self.run_count = 0
		self.meta_count = 0
		self.dry_run_count = 0

		super().__init__(my_class = my_class, schema = schema, endpoint = endpoint, logger = logger)


	def _run(self, request):
		""" Records and returns a run request. """
		self.run_count += 1

		return {'request': request, 'run_count': self.run_count}


	def _meta(self):
		""" Records and returns metadata. """
		self.meta_count += 1

		return {'meta_count': self.meta_count}


	def _dry_run(self, request):
		""" Records and returns a dry-run request. """
		self.dry_run_count += 1

		return {'request': request, 'dry_run_count': self.dry_run_count}


def test_agentic_is_abstract():
	""" Verifies that Agentic cannot be instantiated directly. """
	with pytest.raises(TypeError):
		Agentic('agentic')


def test_abstract_method_bodies_return_none():
	""" Verifies the base abstract method bodies are no-ops. """
	dummy = DummyAgentic()

	assert Agentic._run(dummy, {'query': 'run'}) is None
	assert Agentic._meta(dummy) is None
	assert Agentic._dry_run(dummy, {'query': 'dry_run'}) is None


def test_child_is_registered_with_endpoint():
	""" Verifies IDs, endpoints, and child registration across a small tree. """
	endpoint = DummyAgentic(my_class = 'endpoint', schema = 'main')
	child = DummyAgentic(my_class = 'child', schema = 'schema', endpoint = endpoint)
	grandchild = DummyAgentic(my_class = 'leaf', endpoint = child)

	assert endpoint.id == 'endpoint_main'
	assert endpoint.endpoint is endpoint
	assert child.id == 'endpoint_main/child_schema'
	assert child.endpoint is endpoint
	assert grandchild.id == 'endpoint_main/child_schema/leaf'
	assert grandchild.endpoint is child

	child.add_tool(grandchild)

	assert grandchild.id in child.tools


def test_meta_is_cached():
	""" Verifies metadata is computed once and then reused. """
	dummy = DummyAgentic()

	assert dummy.meta == {'meta_count': 1}
	assert dummy.meta == {'meta_count': 1}
	assert dummy.meta_count == 1


def test_pilot():
	""" Verifies the pilot method sets the state to "more than ready". """
	dummy = DummyAgentic()

	dummy.pilot(42)
	assert dummy.meta['state'] == 100

	dummy.close(False)


def test_run_and_log_error_write_events():
	""" Verifies request, response, and error logging fields. """
	logger = []
	dummy = DummyAgentic(schema = 'audit', logger = logger)
	request = {'query': 'value'}

	dummy.log_error('bad request')
	response = dummy.run(request)

	assert response == {'request': request, 'run_count': 1}
	assert dummy.seq_num == 2
	assert len(logger) == 3
	assert logger[0]['type'] == 'error'
	assert logger[0]['id'] == 'dummy_audit'
	assert logger[0]['seq_num'] == 0
	assert logger[0]['error'] == 'bad request'
	assert logger[1]['type'] == 'request'
	assert logger[1]['request'] is request
	assert logger[1]['seq_num'] == 1
	assert logger[2]['type'] == 'response'
	assert logger[2]['response'] == response
	assert logger[2]['seq_num'] == 1

	dummy.run({'query': 'again'})

	assert dummy.seq_num == 3
	assert logger[3]['seq_num'] == 2
	assert logger[4]['seq_num'] == 2


def test_dry_run_and_normalize_name():
	""" Verifies dry-run dispatch and name normalization. """
	dummy = DummyAgentic()

	assert dummy.dry_run({'query': 'value'}) == {'request': {'query': 'value'}, 'dry_run_count': 1}
	assert dummy._normalize_name(' Bad Name-1! ') == '_Bad_Name1_'


# if __name__ == "__main__":
# 	pytest.main([__file__])
