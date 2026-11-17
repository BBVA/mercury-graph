import networkx as nx
import pytest

from mercury.graph.evidence import AgenticGraph, Decider, Formalizer, MultiGraph
from mercury.graph.evidence.agentic import AgenticRunInvalidRequest
from mercury.graph.evidence.decider import DeciderState
from mercury.graph.evidence.formalizer import FormalizerState


ENTITY_TYPES = (
	('person', 'A person.'),
	('person|teacher', 'A teacher.'),
	('organization', 'An organization.'),
	('organization|school', None)
)

RELATION_TYPES = (
	('works_at', 'person', 'organization', 'Employment.'),
	('works_at|teaches_at', 'person|teacher', 'organization|school', None)
)

QUESTIONS = {'extract_nodes': 'nodes', 'match_node': 'matcher', 'extract_edges': 'edges'}

ANSWERS = {
	'extract_nodes': [{'mention': 'Ada', 'type': 'person', 'confidence': 0.9}],
	'match_node': {'score': 0.8, 'same': True},
	'extract_edges': [{'src': 'person|Ada', 'relation': 'works_at', 'dst': 'organization|School', 'confidence': 0.7}]
}


class StubDecider(Decider):
	"""Return a configured answer and record the question sent by a Formalizer."""

	def __init__(self, schema, question, answer = None, ready = True):
		"""Initialize a Decider with a question key, answer, and optional ready state."""
		super().__init__(schema = schema, extra_args = {})
		self.question = question
		self.answer = answer
		self.requests = []
		self._meta_ = self._meta()
		if ready:
			self._meta_['state'] = DeciderState.READY.value

	def _run(self, request):
		"""Record a request and return the configured answer in a Decider response."""
		self.requests.append(request)
		return {'finish_reason': 'stop', 'message': self.answer}

	def _dry_run(self, request):
		"""Accept requests without running the stub."""
		return {'status': 0, 'description': 'Valid request.'}


def _ontology(nodes = ENTITY_TYPES, relations = RELATION_TYPES, loaded = True):
	"""Build an AgenticGraph whose NetworkX data is controlled by this test."""
	graph = AgenticGraph(schema = 'ontology', extra_args = {})
	if loaded:
		ntx = nx.MultiDiGraph()
		for index, definition in nodes:
			ntx.add_node(index, definition = definition)
		for index, src, dst, definition in relations:
			ntx.add_edge(src, dst, key = index, definition = definition)
		graph._graph = MultiGraph(data = ntx)
		graph._meta_['state'] = graph.states.READY.value
	return graph


def _formalizer(questions = None, ontology = None, deciders = (), logger = None):
	"""Build a Formalizer and attach the supplied ontology and Decider tools."""
	conf = {'ontology': 'ontology'}
	if questions is not None:
		conf.update(questions)
	formalizer = Formalizer(schema = 'sample', extra_args = conf, logger = logger)
	if ontology is not None:
		formalizer.tools['%s/agentic_graph_ontology' % formalizer.id] = ontology
	for decider in deciders:
		formalizer.tools[decider.id] = decider
	return formalizer


def _ready_formalizer(questions = None, ontology = None, logger = None):
	"""Return a ready Formalizer and the stub Deciders configured for its questions."""
	if questions is None:
		questions = QUESTIONS
	if ontology is None:
		ontology = _ontology()
	deciders = {}
	for key, name in questions.items():
		if name is not None:
			deciders[key] = StubDecider(name, key.upper(), ANSWERS[key])
	formalizer = _formalizer(questions, ontology, deciders.values(), logger)
	formalizer.pilot(FormalizerState.READY.value)
	assert formalizer.meta['state'] == FormalizerState.READY.value
	return formalizer, deciders


def _errors(logger):
	"""Return error messages recorded in an Agentic logger."""
	return [event['error'] for event in logger if event['type'] == 'error']


def test_initialization_metadata_and_independent_capabilities():
	"""Metadata exposes only configured questions and each capability is a fresh copy."""
	discovery = Formalizer(schema = None, extra_args = None)
	assert discovery.id == 'formalizer'
	assert not hasattr(discovery, 'conf')

	formalizer = Formalizer(schema = 'sample', extra_args = {'description': ['First', 'Second'], 'extract_nodes': 'nodes'})
	assert formalizer.meta['state'] == FormalizerState.INITIAL.value
	assert formalizer.meta['description'] == 'First\nSecond'
	assert formalizer._ontology is None
	assert formalizer._deciders == {}
	assert [cap['function']['name'] for cap in formalizer.meta['capabilities']] == ['extract_nodes_sample']
	assert formalizer.call == {'extract_nodes_sample': 'extract_nodes'}
	assert formalizer._dry_run({}) == {'status': 0, 'description': 'Valid request.'}

	capabilities = formalizer._capabilities()
	capabilities[0]['function']['parameters']['required'].append('unexpected')
	assert formalizer._capabilities()[0]['function']['parameters']['required'] == ['text']
	assert Formalizer.FUNCTIONS['extract_nodes']['function']['parameters']['required'] == ['text']

	assert Formalizer(schema = 'empty', extra_args = {}).meta['description'] == ''
	assert Formalizer(schema = 'plain', extra_args = {'description': 'One line'}).meta['description'] == 'One line'
	assert Formalizer(schema = 'empty', extra_args = {}).meta['capabilities'] == []


def test_pilot_advances_one_stage_at_a_time_and_close_releases_tools():
	"""Piloting reaches each state in order and close discards ontology and Decider references."""
	ontology = _ontology()
	decider = StubDecider('nodes', 'EXTRACT_NODES')
	formalizer = _formalizer({'extract_nodes': 'nodes'}, ontology, [decider])
	assert decider.dry_run({}) == {'status': 0, 'description': 'Valid request.'}

	for expected in (FormalizerState.ONTOLOGY_LOADED_OK, FormalizerState.DECIDER_LOADED_OK, FormalizerState.READY):
		formalizer.pilot(FormalizerState.READY.value, just_once = True)
		assert formalizer.meta['state'] == expected.value

	assert formalizer._ontology is ontology
	assert formalizer._deciders == {'extract_nodes': decider}
	formalizer.pilot(FormalizerState.READY.value)
	assert formalizer.meta['state'] == FormalizerState.READY.value
	formalizer.close(endpoint_locked = False)
	assert formalizer._ontology is None
	assert formalizer._deciders == {}


def test_pilot_rejects_missing_and_unloaded_ontology():
	"""A missing setting, a missing tool, and an unloaded ontology each stop piloting."""
	for conf, tool, expected in (
		({}, None, '"ontology" is mandatory'),
		({'ontology': 'ontology'}, None, 'agentic_graph_ontology'),
		({'ontology': 'ontology'}, _ontology(loaded = False), 'not loaded')
	):
		logger = []
		formalizer = Formalizer(schema = 'sample', extra_args = conf, logger = logger)
		if tool is not None:
			formalizer.tools['formalizer_sample/agentic_graph_ontology'] = tool
		formalizer.pilot(FormalizerState.READY.value)
		assert formalizer.meta['state'] == FormalizerState.ERR_ONTOLOGY_INIT.value
		assert any(expected in error for error in _errors(logger))
		formalizer.pilot(FormalizerState.READY.value)
		assert 'error state' in _errors(logger)[-1]


def test_pilot_logs_every_invalid_ontology_problem():
	"""Piloting reports every missing parent and invalid inherited relation end."""
	nodes = ENTITY_TYPES + (('place|room', 'A room.'),)
	relations = RELATION_TYPES + (
		('missing|child', 'person', 'organization', 'Orphan relation.'),
		('works_at|invalid', 'organization', 'person', 'Wrong ends.')
	)
	logger = []
	formalizer = _formalizer({'extract_nodes': 'nodes'}, _ontology(nodes, relations), logger = logger)
	formalizer.pilot(FormalizerState.READY.value)
	errors = _errors(logger)

	assert formalizer.meta['state'] == FormalizerState.ERR_ONTOLOGY_INIT.value
	assert formalizer._ontology is None
	assert any('place|room' in error and 'place' in error for error in errors)
	assert any('missing|child' in error and 'missing' in error for error in errors)
	assert any('works_at|invalid' in error and 'src' in error for error in errors)
	assert any('works_at|invalid' in error and 'dst' in error for error in errors)


def test_pilot_requires_a_configured_question():
	"""An ontology alone cannot make the Formalizer ready."""
	logger = []
	formalizer = _formalizer(ontology = _ontology(), logger = logger)
	formalizer.pilot(FormalizerState.READY.value)

	assert formalizer.meta['state'] == FormalizerState.ERR_DECIDER_INIT.value
	assert 'answers no question' in _errors(logger)[0]


@pytest.mark.parametrize('decider, message', [
	(None, 'not found'),
	(StubDecider('nodes', 'MATCH_NODE'), 'answers MATCH_NODE, not EXTRACT_NODES'),
	(StubDecider('nodes', 'EXTRACT_NODES', ready = False), 'is not ready')
])
def test_pilot_rejects_unavailable_or_incompatible_decider(decider, message):
	"""Piloting rejects absent, wrong-question, and unready Deciders."""
	logger = []
	tools = [] if decider is None else [decider]
	formalizer = _formalizer({'extract_nodes': 'nodes'}, _ontology(), tools, logger)
	formalizer.tools['unrelated'] = object()
	formalizer.pilot(FormalizerState.READY.value)

	assert formalizer.meta['state'] == FormalizerState.ERR_DECIDER_INIT.value
	assert formalizer._deciders == {}
	assert any(message in error for error in _errors(logger))


def test_pilot_rejects_partial_decider_registration():
	"""All configured questions need matching Deciders before any are retained."""
	logger = []
	nodes = StubDecider('nodes', 'EXTRACT_NODES')
	formalizer = _formalizer({'extract_nodes': 'nodes', 'match_node': 'matcher'}, _ontology(), [nodes], logger)
	formalizer.pilot(FormalizerState.READY.value)

	assert formalizer.meta['state'] == FormalizerState.ERR_DECIDER_INIT.value
	assert formalizer._deciders == {}
	assert len(_errors(logger)) == 1


def test_direct_calls_translate_nodes_edges_and_match_questions():
	"""Every direct capability passes its documented data and ontology details to its Decider."""
	formalizer, deciders = _ready_formalizer()
	context = [{'source': 'article'}]
	nodes = [{'mention': 'Ada', 'id': 'person|Ada'}]
	mention = {'mention': 'Ada', 'type': 'person|teacher', 'texts': ['Ada teaches.']}
	known = {'id': 'person|teacher|Ada', 'description': 'A teacher.'}

	assert formalizer.extract_nodes({'text': 'Ada teaches.', 'context': context}) == ANSWERS['extract_nodes']
	assert deciders['extract_nodes'].requests[-1] == {
		'name': 'extract_nodes_nodes',
		'arguments': {
			'text': 'Ada teaches.', 'ontology': {'types': [
				{'id': 'person', 'definition': 'A person.'},
				{'id': 'person|teacher', 'definition': 'A teacher.'},
				{'id': 'organization', 'definition': 'An organization.'},
				{'id': 'organization|school', 'definition': ''}
			]}, 'context': context
		}
	}

	assert formalizer.extract_edges({'text': 'Ada teaches.', 'nodes': nodes}) == ANSWERS['extract_edges']
	assert deciders['extract_edges'].requests[-1] == {
		'name': 'extract_edges_edges',
		'arguments': {
			'text': 'Ada teaches.', 'nodes': nodes, 'ontology': {'relations': [
				{'id': 'works_at', 'src': 'person', 'dst': 'organization', 'definition': 'Employment.'},
				{'id': 'works_at|teaches_at', 'src': 'person|teacher', 'dst': 'organization|school', 'definition': ''}
			]}
		}
	}

	assert formalizer.match_node({'mention': mention, 'node': known, 'context': context}) == ANSWERS['match_node']
	assert mention == {'mention': 'Ada', 'type': 'person|teacher', 'texts': ['Ada teaches.']}
	assert deciders['match_node'].requests[-1] == {
		'name': 'match_node_matcher',
		'arguments': {
			'mention': {'mention': 'Ada', 'type': 'person|teacher', 'texts': ['Ada teaches.'], 'definition': 'A teacher.'},
			'node': known, 'context': context
		}
	}


def test_selected_types_and_relations_preserve_requested_order():
	"""Explicit ids restrict the question to those ontology entries in caller order."""
	formalizer, deciders = _ready_formalizer()
	nodes = [{'mention': 'Ada', 'id': 'person|Ada'}]

	formalizer.extract_nodes({'text': 'Ada', 'types': ['organization|school', 'person']})
	assert deciders['extract_nodes'].requests[-1]['arguments']['ontology']['types'] == [
		{'id': 'organization|school', 'definition': ''}, {'id': 'person', 'definition': 'A person.'}
	]

	formalizer.extract_edges({'text': 'Ada', 'nodes': nodes, 'relations': ['works_at|teaches_at'], 'context': []})
	assert deciders['extract_edges'].requests[-1]['arguments'] == {
		'text': 'Ada', 'nodes': nodes,
		'ontology': {'relations': [{'id': 'works_at|teaches_at', 'src': 'person|teacher', 'dst': 'organization|school',
									'definition': ''}]}, 'context': []
	}

	formalizer.match_node({'mention': {'mention': 'School', 'type': 'organization|school'},
						   'node': {'id': 'organization|school|School', 'description': 'A school.'}})
	assert deciders['match_node'].requests[-1]['arguments']['mention']['definition'] == ''


def test_run_dispatches_capability_and_rejects_unknown_name():
	"""The Agentic request interface dispatches configured functions by name."""
	logger = []
	formalizer, deciders = _ready_formalizer(logger = logger)
	request = {'name': 'extract_nodes_sample', 'arguments': {'text': 'Ada'}}
	assert formalizer.run(request) == {'finish_reason': 'stop', 'message': ANSWERS['extract_nodes']}
	assert deciders['extract_nodes'].requests[-1]['arguments']['text'] == 'Ada'

	with pytest.raises(AgenticRunInvalidRequest):
		formalizer.run({'name': 'missing', 'arguments': {}})
	assert 'does not have a function named "missing"' in _errors(logger)[-1]


def test_answer_requires_ready_formalizer_and_configured_question():
	"""Calls before readiness or for an unconfigured question return None with an error."""
	logger = []
	formalizer = _formalizer({'extract_nodes': 'nodes'}, _ontology(), [StubDecider('nodes', 'EXTRACT_NODES')], logger)
	assert formalizer.extract_nodes({'text': 'Ada'}) is None
	assert 'is not ready' in _errors(logger)[-1]

	formalizer.pilot(FormalizerState.READY.value)
	assert formalizer.match_node({'mention': {'mention': 'Ada', 'type': 'person'}, 'node': {'id': 'person|Ada'}}) is None
	assert 'does not answer match_node' in _errors(logger)[-1]


@pytest.mark.parametrize('question, arguments, message', [
	('extract_nodes', None, 'arguments must be a dictionary'),
	('extract_nodes', {}, 'Missing argument "text"'),
	('extract_nodes', {'text': 4}, 'Argument "text" must be of type string'),
	('extract_nodes', {'text': 'Ada', 'unexpected': True}, 'Unknown argument "unexpected"'),
	('extract_nodes', {'text': 'Ada', 'types': ['person', 5]}, 'Argument "types[1]" must be of type string'),
	('extract_nodes', {'text': 'Ada', 'context': ['wrong']}, 'Argument "context[0]" must be of type object'),
	('extract_edges', {'text': 'Ada', 'nodes': [{}]}, 'Argument "nodes[0]" is missing "mention"'),
	('match_node', {'mention': {}, 'node': {}}, 'Argument "mention" is missing "mention"'),
	('match_node', {'mention': {'mention': 'Ada', 'type': 'person'}, 'node': {}}, 'Argument "node" is missing "id"')
])
def test_invalid_arguments_are_logged_without_calling_decider(question, arguments, message):
	"""Invalid top-level arguments and object or array fields fail before Decider dispatch."""
	logger = []
	formalizer, deciders = _ready_formalizer(logger = logger)
	assert getattr(formalizer, question)(arguments) is None
	assert any(message in error for error in _errors(logger))
	assert deciders[question].requests == []


def test_each_invalid_argument_is_reported():
	"""A request with several argument defects logs every problem."""
	logger = []
	formalizer, _ = _ready_formalizer(logger = logger)
	formalizer.extract_edges({'text': 'Ada', 'nodes': [{'mention': 'Ada'}], 'extra': 1})
	errors = _errors(logger)
	assert len(errors) == 2
	assert any('nodes[0]' in error and '"id"' in error for error in errors)
	assert any('Unknown argument "extra"' in error for error in errors)


def test_unknown_ontology_ids_are_reported_without_decider_calls():
	"""Unknown type, relation, and mention type ids fail during question translation."""
	logger = []
	formalizer, deciders = _ready_formalizer(logger = logger)
	nodes = [{'mention': 'Ada', 'id': 'person|Ada'}]

	assert formalizer.extract_nodes({'text': 'Ada', 'types': ['person', 'missing', 'also_missing']}) is None
	assert formalizer.extract_edges({'text': 'Ada', 'nodes': nodes, 'relations': ['absent']}) is None
	assert formalizer.match_node({'mention': {'mention': 'Ada', 'type': 'animal'},
								  'node': {'id': 'animal|Ada', 'description': 'An animal.'}}) is None
	errors = _errors(logger)
	assert any('Type "missing" is not in the ontology' in error for error in errors)
	assert any('Type "also_missing" is not in the ontology' in error for error in errors)
	assert any('Relation "absent" is not in the ontology' in error for error in errors)
	assert any('Type "animal" of the mention is not in the ontology' in error for error in errors)
	assert all(decider.requests == [] for decider in deciders.values())


def test_validate_ontology_accepts_hierarchy_and_requires_loaded_graph():
	"""Valid parent chains and inherited ends pass, while an unloaded ontology has one error."""
	formalizer = _formalizer()
	assert formalizer._validate_ontology(_ontology()) == []
	assert formalizer._validate_ontology(_ontology(loaded = False)) == ['Ontology "ontology" is not loaded.']


def test_validate_ontology_reports_missing_parents_and_wrong_inherited_ends():
	"""Entity and relation parents, and both ends of a child relation, are checked."""
	nodes = ENTITY_TYPES + (('place|room', 'A room.'),)
	relations = RELATION_TYPES + (
		('missing|child', 'person', 'organization', 'Orphan.'),
		('works_at|invalid', 'organization', 'person', 'Wrong.')
	)
	errors = _formalizer()._validate_ontology(_ontology(nodes, relations))
	assert len(errors) == 4
	assert any('Entity "place|room" has no parent "place"' in error for error in errors)
	assert any('Relationship "missing|child" has no parent "missing"' in error for error in errors)
	assert any('Relationship "works_at|invalid" has src "organization"' in error for error in errors)
	assert any('Relationship "works_at|invalid" has dst "person"' in error for error in errors)


def test_validate_initial_graph_accepts_described_instances_and_edges():
	"""Instances of declared types with described nodes and compatible edges are valid."""
	formalizer, _ = _ready_formalizer()
	ntx = nx.MultiDiGraph()
	ntx.add_node('person|teacher|Ada', description = 'A teacher.')
	ntx.add_node('organization|school|School', description = 'A school.')
	ntx.add_edge('person|teacher|Ada', 'organization|school|School', key = 'teaches', relation = 'works_at')
	ntx.add_edge('person|teacher|Ada', 'organization|school|School', key = 'teaches_specific',
				 relation = 'works_at|teaches_at')
	assert formalizer.validate_initial_graph(ntx) == []


def test_validate_initial_graph_reports_all_instance_edge_and_description_errors():
	"""Every bad type, relation, end, and missing description is reported together."""
	formalizer, _ = _ready_formalizer()
	ntx = nx.MultiDiGraph()
	ntx.add_node('person|teacher|Ada', description = 'A teacher.')
	ntx.add_node('organization|school|School', description = None)
	ntx.add_node('vehicle|Car', description = '  ')
	ntx.add_node('Orphan', description = float('nan'))
	ntx.add_edge('person|teacher|Ada', 'organization|school|School', key = 'missing')
	ntx.add_edge('person|teacher|Ada', 'organization|school|School', key = 'unknown', relation = 'drives')
	ntx.add_edge('organization|school|School', 'person|teacher|Ada', key = 'reversed', relation = 'works_at')
	errors = formalizer.validate_initial_graph(ntx)

	assert len(errors) == 9
	assert any('Instance "Orphan" has no type' in error for error in errors)
	assert any('Instance "vehicle|Car" is of type "vehicle"' in error for error in errors)
	assert any('Edge "missing" has no relation' in error for error in errors)
	assert any('Edge "unknown" has relation "drives"' in error for error in errors)
	assert any('Edge "reversed": its src' in error for error in errors)
	assert any('Edge "reversed": its dst' in error for error in errors)
	assert any('Instance "organization|school|School" has no description' in error for error in errors)
	assert any('Instance "vehicle|Car" has no description' in error for error in errors)
	assert any('Instance "Orphan" has no description' in error for error in errors)


def test_instance_validation_does_not_require_descriptions():
	"""The internal instance check validates types and relations independently of descriptions."""
	formalizer, _ = _ready_formalizer()
	ntx = nx.MultiDiGraph()
	ntx.add_edge('person|teacher|Ada', 'organization|school|School', key = 'teaches', relation = 'works_at')
	assert formalizer._validate_instances(ntx) == []
