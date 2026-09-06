import importlib
import sys

import networkx as nx
import pytest

import mercury.graph.evidence.formalizer as formalizer_module

from mercury.graph.evidence import Formalizer
from mercury.graph.evidence.agentic import AgenticRunInvalidRequest
from mercury.graph.evidence.formalizer import FormalizerState


class DummyOntology:
	"""Provide the graph shape consumed by Formalizer ontology operations."""

	def __init__(self, nodes):
		"""Create an ontology containing nodes keyed by their identifiers."""
		self._graph = type('GraphHolder', (), {})()
		self._graph.networkx = nx.DiGraph()
		for identifier, attributes in nodes.items():
			self._graph.networkx.add_node(identifier, **attributes)


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


def _configuration(**extra):
	"""Return a complete Formalizer configuration, optionally extended by extra."""
	conf = {
		'description': ['Extract', 'evidence'],
		'model': {'library': 'gliner2', 'model': 'dummy', 'map_location': 'cpu', 'quantize': True, 'compile': False},
	}
	conf.update(extra)
	return conf


def _ready_formalizer(monkeypatch, include_relation = True, include_known_id = True):
	"""Build a ready Formalizer with deterministic model and ontology tools."""
	monkeypatch.setattr(formalizer_module, 'AutoExtractor', DummyModel)
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
	entities = DummyOntology({'person': {'definition': 'A person'}, 'place': {'definition': 'A place'}})
	relations = DummyOntology({'located': {'src': 'person', 'dest': 'place', 'definition': 'is located in'}})
	formalizer.tools['formalizer_test/agentic_graph_entities'] = entities
	if include_relation:
		formalizer.tools['formalizer_test/agentic_graph_relationships'] = relations
	if include_known_id:
		formalizer.tools['formalizer_test/agentic_graph_known_ids'] = DummyOntology({})
	formalizer.pilot(FormalizerState.READY.value)
	return formalizer


def test_formalizer_initialization_and_calls():
	"""Exercise initial metadata, capability registration, and invalid calls."""
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

	monkeypatch.setattr(formalizer_module, 'AutoExtractor', DummyModel)
	DummyModel.fail_loading = True
	failed = Formalizer(schema = 'failed', extra_args = _configuration(), logger = [])
	failed.pilot(100)
	assert failed.meta['state'] == FormalizerState.ERR_MODEL_INIT.value
	failed.pilot(100)
	assert len(failed.logger) == 2


def test_formalizer_pilot_ontology_outcomes(monkeypatch):
	"""Cover stepwise piloting and all ontology configuration failures."""
	monkeypatch.setattr(formalizer_module, 'AutoExtractor', DummyModel)
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


def test_formalizer_pilot_ready_and_optional_capabilities(monkeypatch):
	"""Make the Formalizer ready and remove unavailable optional capabilities."""
	formalizer = _ready_formalizer(monkeypatch, include_relation = False, include_known_id = False)
	assert formalizer.meta['state'] == FormalizerState.READY.value
	assert DummyModel.loaded == [('dummy', {'map_location': 'cpu', 'quantize': True, 'compile': False})]
	assert [capability['function']['name'] for capability in formalizer.meta['capabilities']] == ['hint_nodes_test']


def test_formalizer_pilot_just_once_reaches_each_stage(monkeypatch):
	"""Stop after model, ontology, and ready transitions when requested."""
	monkeypatch.setattr(formalizer_module, 'AutoExtractor', DummyModel)
	DummyModel.fail_loading = False
	formalizer = Formalizer(schema = 'staged', extra_args = _configuration())
	formalizer.tools['formalizer_staged/agentic_graph_entities'] = DummyOntology({})
	formalizer.tools['formalizer_staged/agentic_graph_relationships'] = DummyOntology({})
	formalizer.tools['formalizer_staged/agentic_graph_known_ids'] = DummyOntology({})
	formalizer.pilot(FormalizerState.READY.value, just_once = True)
	assert formalizer.meta['state'] == FormalizerState.MODEL_LOADED_OK.value
	formalizer.pilot(FormalizerState.READY.value, just_once = True)
	assert formalizer.meta['state'] == FormalizerState.ONTOLOGY_LOADED_OK.value
	formalizer.pilot(FormalizerState.READY.value, just_once = True)
	assert formalizer.meta['state'] == FormalizerState.READY.value


def test_formalizer_hint_nodes_edges_and_is_a(monkeypatch):
	"""Exercise ready-state extraction with every concepts selection path."""
	formalizer = _ready_formalizer(monkeypatch)
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
	"""Cover the optional GLiNER import fallback without changing its environment."""
	with monkeypatch.context() as context:
		context.setitem(sys.modules, 'gliner2', None)
		importlib.reload(formalizer_module)
		assert formalizer_module.AutoExtractor is None
	importlib.reload(formalizer_module)


# if __name__ == "__main__":
# 	pytest.main([__file__])
