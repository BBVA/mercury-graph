import pytest
from unittest.mock import Mock

from mercury.graph.evidence import Crawl


def _make_crawl(objects = None, children = None, domain_options = None, target_options = None):
	"""Build a crawl with in-memory capability responses.

	Args:
		objects (dict, optional): Objects keyed by node id; defaults to a single root object.
		children (dict, optional): Child id lists keyed by parent id; missing entries return None.
		domain_options (dict, optional): Boundary settings added to the domain configuration.
		target_options (dict, optional): Acceptance and serialization settings added to the target configuration.

	Returns:
		tuple: The crawl, domain mock, and target mock.
	"""
	if objects is None:
		objects = {'root': {'id': 'root'}}
	children = children or {}

	def run_domain(request):
		"""Return the object or child ids requested by a capability call dictionary."""
		index = request['arguments']['index']
		if request['name'] == 'children':
			message = children.get(index)
		else:
			assert request['name'] == 'get_object'
			message = objects[index]
		return {'finish_reason': 'stop', 'message': message}

	domain_agent = Mock()
	domain_agent._run.side_effect = run_domain
	target_agent = Mock()
	target_agent._run.return_value = {'finish_reason': 'stop'}
	domain = {'root_id': 'root', 'agentic': domain_agent, 'children': 'children', 'get_object': 'get_object'}
	target = {'agentic': target_agent, 'target': 'store'}
	if domain_options is not None:
		domain.update(domain_options)
	if target_options is not None:
		target.update(target_options)
	return Crawl(domain, target), domain_agent, target_agent


def test_101():
	"""Verify invalid construction and the initial crawl state."""
	with pytest.raises(TypeError):
		crawl = Crawl(None, None)

	crawl = Crawl({'root_id': '', 'agentic': None, 'children': None, 'get_object': None}, {'agentic': None, 'target': None})

	assert type(crawl) is Crawl
	assert crawl.finished is False
	assert crawl.nodes_done == 0
	assert crawl.nodes_pending == 1
	assert crawl.error is False


def test_crawl_traverses_breadth_first_and_resumes():
	"""Process each sibling once, resume after a step limit, and stop cleanly at exhaustion."""
	objects = {index: {'id': index} for index in ['root', 'left', 'right', 'leaf']}
	children = {'root': ['left', 'right', 'left'], 'left': ['leaf'], 'right': []}
	crawl, domain, target = _make_crawl(objects, children)

	assert crawl.run(num_steps = 1) is False
	assert crawl.nodes_done == 1
	assert crawl.nodes_pending == 2
	assert crawl.finished is False
	assert crawl.error is False
	assert crawl.run() is True

	visited = [call.args[0]['arguments']['index'] for call in domain._run.call_args_list if call.args[0]['name'] == 'get_object']
	assert visited[0] == 'root'
	assert set(visited[1:3]) == {'left', 'right'}
	assert visited[3:] == ['leaf']
	assert [call.args[0] for call in target._run.call_args_list] == [
		{'name': 'store', 'arguments': objects[index]} for index in visited
	]
	assert crawl.nodes_done == 4
	assert crawl.nodes_pending == 0
	assert crawl.finished is True
	assert crawl.error is False
	assert crawl._run_step() is False
	assert crawl.run() is True
	assert domain._run.call_count == 8
	assert target._run.call_count == 4
	assert crawl.nodes_done == 4


@pytest.mark.parametrize('max_depth, expected', [
	(0, {'root'}),
	(1, {'root', 'child'}),
	(2, {'root', 'child', 'leaf'}),
])
def test_crawl_maximum_depth_includes_boundary(max_depth, expected):
	"""Include nodes at the integer depth limit without requesting their children."""
	objects = {index: {'id': index} for index in ['root', 'child', 'leaf']}
	children = {'root': ['child'], 'child': ['leaf']}
	crawl, domain, target = _make_crawl(objects, children, domain_options = {'max_depth': max_depth})

	assert crawl.run() is True
	assert {call.args[0]['arguments']['id'] for call in target._run.call_args_list} == expected
	assert domain._run.call_count == 2 * len(expected) - 1
	assert crawl.nodes_done == len(expected)
	assert crawl.nodes_pending == 0
	assert crawl.error is False


@pytest.mark.parametrize('boundary', ['boundary_including', 'boundary_excluding'])
def test_crawl_boundaries_require_all_conditions(boundary):
	"""Stop at matching boundaries and include them only for an inclusive boundary setting."""
	objects = {
		'root': {'id': 'root', 'kind': 'group'},
		'boundary': {'id': 'boundary', 'kind': 'section', 'closed': True},
		'open': {'id': 'open', 'kind': 'section', 'closed': False},
		'hidden': {'id': 'hidden', 'kind': 'text'},
		'leaf': {'id': 'leaf', 'kind': 'text'},
	}
	children = {'root': ['boundary', 'open'], 'boundary': ['hidden'], 'open': ['leaf']}
	domain_options = {boundary: {'kind': 'section', 'closed': True}}
	crawl, domain, target = _make_crawl(objects, children, domain_options = domain_options)

	assert crawl.run() is True
	expected = {'root', 'open', 'leaf'}
	if boundary == 'boundary_including':
		expected.add('boundary')
	assert {call.args[0]['arguments']['id'] for call in target._run.call_args_list} == expected
	expanded = {call.args[0]['arguments']['index'] for call in domain._run.call_args_list if call.args[0]['name'] == 'children'}
	assert expanded == {'root', 'open', 'leaf'}
	assert crawl.nodes_done == 4
	assert crawl.nodes_pending == 0
	assert crawl.error is False


def test_crawl_acceptance_filters_delivery_without_pruning():
	"""Traverse rejected nodes and send only objects matching every acceptance condition."""
	objects = {
		'root': {'id': 'root', 'kind': 'text', 'ready': False},
		'child': {'id': 'child', 'kind': 'image', 'ready': True},
		'leaf': {'id': 'leaf', 'kind': 'text', 'ready': True},
	}
	children = {'root': ['child'], 'child': ['leaf']}
	target_options = {'accept': {'kind': 'text', 'ready': True}}
	crawl, domain, target = _make_crawl(objects, children, target_options = target_options)

	assert crawl.run() is True
	target._run.assert_called_once_with({'name': 'store', 'arguments': objects['leaf']})
	assert domain._run.call_count == 6
	assert crawl.nodes_done == 3
	assert crawl.nodes_pending == 0
	assert crawl.error is False


def test_crawl_serializes_after_boundary_and_acceptance_checks():
	"""Check original objects before sending the serializer's converted data to the target."""
	objects = {index: {'kind': 'raw', 'text': index} for index in ['root', 'child']}
	children = {'root': ['child']}
	serialized = []

	def serialize(index, obj):
		"""Record the string id and original dictionary, then return the target dictionary."""
		serialized.append((index, obj))
		return {'id': index, 'kind': 'converted', 'text': obj['text'].upper()}

	domain_options = {'boundary_including': {'kind': 'converted'}}
	target_options = {'accept': {'kind': 'raw'}, 'serializer': serialize}
	crawl, _, target = _make_crawl(objects, children, domain_options, target_options)

	assert crawl.run() is True
	assert serialized == [('root', objects['root']), ('child', objects['child'])]
	assert [call.args[0]['arguments'] for call in target._run.call_args_list] == [
		{'id': 'root', 'kind': 'converted', 'text': 'ROOT'},
		{'id': 'child', 'kind': 'converted', 'text': 'CHILD'},
	]
	assert crawl.nodes_done == 2
	assert crawl.error is False


def test_crawl_serializer_rejection_preserves_traversal():
	"""Treat a None serializer result as a skipped delivery and continue to its children."""
	objects = {index: {'id': index} for index in ['root', 'child']}
	serializer = Mock(side_effect = [None, objects['child']])
	crawl, _, target = _make_crawl(objects, {'root': ['child']}, target_options = {'serializer': serializer})

	assert crawl.run() is True
	assert serializer.call_count == 2
	target._run.assert_called_once_with({'name': 'store', 'arguments': objects['child']})
	assert crawl.nodes_done == 2
	assert crawl.nodes_pending == 0
	assert crawl.error is False


@pytest.mark.parametrize('capability', ['get_object', 'children', 'store'])
@pytest.mark.parametrize('failure', ['response', 'exception'])
def test_crawl_halts_on_capability_failure(capability, failure):
	"""Halt without counting a failed node when a capability reports an error or raises."""
	crawl, domain, target = _make_crawl(children = {'root': ['child']})
	run_domain = domain._run.side_effect

	def run_capability(request):
		"""Inject the selected failure into a capability request dictionary."""
		if request['name'] == capability:
			if failure == 'exception':
				raise RuntimeError('Capability failed')
			return {'finish_reason': 'ERROR', 'message': None}
		return run_domain(request)

	if capability == 'store':
		target._run.side_effect = run_capability
	else:
		domain._run.side_effect = run_capability

	assert crawl.run() is False
	assert crawl.error is True
	assert crawl.finished is True
	assert crawl.nodes_done == 0
	assert crawl.nodes_pending == (1 if capability == 'store' else 0)
	assert target._run.call_count == (1 if capability == 'store' else 0)
	calls_before = (domain._run.call_count, target._run.call_count)
	assert crawl._run_step() is False
	assert (domain._run.call_count, target._run.call_count) == calls_before


@pytest.mark.parametrize('obj, conditions, expected', [
	(None, {}, False),
	([], {}, False),
	({}, None, False),
	({}, [], False),
	({'kind': 'text'}, {'kind': 'image'}, False),
	({}, {'kind': 'text'}, False),
	({'kind': 'text', 'ready': False}, {'kind': 'text', 'ready': True}, False),
	({'kind': 'text', 'ready': True}, {'kind': 'text', 'ready': True}, True),
	({'kind': 'text'}, {}, True),
])
def test_crawl_matches_dictionary_conditions(obj, conditions, expected):
	"""Require dictionary inputs and all condition values; an empty condition dictionary matches any dictionary."""
	assert Crawl._matches(obj, conditions) is expected


# if __name__ == "__main__":
# 	pytest.main([__file__])
