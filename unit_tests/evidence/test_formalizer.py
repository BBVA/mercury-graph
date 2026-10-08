import sys
import types

from pathlib import Path

import pandas as pd
import pytest

from mercury.graph.evidence import AgenticGraph, Formalizer
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
			extra_args['initial_%s' % kind] = {'type': 'csv', 'path': str(path)}
	graph = AgenticGraph(schema = name, extra_args = extra_args)
	graph.pilot(graph.states.READY.value)
	assert graph.meta['state'] == graph.states.READY.value
	return graph


def _entities(directory, *ids):
	"""Return an entities ontology with the given concept ids."""
	return _ontology(directory, 'entities', pd.DataFrame({'id': list(ids), 'definition': ['Definition of %s.' % i for i in ids]}))


def _relationships(directory, *rows):
	"""Return a relationships ontology from (id, src, dst) tuples. None leaves the src or dst empty in the .csv file."""
	nodes = pd.DataFrame(list(rows), columns = ['id', 'src', 'dst'])
	nodes['definition'] = ['Definition of %s.' % i for i in nodes['id']]
	return _ontology(directory, 'relationships', nodes)


def _known_ids(directory, nodes, edges = ()):
	"""Return a known_ids ontology from instance ids and (src, dst, relation, key) tuples. None leaves the relation empty."""
	edges = pd.DataFrame(list(edges), columns = ['src', 'dst', 'relation', 'id']) if len(edges) > 0 else None
	return _ontology(directory, 'known_ids', pd.DataFrame({'id': list(nodes)}), edges)


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

	def extract(self, text, schema):
		"""Return entities along with the supplied text and schema."""
		return {'entities': {'text': text, 'schema': schema}}

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
	}
	conf.update(extra)
	return conf


def _ready_formalizer(monkeypatch, directory, include_relation = True, include_known_id = True):
	"""Build a ready Formalizer with deterministic model and ontology tools."""
	set_gliner_extractor(monkeypatch, DummyModel)
	DummyModel.loaded = []
	DummyModel.fail_loading = False
	ontologies = None
	if not include_relation or not include_known_id:
		ontologies = {'entities': 'entities', 'relationships': 'relationships', 'known_ids': 'known_ids'}
		if not include_relation:
			ontologies['relationships'] = None
		if not include_known_id:
			ontologies['known_ids'] = None
	formalizer = Formalizer(schema = 'test', extra_args = _configuration(ontologies = ontologies))
	entities = pd.DataFrame({'id': ['person', 'place'], 'definition': ['A person', 'A place']})
	relations = pd.DataFrame({'id': ['located'], 'src': ['person'], 'dst': ['place'], 'definition': ['is located in']})
	formalizer.tools['formalizer_test/agentic_graph_entities'] = _ontology(directory, 'entities', entities)
	if include_relation:
		formalizer.tools['formalizer_test/agentic_graph_relationships'] = _ontology(directory, 'relationships', relations)
	if include_known_id:
		formalizer.tools['formalizer_test/agentic_graph_known_ids'] = _known_ids(directory, [])
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
	"""Cover stepwise piloting and all ontology configuration failures."""
	set_gliner_extractor(monkeypatch, DummyModel)
	DummyModel.loaded = []
	DummyModel.fail_loading = False
	stepwise = Formalizer(schema = 'stepwise', extra_args = _configuration())
	stepwise.pilot(100, just_once = True)
	assert stepwise.meta['state'] == FormalizerState.MODEL_LOADED_OK.value
	stepwise.pilot(100, just_once = True)
	assert stepwise.meta['state'] == FormalizerState.ERR_ONTOLOGY_INIT.value

	malformed = Formalizer(schema = 'malformed', extra_args = _configuration(ontologies = {}), logger = [])
	malformed.pilot(100)
	assert malformed.meta['state'] == FormalizerState.ERR_ONTOLOGY_INIT.value

	missing_tool = Formalizer(schema = 'tool', extra_args = _configuration(ontologies = {'entities': 'people'}), logger = [])
	missing_tool.pilot(100)
	assert missing_tool.meta['state'] == FormalizerState.ERR_ONTOLOGY_INIT.value

	no_entities = Formalizer(schema = 'none', extra_args = _configuration(ontologies = {'entities': None, 'relationships': None, 'known_ids': None}), logger = [])
	no_entities.pilot(100)
	assert no_entities.meta['state'] == FormalizerState.ERR_ONTOLOGY_INIT.value


def test_formalizer_pilot_ready_and_optional_capabilities(monkeypatch, tmp_path):
	"""Make the Formalizer ready and remove unavailable optional capabilities."""
	formalizer = _ready_formalizer(monkeypatch, tmp_path, include_relation = False, include_known_id = False)
	assert formalizer.meta['state'] == FormalizerState.READY.value
	assert DummyModel.loaded == [('dummy', {'map_location': 'cpu', 'quantize': True, 'compile': False})]
	assert [capability['function']['name'] for capability in formalizer.meta['capabilities']] == ['hint_nodes_test']


def test_formalizer_pilot_just_once_reaches_each_stage(monkeypatch, tmp_path):
	"""Stop after model, ontology, and ready transitions when requested."""
	set_gliner_extractor(monkeypatch, DummyModel)
	DummyModel.fail_loading = False
	formalizer = Formalizer(schema = 'staged', extra_args = _configuration())
	formalizer.tools['formalizer_staged/agentic_graph_entities'] = _entities(tmp_path)
	formalizer.tools['formalizer_staged/agentic_graph_relationships'] = _relationships(tmp_path)
	formalizer.tools['formalizer_staged/agentic_graph_known_ids'] = _known_ids(tmp_path, [])
	formalizer.pilot(FormalizerState.READY.value, just_once = True)
	assert formalizer.meta['state'] == FormalizerState.MODEL_LOADED_OK.value
	formalizer.pilot(FormalizerState.READY.value, just_once = True)
	assert formalizer.meta['state'] == FormalizerState.ONTOLOGY_LOADED_OK.value
	formalizer.pilot(FormalizerState.READY.value, just_once = True)
	assert formalizer.meta['state'] == FormalizerState.READY.value


def test_formalizer_hint_nodes_edges_and_is_a(monkeypatch, tmp_path):
	"""Exercise ready-state extraction with every concepts selection path."""
	formalizer = _ready_formalizer(monkeypatch, tmp_path)
	assert formalizer.hint_nodes({'text': 'Ada'}) == {'text': 'Ada', 'schema': {'person': 'A person', 'place': 'A place'}}
	assert formalizer.hint_nodes({'text': 'Ada', 'concepts': ['person', 'missing']}) == {
		'text': 'Ada', 'schema': {'person': 'A person', 'missing': ''}
	}
	assert formalizer.hint_edges({'text': 'Ada lives here'}) == {
		'text': 'Ada lives here', 'format': {'is located in': ['person', 'place']}
	}
	assert formalizer.hint_edges({'text': 'Ada lives here', 'concepts': []}) == {'text': 'Ada lives here', 'format': {}}
	assert formalizer.hint_edges({'text': 'Ada lives here', 'concepts': ['located']}) == {
		'text': 'Ada lives here', 'format': {'is located in': ['person', 'place']}
	}
	assert formalizer.is_a({'child': 'person', 'parent': 'thing'}) == 0
	assert formalizer.run({'name': 'hint_nodes_test', 'arguments': {'text': 'Ada'}})['finish_reason'] == 'stop'


def test_formalizer_request_state_errors_and_close():
	"""Cover unavailable request handling, logging, and resource cleanup."""
	formalizer = Formalizer(schema = 'errors', extra_args = _configuration(), logger = [])
	assert formalizer.hint_nodes({'text': 'Ada'}) is None
	assert formalizer.hint_edges({'text': 'Ada'}) is None
	assert formalizer.is_a({}) is None
	formalizer._meta_['state'] = FormalizerState.READY.value
	assert formalizer.hint_nodes({}) is None
	assert formalizer.hint_edges({}) is None
	formalizer._entities = object()
	formalizer._relation = object()
	formalizer._known_id = object()
	formalizer._model = object()
	formalizer.close(False)
	assert formalizer._entities is None
	assert formalizer._relation is None
	assert formalizer._known_id is None
	assert formalizer._model is None
	assert len(formalizer.logger) == 5


def test_formalizer_handles_missing_gliner_dependency(monkeypatch):
	"""Cover the optional GLiNER import fallback when the Formalizer is piloted."""
	monkeypatch.setitem(sys.modules, 'gliner2', None)
	formalizer = Formalizer(schema = 'missing_gliner', extra_args = _configuration(), logger = [])
	formalizer.pilot(FormalizerState.READY.value)
	assert formalizer.meta['state'] == FormalizerState.ERR_MODEL_INIT.value


TEMPLATE_ONTOLOGIES = Path(__file__).resolve().parents[2] / 'cli' / 'new_endpoint_template' / 'ontology_source'


def _validate(entities, relationships = None, known_ids = None):
	"""Run validate_ontologies() on the given ontologies (or None)."""
	from mercury.graph.evidence.formalizer import validate_ontologies

	return validate_ontologies(entities, relationships, known_ids)


def _mentions(errors, *ids):
	"""Return True if exactly one error mentions all the given ids."""
	return sum(all(i in e for i in ids) for e in errors) == 1


SCHOOL_ENTITIES	 = ('person', 'person|student', 'person|teacher', 'organization', 'organization|school', 'project')
SCHOOL_RELATIONS = (
	('teaches_at', 'person|teacher', 'organization|school'),
	('works_on', 'person', 'project'),
	('works_on|leads', 'person', 'project')
)


def test_validate_ontologies_accepts_valid_ontologies(tmp_path):
	"""A coherent set of ontologies has no errors, including instances of descendants of the declared types."""
	known = _known_ids(tmp_path, 
		['person|teacher|Elena', 'person|student|Noah', 'organization|school|Riverside', 'project|Helios'],
		[
			('person|teacher|Elena', 'organization|school|Riverside', 'teaches_at', 'elena_rhs'),
			('person|student|Noah', 'project|Helios', 'works_on|leads', 'noah_helios')
		]
	)

	assert _validate(_entities(tmp_path, *SCHOOL_ENTITIES), _relationships(tmp_path, *SCHOOL_RELATIONS), known) == []


def test_validate_ontologies_accepts_the_template_ontologies():
	"""The ontologies created by `mge` for a new endpoint are valid."""
	fmt = {'src': 'src', 'dst': 'dst', 'id': 'id', 'directed': True, 'sep': '\t'}
	conf = {
		'entities': {'initial_nodes': 'entities_concepts.csv'},
		'relationships': {'initial_nodes': 'relationships_concepts.csv'},
		'known_ids': {'initial_nodes': 'known_ids_nodes.csv', 'initial_edges': 'known_ids_edges.csv'}
	}
	graphs = []
	for name, files in conf.items():
		extra_args = {k: {'type': 'csv', 'path': str(TEMPLATE_ONTOLOGIES / v)} for k, v in files.items()}
		extra_args['file_format'] = fmt
		graph = AgenticGraph(schema = name, extra_args = extra_args)
		graph.pilot(100)
		graphs.append(graph)

	assert _validate(*graphs) == []


def test_validate_ontologies_requires_entity_parents(tmp_path):
	"""A concept whose parent is not defined is an error, also when only an intermediate level is missing."""
	errors = _validate(_entities(tmp_path, 'person|teacher', 'place', 'place|room|laboratory'))

	assert len(errors) == 2
	assert _mentions(errors, 'person|teacher', 'person')
	assert _mentions(errors, 'place|room|laboratory', 'place|room')


def test_validate_ontologies_requires_relationship_parents(tmp_path):
	"""A relationship whose parent relationship is not defined is an error."""
	errors = _validate(_entities(tmp_path, 'person', 'project'), _relationships(tmp_path, ('works_on|leads', 'person', 'project')))

	assert len(errors) == 1
	assert _mentions(errors, 'works_on|leads', 'works_on')


def test_validate_ontologies_requires_relationship_types_in_entities(tmp_path):
	"""The src and dst of every relationship must be concepts in entities."""
	errors = _validate(
		_entities(tmp_path, 'person', 'project'),
		_relationships(tmp_path, 
			('drives', 'person', 'vehicle'),
			('owned_by', 'company', 'person'),
			('competes_with', 'company', 'bank')
		)
	)

	assert len(errors) == 4
	assert _mentions(errors, 'drives', 'vehicle')
	assert _mentions(errors, 'owned_by', 'company')
	assert _mentions(errors, 'competes_with', 'company')
	assert _mentions(errors, 'competes_with', 'bank')


def test_validate_ontologies_requires_relationship_src_and_dst(tmp_path):
	"""A relationship that does not declare its src or dst is an error."""
	relationships = _relationships(tmp_path, ('knows', 'person', None), ('likes', None, 'person'), ('meets', None, None))
	errors = _validate(_entities(tmp_path, 'person'), relationships)

	assert len(errors) == 3
	assert _mentions(errors, 'knows')
	assert _mentions(errors, 'likes')
	assert _mentions(errors, 'meets')


def test_validate_ontologies_requires_known_instances_of_existing_concepts(tmp_path):
	"""Every instance in known_ids must be a name under a concept defined in entities."""
	errors = _validate(
		_entities(tmp_path, *SCHOOL_ENTITIES),
		_relationships(tmp_path, *SCHOOL_RELATIONS),
		_known_ids(tmp_path, ['person|student|Noah', 'vehicle|car|Herbie', 'Lonely Name'])
	)

	assert len(errors) == 2
	assert _mentions(errors, 'vehicle|car|Herbie', 'vehicle|car')
	assert _mentions(errors, 'Lonely Name')


def test_validate_ontologies_requires_known_edges_of_existing_relationships(tmp_path):
	"""Every edge in known_ids must have a relation defined in relationships."""
	known = _known_ids(
		tmp_path,
		['person|student|Noah', 'project|Helios'],
		[
			('person|student|Noah', 'project|Helios', 'sponsors', 'noah_sponsors'),
			('person|student|Noah', 'project|Helios', None, 'noah_unknown')
		]
	)
	errors = _validate(_entities(tmp_path, *SCHOOL_ENTITIES), _relationships(tmp_path, *SCHOOL_RELATIONS), known)

	assert len(errors) == 2
	assert _mentions(errors, 'noah_sponsors', 'sponsors')
	assert _mentions(errors, 'noah_unknown')


def test_validate_ontologies_requires_known_edges_of_compatible_types(tmp_path):
	"""The instances connected by an edge must be of the types (or descendants of the types) declared by its relation."""
	known = _known_ids(tmp_path, 
		['person|student|Noah', 'person|teacher|Elena', 'organization|school|Riverside', 'project|Helios'],
		[
			('person|student|Noah', 'organization|school|Riverside', 'teaches_at', 'noah_teaches'),
			('person|teacher|Elena', 'project|Helios', 'teaches_at', 'elena_teaches_helios'),
			('project|Helios', 'person|student|Noah', 'works_on', 'helios_works_on_noah')
		]
	)
	errors = _validate(_entities(tmp_path, *SCHOOL_ENTITIES), _relationships(tmp_path, *SCHOOL_RELATIONS), known)

	assert len(errors) == 4
	assert _mentions(errors, 'noah_teaches', 'person|student|Noah', 'person|teacher')
	assert _mentions(errors, 'elena_teaches_helios', 'project|Helios', 'organization|school')
	assert _mentions(errors, 'helios_works_on_noah', 'project|Helios', 'person')
	assert _mentions(errors, 'helios_works_on_noah', 'person|student|Noah', 'project')


def test_validate_ontologies_does_not_accept_a_prefix_as_a_parent_type(tmp_path):
	"""Type compatibility follows the | hierarchy, not plain string prefixes (person_group is not a person)."""
	known = _known_ids(tmp_path, 
		['person_group|Robotics Team', 'project|Helios'],
		[('person_group|Robotics Team', 'project|Helios', 'works_on', 'team_helios')]
	)
	errors = _validate(_entities(tmp_path, 'person', 'person_group', 'project'), _relationships(tmp_path, ('works_on', 'person', 'project')), known)

	assert len(errors) == 1
	assert _mentions(errors, 'team_helios', 'person_group|Robotics Team', 'person')


def test_validate_ontologies_with_disabled_ontologies(tmp_path):
	"""Disabled relationships or known_ids are skipped, but known_ids edges need relationships to be checked against."""
	assert _validate(_entities(tmp_path, 'person'), None, None) == []
	assert _validate(_entities(tmp_path, 'person'), None, _known_ids(tmp_path, ['person|Noah'])) == []

	errors = _validate(_entities(tmp_path, 'person'), None, _known_ids(tmp_path, ['person|Noah', 'person|Ada'], [('person|Noah', 'person|Ada', 'knows', 'k')]))

	assert len(errors) == 1
	assert _mentions(errors, 'k', 'knows')


def test_validate_ontologies_reports_every_error_at_once(tmp_path):
	"""All the problems are reported together, not just the first one."""
	errors = _validate(
		_entities(tmp_path, 'person|teacher', 'project'),
		_relationships(tmp_path, ('works_on|leads', 'person', 'project')),
		_known_ids(tmp_path, ['vehicle|Herbie'])
	)

	assert len(errors) == 4


def test_validate_ontologies_requires_loaded_ontologies(tmp_path):
	"""Ontologies that have not been piloted cannot be validated and that is the only problem reported."""
	relationships = AgenticGraph(schema = 'relationships', extra_args = {})
	known_ids = AgenticGraph(schema = 'known_ids', extra_args = {})
	errors = _validate(_entities(tmp_path, 'person|teacher'), relationships, known_ids)

	assert len(errors) == 2
	assert _mentions(errors, 'relationships')
	assert _mentions(errors, 'known_ids')


def test_formalizer_pilot_fails_with_invalid_ontologies(monkeypatch, tmp_path):
	"""The Formalizer does not become ready with incoherent ontologies and logs every problem."""
	set_gliner_extractor(monkeypatch, DummyModel)
	DummyModel.fail_loading = False
	formalizer = Formalizer(schema = 'invalid', extra_args = _configuration(), logger = [])
	formalizer.tools['formalizer_invalid/agentic_graph_entities'] = _entities(tmp_path, 'person|teacher')
	formalizer.tools['formalizer_invalid/agentic_graph_relationships'] = _relationships(tmp_path, ('drives', 'person|teacher', 'vehicle'))
	formalizer.tools['formalizer_invalid/agentic_graph_known_ids'] = _known_ids(tmp_path, [])
	formalizer.pilot(FormalizerState.READY.value)

	assert formalizer.meta['state'] == FormalizerState.ERR_ONTOLOGY_INIT.value

	logged = [event['error'] for event in formalizer.logger]

	assert _mentions(logged, 'person|teacher', 'person')
	assert _mentions(logged, 'drives', 'vehicle')


# if __name__ == "__main__":
# 	pytest.main([__file__])
