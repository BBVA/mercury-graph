import shutil

from pathlib import Path

import networkx as nx
import pandas as pd
import pytest

from mercury.graph.evidence import AgenticGraph, Endpoint, Formalizer
from mercury.graph.evidence.agentic import AgenticRunInvalidRequest
from mercury.graph.evidence.decider import Decider
from mercury.graph.evidence.formalizer import DECIDERS, FormalizerState
from mercury.graph.evidence.question import Question


def _ontology(directory, name, nodes, edges = None):
	"""Return a ready AgenticGraph loaded from tab separated .csv files written in directory.

	Args:
		directory (pathlib.Path): where the .csv files are written (typically pytest's tmp_path).
		name (str): the name of the ontology.
		nodes (pandas.DataFrame): the initial nodes, with an 'id' column.
		edges (pandas.DataFrame): the optional initial edges, with 'src', 'dst' and 'id' columns.
	"""
	extra_args = {}
	for kind, data in (('nodes', nodes), ('edges', edges)):
		if data is not None:
			path = directory / ('%s_%s.csv' % (name, kind))
			data.to_csv(path, sep = '\t', index = False)
			extra_args[kind] = {'type': 'csv', 'path': str(path)}
	graph = AgenticGraph(schema = name, extra_args = extra_args)
	graph.pilot(graph.states.READY.value)
	assert graph.meta['state'] == graph.states.READY.value
	return graph


def _multigraph(directory, entities, relations = ()):
	"""Return an ontology with entity ids as nodes and (id, src, dst) tuples as edges, all of them with a definition."""
	nodes = pd.DataFrame({'id': list(entities), 'definition': ['Definition of %s.' % i for i in entities]})
	edges = pd.DataFrame(list(relations), columns = ['id', 'src', 'dst'])
	edges['definition'] = ['Definition of %s.' % i for i in edges['id']]
	return _ontology(directory, 'ontology', nodes, edges if len(relations) > 0 else None)




class FakeDecider(Decider):
	"""A Decider of extract_nodes with the answer of its configuration, which records the arguments it is asked with."""

	QUESTION = Question.EXTRACT_NODES

	def __init__(self, extra_args):
		"""Fail if the configuration says so, as a Decider that cannot be created."""
		if extra_args.get('fail', False):
			raise RuntimeError('cannot create')
		super().__init__(extra_args)
		self.asked = []

	def ready(self):
		"""Return the problems of the configuration."""
		return self.conf.get('problems', [])

	def run(self, arguments):
		"""Record the arguments and return the answer of the configuration."""
		self.asked.append(arguments)
		return self.conf.get('answer', [])


class FakeMatchDecider(FakeDecider):
	"""The same FakeDecider, for match_node."""

	QUESTION = Question.MATCH_NODE


class FakeEdgesDecider(FakeDecider):
	"""The same FakeDecider, for extract_edges."""

	QUESTION = Question.EXTRACT_EDGES


@pytest.fixture
def fake_deciders(monkeypatch):
	"""Register FakeDecider as "fake", FakeMatchDecider as "fake_match" and FakeEdgesDecider as "fake_edges"."""
	monkeypatch.setitem(DECIDERS, 'fake', FakeDecider)
	monkeypatch.setitem(DECIDERS, 'fake_match', FakeMatchDecider)
	monkeypatch.setitem(DECIDERS, 'fake_edges', FakeEdgesDecider)


ONTOLOGY = {'types': [{'id': 'person', 'definition': 'A person.'}], 'relations': []}


def _formalizer(**questions):
	"""Return a piloted Formalizer named "test" with the given questions configured (e.g., extract_nodes = {...})."""
	formalizer = Formalizer(schema = 'test', extra_args = dict(questions, description = ['Extract', 'evidence']), logger = [])
	formalizer.pilot(FormalizerState.READY.value)
	return formalizer


def _errors(formalizer):
	"""Return the errors logged by a Formalizer."""
	return [event['error'] for event in formalizer.logger if event['type'] == 'error']


def test_formalizer_initialization_and_calls():
	"""Exercise initial metadata, the capabilities of the questions configured, and invalid calls."""
	Formalizer(schema = None, extra_args = {})
	formalizer = Formalizer(schema = 'any', extra_args = {'description': ['One', 'Two'], 'extract_nodes': {'decider': 'gliner_nodes'}})
	assert type(formalizer) is Formalizer
	assert formalizer.meta['state'] == FormalizerState.INITIAL.value
	assert formalizer.meta['description'] == 'One\nTwo'
	assert [capability['function']['name'] for capability in formalizer.meta['capabilities']] == ['extract_nodes_any']
	assert formalizer._dry_run({'cmd': 'test'}) == {'status': 0, 'description': 'Valid request.'}

	with pytest.raises(KeyError):
		formalizer.run({'cmd': 'test'})

	with pytest.raises(AgenticRunInvalidRequest):
		formalizer._run({'name': 'missing', 'function': 'missing', 'arguments': {}})


def test_formalizer_exposes_only_the_questions_configured(fake_deciders):
	"""A question without a key, or with null, is not exposed; the capabilities follow the order of Question."""
	formalizer = _formalizer(match_node = {'decider': 'fake_match'}, extract_nodes = {'decider': 'fake'}, extract_edges = None)
	names = [capability['function']['name'] for capability in formalizer.meta['capabilities']]
	assert names == ['extract_nodes_test', 'match_node_test']
	assert formalizer.meta['capabilities'][0] == Question.EXTRACT_NODES.capability('test')


def test_formalizer_pilot_creates_a_ready_decider_per_question(fake_deciders):
	"""Every question configured gets its Decider, created with its "extra_args"."""
	formalizer = _formalizer(extract_nodes = {'decider': 'fake', 'extra_args': {'answer': ['x']}}, match_node = {'decider': 'fake_match'})
	assert formalizer.meta['state'] == FormalizerState.READY.value
	assert type(formalizer._deciders[Question.EXTRACT_NODES]) is FakeDecider
	assert formalizer._deciders[Question.EXTRACT_NODES].conf == {'answer': ['x']}
	assert formalizer._deciders[Question.MATCH_NODE].conf == {}
	assert Question.EXTRACT_EDGES not in formalizer._deciders


def test_formalizer_pilot_fails_without_questions():
	"""A Formalizer that answers no question stops in ERR_DECIDER_INIT."""
	formalizer = _formalizer()
	assert formalizer.meta['state'] == FormalizerState.ERR_DECIDER_INIT.value
	assert 'answers no question' in _errors(formalizer)[0]


@pytest.mark.parametrize('conf, error', [
	('fake', 'must be a dictionary'),
	({'decider': 'unknown'}, 'Unknown decider "unknown"'),
	({'decider': 'fake_match'}, 'answers match_node, not extract_nodes'),
	({'decider': 'fake', 'extra_args': {'fail': True}}, 'cannot create'),
	({'decider': 'fake', 'extra_args': {'problems': ['no model']}}, 'no model')
])
def test_formalizer_pilot_fails_without_a_ready_decider(fake_deciders, conf, error):
	"""A wrong configuration, an unknown Decider, one of another question, one that cannot be created or one with problems stop the
	Formalizer in ERR_DECIDER_INIT."""
	formalizer = _formalizer(extract_nodes = conf)
	assert formalizer.meta['state'] == FormalizerState.ERR_DECIDER_INIT.value
	assert formalizer._deciders == {}
	assert any(error in logged for logged in _errors(formalizer))


def test_formalizer_logs_every_problem_of_every_decider(fake_deciders):
	"""Every problem of every Decider is logged, not only the first one."""
	formalizer = _formalizer(extract_nodes = {'decider': 'fake', 'extra_args': {'problems': ['no model', 'no key']}},
							 match_node = {'decider': 'unknown'})
	errors = _errors(formalizer)
	assert len(errors) == 3
	assert any('no model' in error for error in errors) and any('no key' in error for error in errors)
	assert any('Unknown decider' in error for error in errors)


def test_formalizer_pilot_logs_from_an_error_state(fake_deciders):
	"""Piloting again a Formalizer in an error state only logs it."""
	formalizer = _formalizer()
	formalizer.pilot(FormalizerState.READY.value)
	assert formalizer.meta['state'] == FormalizerState.ERR_DECIDER_INIT.value
	assert len(_errors(formalizer)) == 2


def test_formalizer_passes_the_arguments_to_the_decider_and_returns_its_answer(fake_deciders):
	"""A question is answered by its Decider, with the arguments as given, called directly or by its capability name."""
	formalizer = _formalizer(extract_nodes = {'decider': 'fake', 'extra_args': {'answer': [{'mention': 'Ada'}]}})
	arguments  = {'text': 'Ada', 'ontology': ONTOLOGY, 'context': [{'description': 'book', 'content': 'A book.'}]}
	assert formalizer.extract_nodes(arguments) == [{'mention': 'Ada'}]
	assert formalizer.run({'name': 'extract_nodes_test', 'arguments': arguments}) == {'finish_reason': 'stop', 'message': [{'mention': 'Ada'}]}
	assert formalizer._deciders[Question.EXTRACT_NODES].asked == [arguments, arguments]


def test_formalizer_does_not_answer_when_it_is_not_ready():
	"""Before piloting, every question returns None and logs why."""
	formalizer = Formalizer(schema = 'test', extra_args = {'extract_nodes': {'decider': 'gliner_nodes'}}, logger = [])
	assert formalizer.extract_nodes({'text': 'Ada', 'ontology': ONTOLOGY}) is None
	assert 'not ready for extract_nodes' in _errors(formalizer)[0]


def test_formalizer_does_not_answer_a_question_it_is_not_configured_for(fake_deciders):
	"""A question without a Decider returns None and logs why."""
	formalizer = _formalizer(extract_nodes = {'decider': 'fake'})
	assert formalizer.match_node({'mention': {}, 'node': {}}) is None
	assert formalizer.extract_edges({'text': 'Ada', 'nodes': [], 'ontology': ONTOLOGY}) is None
	assert 'does not answer match_node' in _errors(formalizer)[0]
	assert 'does not answer extract_edges' in _errors(formalizer)[1]


@pytest.mark.parametrize('arguments, problems', [
	({'text': 'Ada'}, ['Missing argument "ontology"']),
	({'text': 'Ada', 'ontology': ONTOLOGY, 'concepts': ['person']}, ['Unknown argument "concepts"']),
	({'text': ['Ada'], 'ontology': 'person', 'context': {}}, ['"text" must be of type string', '"ontology" must be of type object',
															 '"context" must be of type array']),
	('Ada', ['must be a dictionary'])
])
def test_formalizer_rejects_arguments_that_are_not_those_of_the_question(fake_deciders, arguments, problems):
	"""Missing, unknown or mistyped arguments return None, log every problem and do not reach the Decider."""
	formalizer = _formalizer(extract_nodes = {'decider': 'fake'})
	assert formalizer.extract_nodes(arguments) is None
	errors = _errors(formalizer)
	assert len(errors) == len(problems)
	for problem, error in zip(problems, errors):
		assert problem in error
	assert formalizer._deciders[Question.EXTRACT_NODES].asked == []


def test_formalizer_match_node_takes_the_definition_of_the_mention_instead_of_the_ontology(fake_deciders):
	"""match_node holds all it needs in its mention and node: the ontology is an unknown argument."""
	formalizer = _formalizer(extract_nodes = None, match_node = {'decider': 'fake_match', 'extra_args': {'answer': {'same': True}}})
	mention	   = {'mention': 'Ada', 'type': 'person', 'definition': 'A person.', 'texts': ['Ada wrote.']}
	node	   = {'id': 'person|Ada Lovelace', 'description': 'A mathematician.'}
	assert formalizer.match_node({'mention': mention, 'node': node}) == {'same': True}
	assert formalizer.match_node({'mention': mention, 'node': node, 'ontology': ONTOLOGY}) is None
	assert 'Unknown argument "ontology"' in _errors(formalizer)[0]
	assert 'ontology' not in Question.MATCH_NODE.value['function']['parameters']['properties']


MENTION = {'mention': 'Ada', 'type': 'person', 'definition': 'A person.'}
NODE	= {'id': 'person|Ada Lovelace', 'description': 'A mathematician.'}


@pytest.mark.parametrize('arguments, problems', [
	({'mention': {'type': 'person|person', 'definition': 'A person.', 'texts': ['Ada']}, 'node': NODE},
	 ['Argument "mention" is missing "mention"']),
	({'mention': {'mention': 'Ada'}, 'node': {'id': 'person|Ada Lovelace'}},
	 ['Argument "mention" is missing "type"', 'Argument "mention" is missing "definition"', 'Argument "node" is missing "description"'])
])
def test_formalizer_rejects_a_mention_or_node_without_its_required_fields(fake_deciders, arguments, problems):
	"""match_node with a mention or a node that misses a required field returns None, logs every problem and does not reach the
	Decider."""
	formalizer = _formalizer(match_node = {'decider': 'fake_match'})
	assert formalizer.match_node(arguments) is None
	assert len(_errors(formalizer)) == len(problems)
	for problem, error in zip(problems, _errors(formalizer)):
		assert problem in error
	assert formalizer._deciders[Question.MATCH_NODE].asked == []
	assert formalizer.match_node({'mention': MENTION, 'node': NODE}) == []


def test_formalizer_rejects_nodes_of_extract_edges_without_mention_and_id(fake_deciders):
	"""Every node of extract_edges must be an object with "mention" and "id"; the problems name the position of the node."""
	formalizer = _formalizer(extract_edges = {'decider': 'fake_edges'})
	nodes	   = [{'mention': 'Ada', 'id': 'person|Ada'}, {'mention': 'Babbage'}, 'person|Ada']
	assert formalizer.extract_edges({'text': 'Ada met Babbage.', 'nodes': nodes, 'ontology': ONTOLOGY}) is None
	errors = _errors(formalizer)
	assert len(errors) == 2
	assert 'Argument "nodes[1]" is missing "id"' in errors[0]
	assert 'Argument "nodes[2]" must be an object' in errors[1]
	assert formalizer._deciders[Question.EXTRACT_EDGES].asked == []


def test_formalizer_close_releases_its_deciders(fake_deciders):
	"""Closing the Formalizer drops its Deciders."""
	formalizer = _formalizer(extract_nodes = {'decider': 'fake'})
	formalizer.close(False)
	assert formalizer._deciders == {}


def test_question_keys_and_capabilities():
	"""The key of a question is its name in lowercase and its capability is a copy named after the Formalizer."""
	capability = Question.MATCH_NODE.capability('GLiNER2')
	assert Question.MATCH_NODE.key() == 'match_node'
	assert capability['function']['name'] == 'match_node_GLiNER2'
	assert Question.MATCH_NODE.value['function']['name'] == 'match_node_%s'
	assert capability['function']['parameters']['required'] == ['mention', 'node']


TEMPLATE_ONTOLOGIES = Path(__file__).resolve().parents[2] / 'cli' / 'new_endpoint_template' / 'ontology_source'


def _mentions(errors, *ids):
	"""Return True if exactly one error mentions all the given ids."""
	return sum(all(i in e for i in ids) for e in errors) == 1


SCHOOL_ENTITIES	 = ('person', 'person|student', 'person|teacher', 'organization', 'organization|school', 'project')
SCHOOL_RELATIONS = (
	('teaches_at', 'person|teacher', 'organization|school'),
	('works_on', 'person', 'project'),
	('works_on|leads', 'person', 'project')
)


def _validate_one(ontology):
	"""Run validate_ontology() on an ontology."""
	from mercury.graph.evidence.formalizer import validate_ontology

	return validate_ontology(ontology)


def test_validate_ontology_accepts_a_valid_ontology(tmp_path):
	"""A coherent ontology has no errors, including a child relationship between descendants of the types of its parent."""
	relations = SCHOOL_RELATIONS + (('works_on|leads_research', 'person|teacher', 'project'),)

	assert _validate_one(_multigraph(tmp_path, SCHOOL_ENTITIES, relations)) == []


def test_the_template_ontology_is_configured_and_valid(tmp_path):
	"""The endpoint created by `mge` has one ontology, used by its EvidenceGraph and exposed, and it is valid."""
	shutil.copytree(TEMPLATE_ONTOLOGIES.parent, tmp_path / 'endpoint')
	conf = Endpoint(str(tmp_path / 'endpoint'), auto_pilot = False).conf
	extra_args = conf['ontologies']['ontology']['extra_args']
	files = {kind: {'type': 'csv', 'path': str(tmp_path / 'endpoint' / extra_args[kind]['$path'])} for kind in ('nodes', 'edges')}
	ontology = AgenticGraph(schema = 'ontology', extra_args = files)
	ontology.pilot(100)

	assert list(conf['ontologies']) == ['ontology']
	assert conf['evidence_graphs']['e_graph']['extra_args']['agentics']['ontology'] == 'ontology'
	assert 'ontology' in conf['evidence_graphs']['e_graph']['tools']
	assert 'ontology' in conf['expose']
	assert _validate_one(ontology) == []


def test_the_template_initial_graph_is_configured_and_valid(tmp_path):
	"""The EvidenceGraph of the endpoint created by `mge` starts from an initial graph that matches the template ontology."""
	from mercury.graph.evidence.formalizer import validate_initial_graph

	shutil.copytree(TEMPLATE_ONTOLOGIES.parent, tmp_path / 'endpoint')
	conf  = Endpoint(str(tmp_path / 'endpoint'), auto_pilot = False).conf
	files = lambda extra_args, kind: {'type': 'csv', 'path': str(tmp_path / 'endpoint' / extra_args[kind]['$path'])}
	ontology_args, e_graph_args = conf['ontologies']['ontology']['extra_args'], conf['evidence_graphs']['e_graph']['extra_args']
	ontology = AgenticGraph(schema = 'ontology', extra_args = {kind: files(ontology_args, kind) for kind in ('nodes', 'edges')})
	ontology.pilot(100)

	initial = AgenticGraph.graph_from_files(files(e_graph_args, 'initial_nodes'), files(e_graph_args, 'initial_edges'))

	assert initial.networkx.number_of_nodes() > 0 and initial.networkx.number_of_edges() > 0
	assert validate_initial_graph(initial.networkx, ontology) == []


def test_validate_ontology_requires_entity_parents(tmp_path):
	"""An entity whose parent is not defined is an error, also when only an intermediate level is missing."""
	errors = _validate_one(_multigraph(tmp_path, ('person|teacher', 'place', 'place|room|laboratory')))

	assert len(errors) == 2
	assert _mentions(errors, 'person|teacher', 'person')
	assert _mentions(errors, 'place|room|laboratory', 'place|room')


def test_an_ontology_with_repeated_relationship_ids_does_not_load(tmp_path):
	"""Two relationships with the same id and different types are rejected when the ontology is loaded."""
	nodes = pd.DataFrame({'id': list(SCHOOL_ENTITIES), 'definition': 'A definition.'})
	edges = pd.DataFrame([('belongs_to', 'person', 'organization'), ('belongs_to', 'organization|school', 'organization')],
						 columns = ['id', 'src', 'dst'])
	nodes.to_csv(tmp_path / 'nodes.csv', sep = '\t', index = False)
	edges.to_csv(tmp_path / 'edges.csv', sep = '\t', index = False)
	logger = []
	ontology = AgenticGraph(schema = 'ontology', logger = logger, extra_args = {
		'nodes': {'type': 'csv', 'path': str(tmp_path / 'nodes.csv')},
		'edges': {'type': 'csv', 'path': str(tmp_path / 'edges.csv')}})

	ontology.pilot(ontology.states.READY.value)

	assert ontology.meta['state'] == ontology.states.ERR_GRAPH_INIT.value
	assert 'Edges have repeated ids: "belongs_to".' in logger[-1]['error']


def test_validate_ontology_requires_relationship_parents(tmp_path):
	"""A relationship whose parent is not defined is an error."""
	errors = _validate_one(_multigraph(tmp_path, SCHOOL_ENTITIES, (('works_on|leads', 'person', 'project'),)))

	assert len(errors) == 1
	assert _mentions(errors, 'works_on|leads', 'works_on')


def test_validate_ontology_requires_child_relationships_between_descendants(tmp_path):
	"""The src and dst of a child relationship are those of its parent or descendants of them."""
	relations = (('works_on', 'person', 'project'), ('works_on|leads', 'organization', 'person|student'))

	errors = _validate_one(_multigraph(tmp_path, SCHOOL_ENTITIES, relations))

	assert len(errors) == 2
	assert _mentions(errors, 'works_on|leads', 'src', 'organization', 'person')
	assert _mentions(errors, 'works_on|leads', 'dst', 'person|student', 'project')


def test_validate_ontology_does_not_accept_a_prefix_as_a_parent_type(tmp_path):
	"""person_group is not a descendant of person, even if its id starts with it."""
	entities = SCHOOL_ENTITIES + ('person_group',)
	relations = (('works_on', 'person', 'project'), ('works_on|leads', 'person_group', 'project'))

	errors = _validate_one(_multigraph(tmp_path, entities, relations))

	assert len(errors) == 1
	assert _mentions(errors, 'works_on|leads', 'person_group')


def test_validate_ontology_reports_every_error_at_once(tmp_path):
	"""Problems of different kinds are all reported."""
	entities = ('person', 'place|room', 'project')
	relations = (('works_on|leads', 'person', 'project'), ('knows', 'person', 'person'), ('knows|admires', 'project', 'person'))

	errors = _validate_one(_multigraph(tmp_path, entities, relations))

	assert len(errors) == 3
	assert _mentions(errors, 'place|room')
	assert _mentions(errors, 'works_on|leads')
	assert _mentions(errors, 'knows|admires')


def test_validate_ontology_requires_a_loaded_ontology():
	"""An ontology that has not been loaded is the only problem reported."""
	errors = _validate_one(AgenticGraph(schema = 'ontology', extra_args = {}))

	assert errors == ['Ontology "ontology" is not loaded.']


def _instances(nodes, edges = (), descriptions = None):
	"""Return a NetworkX graph of instance ids and (src, dst, relation, id) edges, like an initial graph. None leaves the relation out.

	Every instance is described as "Description of <id>." unless descriptions ({id: description}) gives it another one.
	"""
	given = descriptions or {}
	ntx	  = nx.MultiDiGraph()
	for index in nodes:
		description = given.get(index, 'Description of %s.' % index)
		ntx.add_node(index, description = description)
	for src, dst, relation, key in edges:
		ntx.add_edge(src, dst, key = key, **({} if relation is None else {'relation': relation}))
	return ntx


def _validate_instances(directory, nodes, edges = ()):
	"""Run validate_initial_graph() on the given instances against an ontology of SCHOOL_ENTITIES and SCHOOL_RELATIONS."""
	from mercury.graph.evidence.formalizer import validate_initial_graph

	return validate_initial_graph(_instances(nodes, edges), _multigraph(directory, SCHOOL_ENTITIES, SCHOOL_RELATIONS))


def test_validate_initial_graph_accepts_instances_of_descendants(tmp_path):
	"""Instances of the declared types or of their descendants are valid (a student can lead a project declared from person)."""
	nodes = ['person|teacher|Elena', 'person|student|Noah', 'organization|school|Riverside', 'project|Helios']
	edges = [('person|teacher|Elena', 'organization|school|Riverside', 'teaches_at', 'elena_rhs'),
			 ('person|student|Noah', 'project|Helios', 'works_on|leads', 'noah_helios')]

	assert _validate_instances(tmp_path, nodes, edges) == []


def test_validate_initial_graph_requires_instances_of_existing_types(tmp_path):
	"""An instance without a type or of a type that is not in the ontology is an error."""
	errors = _validate_instances(tmp_path, ['Noah', 'vehicle|Car', 'person|Ada'])

	assert len(errors) == 2
	assert _mentions(errors, 'Noah')
	assert _mentions(errors, 'vehicle|Car', 'vehicle')


def test_validate_initial_graph_requires_edges_of_existing_relationships(tmp_path):
	"""An edge without a relation or with a relation that is not in the ontology is an error."""
	nodes = ['person|Ada', 'project|Helios']
	edges = [('person|Ada', 'project|Helios', None, 'no_relation'), ('person|Ada', 'project|Helios', 'drives', 'unknown')]

	errors = _validate_instances(tmp_path, nodes, edges)

	assert len(errors) == 2
	assert _mentions(errors, 'no_relation', 'has no relation')
	assert _mentions(errors, 'unknown', 'drives')


def test_validate_initial_graph_requires_edges_between_compatible_types(tmp_path):
	"""The instances of an edge must be of the types of its relation or of their descendants (person_group is not a person)."""
	nodes = ['person|student|Noah', 'organization|school|Riverside', 'person_group|Club', 'project|Helios']
	edges = [('person|student|Noah', 'organization|school|Riverside', 'teaches_at', 'noah_teaches'),
			 ('person_group|Club', 'project|Helios', 'works_on', 'club_works')]
	entities = _multigraph(tmp_path, SCHOOL_ENTITIES + ('person_group',), SCHOOL_RELATIONS)

	from mercury.graph.evidence.formalizer import validate_initial_graph
	errors = validate_initial_graph(_instances(nodes, edges), entities)

	assert len(errors) == 2
	assert _mentions(errors, 'noah_teaches', 'src', 'person|teacher')
	assert _mentions(errors, 'club_works', 'src', 'person_group|Club')


def test_validate_initial_graph_reports_every_error_at_once(tmp_path):
	"""Problems with instances and with edges are all reported."""
	errors = _validate_instances(tmp_path, ['vehicle|Car', 'person|Ada', 'project|Helios'], [('person|Ada', 'project|Helios', 'drives', 'x')])

	assert len(errors) == 2


def test_validate_initial_graph_requires_a_description_of_every_instance(tmp_path):
	"""An instance without a description, with an empty one or with an empty cell of a .csv file (NaN) is an error."""
	from mercury.graph.evidence.formalizer import validate_initial_graph

	nodes		 = ['person|Ada', 'person|Noah', 'project|Helios', 'project|Apollo']
	descriptions = {'person|Ada': None, 'person|Noah': '  ', 'project|Helios': float('nan')}
	errors		 = validate_initial_graph(_instances(nodes, descriptions = descriptions), _multigraph(tmp_path, SCHOOL_ENTITIES))

	assert len(errors) == 3
	assert _mentions(errors, 'person|Ada', 'no description')
	assert _mentions(errors, 'person|Noah', 'no description')
	assert _mentions(errors, 'project|Helios', 'no description')


def test_validate_instances_does_not_require_descriptions(tmp_path):
	"""validate_instances() only checks the types: a graph of instances without descriptions can match the ontology."""
	from mercury.graph.evidence.formalizer import validate_instances

	ntx = nx.MultiDiGraph()
	ntx.add_edge('person|Ada', 'project|Helios', key = 'ada_helios', relation = 'works_on')

	assert validate_instances(ntx, _multigraph(tmp_path, SCHOOL_ENTITIES, SCHOOL_RELATIONS)) == []


def test_the_template_formalizer_answers_every_question_with_its_decider(tmp_path):
	"""The Formalizer of the endpoint created by `mge` configures every question with a Decider of that question."""
	shutil.copytree(TEMPLATE_ONTOLOGIES.parent, tmp_path / 'endpoint')
	conf	   = Endpoint(str(tmp_path / 'endpoint'), auto_pilot = False).conf
	extra_args = conf['formalizers']['GLiNER2']['extra_args']

	for question in Question:
		decider = extra_args[question.key()]['decider']
		assert DECIDERS[decider].QUESTION is question
