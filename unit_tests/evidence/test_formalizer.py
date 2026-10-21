import shutil
import sys
import types

from pathlib import Path

import networkx as nx
import pandas as pd
import pytest

from mercury.graph.evidence import AgenticGraph, Endpoint, Formalizer
from mercury.graph.evidence.agentic import AgenticRunInvalidRequest
from mercury.graph.evidence.formalizer import FormalizerState


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


class DummySchema:
	"""Record the entity schema supplied to the model."""

	def __init__(self, model):
		"""Keep the owning model to expose requested schemas to assertions."""
		self.model = model

	def entities(self, schema):
		"""Store and return the entity schema expected by DummyModel.extract."""
		self.model.entity_schema = schema
		return schema


class DummyModel:
	"""Small deterministic replacement for the GLiNER extractor."""

	loaded = []
	fail_loading = False
	entities = {}

	@classmethod
	def from_pretrained(cls, model, **arguments):
		"""Create a model or reproduce an extractor load failure."""
		cls.loaded.append((model, arguments))
		if cls.fail_loading:
			raise RuntimeError('cannot load')
		return cls()

	def create_schema(self):
		"""Return a schema recorder for entity extraction."""
		return DummySchema(self)

	def extract(self, text, schema, include_confidence = False):
		"""Record the request and return the configured entities, as GLiNER2 does with include_confidence."""
		self.extracted = (text, include_confidence)
		return {'entities': DummyModel.entities}

	def extract_json(self, text, format):
		"""Return the relationship format supplied by the Formalizer."""
		return {'text': text, 'format': format}


def set_gliner_extractor(monkeypatch, extractor):
	"""Makes Formalizer's deferred GLiNER import return the supplied extractor.

	Args:
		monkeypatch (pytest.MonkeyPatch): pytest fixture used to restore the module cache.
		extractor (type): class returned by importing ``gliner2.AutoExtractor``.
	"""
	module = types.ModuleType('gliner2')
	module.AutoExtractor = extractor
	monkeypatch.setitem(sys.modules, 'gliner2', module)


def _configuration(**extra):
	"""Return a complete Formalizer configuration, optionally extended by extra."""
	conf = {
		'description': ['Extract', 'evidence'],
		'model': {'library': 'gliner2', 'model': 'dummy', 'map_location': 'cpu', 'quantize': True, 'compile': False},
		'ontology': 'ontology'
	}
	conf.update(extra)
	return conf


def _ready_formalizer(monkeypatch, directory):
	"""Build a ready Formalizer with a deterministic model and an ontology of two entities and one relationship."""
	set_gliner_extractor(monkeypatch, DummyModel)
	DummyModel.loaded = []
	DummyModel.fail_loading = False
	DummyModel.entities = {}
	formalizer = Formalizer(schema = 'test', extra_args = _configuration())
	formalizer.tools['formalizer_test/agentic_graph_ontology'] = _multigraph(directory, ('person', 'place'), (('located', 'person', 'place'),))
	formalizer.pilot(FormalizerState.READY.value)
	return formalizer


def test_formalizer_initialization_and_calls():
	"""Exercise initial metadata, capability registration, and invalid calls."""
	Formalizer(schema = None, extra_args = {})
	formalizer = Formalizer(schema = 'any', extra_args = {'description': ['One', 'Two']})
	assert type(formalizer) is Formalizer
	assert formalizer.conf == {'description': ['One', 'Two']}
	assert formalizer.meta['description'] == 'One\nTwo'
	assert len(formalizer.meta['capabilities']) == 3
	assert formalizer._dry_run({'cmd': 'test'}) == {'status': 0, 'description': 'Valid request.'}

	with pytest.raises(KeyError):
		formalizer.run({'cmd': 'test'})

	with pytest.raises(AgenticRunInvalidRequest):
		formalizer._run({'name': 'missing', 'function': 'missing', 'arguments': {}})


def test_formalizer_pilot_model_outcomes(monkeypatch):
	"""Cover missing, unsupported, incomplete, and failed model initialization."""
	missing = Formalizer(schema = 'missing', extra_args = {}, logger = [])
	missing.pilot(100)
	assert missing.meta['state'] == FormalizerState.ERR_MODEL_INIT.value

	unsupported = Formalizer(schema = 'unsupported', extra_args = {'model': {'library': 'other', 'model': 'x'}}, logger = [])
	unsupported.pilot(100)
	assert unsupported.meta['state'] == FormalizerState.ERR_MODEL_INIT.value

	no_model = Formalizer(schema = 'no_model', extra_args = {'model': {'library': 'gliner2'}}, logger = [])
	no_model.pilot(100)
	assert no_model.meta['state'] == FormalizerState.ERR_MODEL_INIT.value

	set_gliner_extractor(monkeypatch, DummyModel)
	DummyModel.fail_loading = True
	failed = Formalizer(schema = 'failed', extra_args = _configuration(), logger = [])
	failed.pilot(100)
	assert failed.meta['state'] == FormalizerState.ERR_MODEL_INIT.value
	failed.pilot(100)
	assert len(failed.logger) == 2


def test_formalizer_pilot_ontology_outcomes(monkeypatch):
	"""Cover stepwise piloting and the ontology configuration failures."""
	set_gliner_extractor(monkeypatch, DummyModel)
	DummyModel.loaded = []
	DummyModel.fail_loading = False
	stepwise = Formalizer(schema = 'stepwise', extra_args = _configuration())
	stepwise.pilot(100, just_once = True)
	assert stepwise.meta['state'] == FormalizerState.MODEL_LOADED_OK.value
	stepwise.pilot(100, just_once = True)
	assert stepwise.meta['state'] == FormalizerState.ERR_ONTOLOGY_INIT.value

	no_ontology = Formalizer(schema = 'none', extra_args = _configuration(ontology = None), logger = [])
	no_ontology.pilot(100)
	assert no_ontology.meta['state'] == FormalizerState.ERR_ONTOLOGY_INIT.value
	assert '"ontology" is mandatory' in no_ontology.logger[-1]['error']

	missing_tool = Formalizer(schema = 'tool', extra_args = _configuration(ontology = 'people'), logger = [])
	missing_tool.pilot(100)
	assert missing_tool.meta['state'] == FormalizerState.ERR_ONTOLOGY_INIT.value
	assert 'agentic_graph_people' in missing_tool.logger[-1]['error']


def test_formalizer_pilot_ready_exposes_every_capability(monkeypatch, tmp_path):
	"""A ready Formalizer has loaded its model and exposes all its capabilities."""
	formalizer = _ready_formalizer(monkeypatch, tmp_path)
	assert formalizer.meta['state'] == FormalizerState.READY.value
	assert DummyModel.loaded == [('dummy', {'map_location': 'cpu', 'quantize': True, 'compile': False})]
	assert [capability['function']['name'] for capability in formalizer.meta['capabilities']] == ['hint_nodes_test', 'hint_edges_test', 'is_a_test']


def test_formalizer_pilot_just_once_reaches_each_stage(monkeypatch, tmp_path):
	"""Stop after model, ontology, and ready transitions when requested."""
	set_gliner_extractor(monkeypatch, DummyModel)
	DummyModel.fail_loading = False
	formalizer = Formalizer(schema = 'staged', extra_args = _configuration())
	formalizer.tools['formalizer_staged/agentic_graph_ontology'] = _multigraph(tmp_path, ('person',))
	formalizer.pilot(FormalizerState.READY.value, just_once = True)
	assert formalizer.meta['state'] == FormalizerState.MODEL_LOADED_OK.value
	formalizer.pilot(FormalizerState.READY.value, just_once = True)
	assert formalizer.meta['state'] == FormalizerState.ONTOLOGY_LOADED_OK.value
	formalizer.pilot(FormalizerState.READY.value, just_once = True)
	assert formalizer.meta['state'] == FormalizerState.READY.value


def test_formalizer_hint_nodes_edges_and_is_a(monkeypatch, tmp_path):
	"""Exercise ready-state extraction with every concepts selection path."""
	formalizer = _ready_formalizer(monkeypatch, tmp_path)
	assert formalizer.hint_nodes({'text': 'Ada'}) == []
	assert formalizer._model.extracted == ('Ada', True)
	assert formalizer._model.entity_schema == {'person': 'Definition of person.', 'place': 'Definition of place.'}
	formalizer.hint_nodes({'text': 'Ada', 'concepts': ['person', 'missing']})
	assert formalizer._model.entity_schema == {'person': 'Definition of person.', 'missing': ''}
	assert formalizer.hint_edges({'text': 'Ada lives here'}) == {
		'text': 'Ada lives here', 'format': {'Definition of located.': ['person', 'place']}
	}
	assert formalizer.hint_edges({'text': 'Ada lives here', 'concepts': []}) == {'text': 'Ada lives here', 'format': {}}
	assert formalizer.hint_edges({'text': 'Ada lives here', 'concepts': ['located']}) == {
		'text': 'Ada lives here', 'format': {'Definition of located.': ['person', 'place']}
	}
	assert formalizer.is_a({'child': 'person', 'parent': 'thing'}) == 0
	assert formalizer.run({'name': 'hint_nodes_test', 'arguments': {'text': 'Ada'}})['finish_reason'] == 'stop'


def _found(*matches):
	"""Return GLiNER2 entities with confidence from (type, mention, confidence) triples."""
	entities = {}
	for concept, mention, confidence in matches:
		entities.setdefault(concept, []).append({'text': mention, 'confidence': confidence})
	return entities


def _hint_nodes(monkeypatch, directory, found):
	"""Return the output of hint_nodes on a ready Formalizer whose model finds the given entities."""
	formalizer = _ready_formalizer(monkeypatch, directory)
	DummyModel.entities = found
	return formalizer.hint_nodes({'text': 'Some text.'})


def test_hint_nodes_returns_one_node_per_mention(monkeypatch, tmp_path):
	"""Every mention is a node with its type and confidence, in the order the model found them."""
	found = _found(('person|teacher', 'Elena Ruiz', 0.9), ('organization|school', 'Riverside School', 0.8))
	assert _hint_nodes(monkeypatch, tmp_path, found) == [
		{'mention': 'Elena Ruiz', 'type': 'person|teacher', 'confidence': 0.9},
		{'mention': 'Riverside School', 'type': 'organization|school', 'confidence': 0.8}
	]


def test_hint_nodes_gives_a_mention_the_most_specific_compatible_type(monkeypatch, tmp_path):
	"""A mention found as a type and its ancestor is one node with the most specific type, even if it is less confident."""
	found = _found(('person', 'Ms. Ruiz', 0.95), ('person|teacher', 'Ms. Ruiz', 0.7))
	assert _hint_nodes(monkeypatch, tmp_path, found) == [{'mention': 'Ms. Ruiz', 'type': 'person|teacher', 'confidence': 0.7}]


def test_hint_nodes_discards_the_types_of_other_branches(monkeypatch, tmp_path):
	"""Types that are neither ancestors nor descendants of the most confident one are discarded."""
	found = _found(('person|student', 'Lucas Moreno', 0.98), ('person|teacher', 'Lucas Moreno', 0.99), ('person', 'Lucas Moreno', 0.9))
	assert _hint_nodes(monkeypatch, tmp_path, found) == [{'mention': 'Lucas Moreno', 'type': 'person|teacher', 'confidence': 0.99}]


def test_hint_nodes_breaks_ties_between_equally_specific_types_by_confidence(monkeypatch, tmp_path):
	"""When the most confident type is an ancestor of several equally specific types, the most confident of them is chosen."""
	found = _found(('person', 'Noah', 0.9), ('person|teacher', 'Noah', 0.6), ('person|student', 'Noah', 0.8))
	assert _hint_nodes(monkeypatch, tmp_path, found) == [{'mention': 'Noah', 'type': 'person|student', 'confidence': 0.8}]


def test_hint_nodes_keeps_the_highest_confidence_of_a_repeated_mention(monkeypatch, tmp_path):
	"""A mention found twice with the same type is one node with the highest confidence."""
	found = _found(('person', 'Noah', 0.6), ('person', 'Noah', 0.8))
	assert _hint_nodes(monkeypatch, tmp_path, found) == [{'mention': 'Noah', 'type': 'person', 'confidence': 0.8}]


def test_formalizer_request_state_errors_and_close():
	"""Cover unavailable request handling, logging, and resource cleanup."""
	formalizer = Formalizer(schema = 'errors', extra_args = _configuration(), logger = [])
	assert formalizer.hint_nodes({'text': 'Ada'}) is None
	assert formalizer.hint_edges({'text': 'Ada'}) is None
	assert formalizer.is_a({}) is None
	formalizer._meta_['state'] = FormalizerState.READY.value
	assert formalizer.hint_nodes({}) is None
	assert formalizer.hint_edges({}) is None
	formalizer._ontology = object()
	formalizer._model = object()
	formalizer.close(False)
	assert formalizer._ontology is None
	assert formalizer._model is None
	assert len(formalizer.logger) == 5


def test_formalizer_handles_missing_gliner_dependency(monkeypatch):
	"""Cover the optional GLiNER import fallback when the Formalizer is piloted."""
	monkeypatch.setitem(sys.modules, 'gliner2', None)
	formalizer = Formalizer(schema = 'missing_gliner', extra_args = _configuration(), logger = [])
	formalizer.pilot(FormalizerState.READY.value)
	assert formalizer.meta['state'] == FormalizerState.ERR_MODEL_INIT.value


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
	"""The endpoint created by `mge` has one ontology, used by its Formalizer and exposed, and it is valid."""
	shutil.copytree(TEMPLATE_ONTOLOGIES.parent, tmp_path / 'endpoint')
	conf = Endpoint(str(tmp_path / 'endpoint'), auto_pilot = False).conf
	extra_args = conf['ontologies']['ontology']['extra_args']
	files = {kind: {'type': 'csv', 'path': str(tmp_path / 'endpoint' / extra_args[kind]['$path'])} for kind in ('nodes', 'edges')}
	ontology = AgenticGraph(schema = 'ontology', extra_args = files)
	ontology.pilot(100)

	assert list(conf['ontologies']) == ['ontology']
	assert conf['formalizers']['GLiNER2']['extra_args']['ontology'] == 'ontology'
	assert conf['formalizers']['GLiNER2']['tools'] == ['ontology']
	assert 'ontology' in conf['expose']
	assert _validate_one(ontology) == []


def test_the_template_initial_graph_is_configured_and_valid(tmp_path):
	"""The EvidenceGraph of the endpoint created by `mge` starts from an initial graph that matches the template ontology."""
	from mercury.graph.evidence.agentic_graph import graph_from_files
	from mercury.graph.evidence.formalizer import validate_initial_graph

	shutil.copytree(TEMPLATE_ONTOLOGIES.parent, tmp_path / 'endpoint')
	conf  = Endpoint(str(tmp_path / 'endpoint'), auto_pilot = False).conf
	files = lambda extra_args, kind: {'type': 'csv', 'path': str(tmp_path / 'endpoint' / extra_args[kind]['$path'])}
	ontology_args, e_graph_args = conf['ontologies']['ontology']['extra_args'], conf['evidence_graphs']['e_graph']['extra_args']
	ontology = AgenticGraph(schema = 'ontology', extra_args = {kind: files(ontology_args, kind) for kind in ('nodes', 'edges')})
	ontology.pilot(100)

	initial = graph_from_files(files(e_graph_args, 'initial_nodes'), files(e_graph_args, 'initial_edges'))

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


def _instances(nodes, edges = ()):
	"""Return a NetworkX graph of instance ids and (src, dst, relation, id) edges, like an initial graph. None leaves the relation out."""
	ntx = nx.MultiDiGraph()
	ntx.add_nodes_from(nodes)
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


def test_formalizer_pilot_fails_with_an_invalid_ontology(monkeypatch, tmp_path):
	"""The Formalizer does not become ready with an incoherent ontology and logs every problem."""
	set_gliner_extractor(monkeypatch, DummyModel)
	DummyModel.fail_loading = False
	formalizer = Formalizer(schema = 'invalid', extra_args = _configuration(), logger = [])
	ontology = _multigraph(tmp_path, ('person|teacher', 'vehicle'), (('drives|fast', 'person|teacher', 'vehicle'),))
	formalizer.tools['formalizer_invalid/agentic_graph_ontology'] = ontology
	formalizer.pilot(FormalizerState.READY.value)

	assert formalizer.meta['state'] == FormalizerState.ERR_ONTOLOGY_INIT.value

	logged = [event['error'] for event in formalizer.logger]

	assert _mentions(logged, 'person|teacher', 'person')
	assert _mentions(logged, 'drives|fast', 'drives')


# if __name__ == "__main__":
# 	pytest.main([__file__])
