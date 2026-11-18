import pytest

from mercury.graph.evidence import Decider
from mercury.graph.evidence.decider import DeciderState, Question


class DummyDecider(Decider):
	""" Provide model-free implementations of the abstract request handlers. """

	def _run(self, request):
		""" Return the supplied request dictionary unchanged. """
		return request


	def _dry_run(self, request):
		""" Return the supplied request dictionary unchanged during validation. """
		return request


@pytest.mark.parametrize('question, function_name, required', [
	('EXTRACT_NODES', 'extract_nodes_test_schema', ['text', 'ontology']),
	('MATCH_NODE', 'match_node_test_schema', ['mention', 'node']),
	('EXTRACT_EDGES', 'extract_edges_test_schema', ['text', 'nodes', 'ontology'])
])
def test_question_capability(question, function_name, required):
	""" Valid question keys produce named tools with their documented required arguments. """
	capability = Question.capability(question, 'test_schema')

	assert capability['type'] == 'function'
	assert capability['function']['name'] == function_name
	assert capability['function']['parameters']['required'] == required


@pytest.mark.parametrize('question', [None, '', 'UNKNOWN', 'extract_nodes'])
def test_question_capability_invalid_key(question):
	""" Unsupported question keys do not expose a capability. """
	assert Question.capability(question, 'test_schema') is None


def test_question_capability_is_independent():
	""" Changes to nested capability data do not affect templates or subsequent calls. """
	capability = Question.capability('EXTRACT_NODES', 'first')
	capability['function']['parameters']['properties']['text']['type'] = 'object'
	capability['function']['parameters']['required'].append('context')

	fresh = Question.capability('EXTRACT_NODES', 'second')
	assert fresh['function']['name'] == 'extract_nodes_second'
	assert fresh['function']['parameters']['properties']['text']['type'] == 'string'
	assert fresh['function']['parameters']['required'] == ['text', 'ontology']
	assert Question.EXTRACT_NODES.value['function']['name'] == 'extract_nodes_%s'
	assert Question.EXTRACT_NODES.value['function']['parameters']['properties']['text']['type'] == 'string'
	assert Question.EXTRACT_NODES.value['function']['parameters']['required'] == ['text', 'ontology']


def test_decider_is_abstract():
	""" A Decider requires concrete run and dry-run implementations. """
	with pytest.raises(TypeError):
		Decider(schema = 'test_schema', extra_args = {})


def test_decider_initialization():
	""" A concrete decider stores its configuration and starts without capabilities. """
	conf = {'description': 'Test decider'}
	decider = DummyDecider(schema = 'test_schema', extra_args = conf)

	assert decider.name == 'test_schema'
	assert decider.conf is conf
	assert decider.question is None
	assert decider.states is DeciderState
	assert decider.id == 'decider_test_schema'
	assert decider.endpoint is decider
	assert decider.meta == {'state': DeciderState.INITIAL.value, 'description': 'Test decider', 'capabilities': []}

	request = {'name': 'test_schema', 'arguments': {}}
	assert decider.run(request) is request
	assert decider.dry_run(request) is request


def test_decider_endpoint_and_logger():
	""" Optional endpoint and logger arguments reach the Agentic constructor. """
	endpoint = DummyDecider(schema = 'root', extra_args = {})
	logger = []
	decider = DummyDecider(schema = 'test_schema', extra_args = {}, endpoint = endpoint, logger = logger)

	assert decider.id == 'decider_root/decider_test_schema'
	assert decider.endpoint is endpoint
	assert decider.logger is logger


def test_decider_without_schema():
	""" A missing schema permits class discovery without initializing decider configuration. """
	decider = DummyDecider(schema = None, extra_args = None)

	assert decider.id == 'decider'
	assert not hasattr(decider, 'conf')
	assert not hasattr(decider, 'question')


@pytest.mark.parametrize('conf, description', [
	({}, ''),
	({'description': 'Single line'}, 'Single line'),
	({'description': ['First line', 'Second line']}, 'First line\nSecond line'),
	({'description': []}, '')
])
def test_decider_metadata_description(conf, description):
	""" Metadata defaults missing descriptions and joins lists into multiline text. """
	decider = DummyDecider(schema = 'test_schema', extra_args = conf)

	assert decider.meta == {'state': DeciderState.INITIAL.value, 'description': description, 'capabilities': []}


@pytest.mark.parametrize('question', ['EXTRACT_NODES', 'MATCH_NODE', 'EXTRACT_EDGES'])
def test_decider_metadata_capability(question):
	""" Subclasses can publish their supported question by rebuilding metadata. """
	decider = DummyDecider(schema = 'test_schema', extra_args = {})
	decider.question = question
	decider._meta_ = decider._meta()

	assert decider.meta['capabilities'] == [Question.capability(question, 'test_schema')]
	assert decider.meta['state'] == DeciderState.INITIAL.value


# if __name__ == "__main__":
# 	pytest.main([__file__])
