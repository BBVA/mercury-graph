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
	structures = {}
	pairs = {}

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

	def extract_json(self, text, format, include_confidence = False):
		"""Record the request and return the configured structures, as GLiNER2 does with include_confidence."""
		self.json_request = (text, format, include_confidence)
		return DummyModel.structures

	def extract_relations(self, text, relations, include_confidence = False):
		"""Record the request and return the configured (head, tail) pairs, as GLiNER2 does with include_confidence."""
		self.relations_request = (text, relations, include_confidence)
		return {'relation_extraction': DummyModel.pairs}


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


def _ready_formalizer(monkeypatch, directory, entities = ('person', 'place'), relations = (('located', 'person', 'place'),)):
	"""Build a ready Formalizer with a deterministic model and an ontology (by default, two entities and one relationship)."""
	set_gliner_extractor(monkeypatch, DummyModel)
	DummyModel.loaded = []
	DummyModel.fail_loading = False
	DummyModel.entities = {}
	DummyModel.structures = {}
	DummyModel.pairs = {}
	formalizer = Formalizer(schema = 'test', extra_args = _configuration())
	formalizer.tools['formalizer_test/agentic_graph_ontology'] = _multigraph(directory, entities, relations)
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
	assert [capability['function']['name'] for capability in formalizer.meta['capabilities']] == ['hint_nodes_test', 'hint_edges_test', 'is_same_node_test']


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


def test_formalizer_hint_nodes_and_edges(monkeypatch, tmp_path):
	"""Exercise ready-state extraction with every concepts selection path."""
	formalizer = _ready_formalizer(monkeypatch, tmp_path)
	assert formalizer.hint_nodes({'text': 'Ada'}) == []
	assert formalizer._model.extracted == ('Ada', True)
	assert formalizer._model.entity_schema == {'person': 'Definition of person.', 'place': 'Definition of place.'}
	formalizer.hint_nodes({'text': 'Ada', 'concepts': ['person', 'missing']})
	assert formalizer._model.entity_schema == {'person': 'Definition of person.', 'missing': ''}
	assert formalizer.hint_edges({'text': 'Ada lives here', 'nodes': []}) == []
	assert formalizer._model.json_request == ('Ada lives here', {'Definition of located.': ['person', 'place']}, True)
	formalizer.hint_edges({'text': 'Ada lives here', 'nodes': [], 'concepts': []})
	assert formalizer._model.json_request[1] == {}
	formalizer.hint_edges({'text': 'Ada lives here', 'nodes': [], 'concepts': ['located']})
	assert formalizer._model.json_request[1] == {'Definition of located.': ['person', 'place']}
	assert formalizer.run({'name': 'hint_nodes_test', 'arguments': {'text': 'Ada'}})['finish_reason'] == 'stop'


def _found(*matches):
	"""Return GLiNER2 entities with confidence from (type, mention, confidence) triples."""
	entities = {}
	for concept, mention, confidence in matches:
		entities.setdefault(concept, []).append({'text': mention, 'confidence': confidence})
	return entities


def _hint_nodes(monkeypatch, directory, found, candidates = None, **conf):
	"""Return the output of hint_nodes on a ready Formalizer whose model finds the given entities, optionally given candidates."""
	formalizer = _ready_formalizer(monkeypatch, directory)
	formalizer.conf.update(conf)
	DummyModel.entities = found
	arguments = {'text': 'Some text.'}
	if candidates is not None:
		arguments['candidates'] = candidates
	return formalizer.hint_nodes(arguments)


def test_hint_nodes_returns_one_node_per_mention(monkeypatch, tmp_path):
	"""Every mention is a node with its type and confidence, in the order the model found them, and no candidates if none are given."""
	found = _found(('person|teacher', 'Elena Ruiz', 0.9), ('organization|school', 'Riverside School', 0.8))
	assert _hint_nodes(monkeypatch, tmp_path, found) == [
		{'mention': 'Elena Ruiz', 'type': 'person|teacher', 'confidence': 0.9, 'candidates': []},
		{'mention': 'Riverside School', 'type': 'organization|school', 'confidence': 0.8, 'candidates': []}
	]


def test_hint_nodes_gives_a_mention_the_most_specific_compatible_type(monkeypatch, tmp_path):
	"""A mention found as a type and its ancestor is one node with the most specific type, even if it is less confident."""
	found = _found(('person', 'Ms. Ruiz', 0.95), ('person|teacher', 'Ms. Ruiz', 0.7))
	assert _hint_nodes(monkeypatch, tmp_path, found) == [{'mention': 'Ms. Ruiz', 'type': 'person|teacher', 'confidence': 0.7, 'candidates': []}]


def test_hint_nodes_discards_the_types_of_other_branches(monkeypatch, tmp_path):
	"""Types that are neither ancestors nor descendants of the most confident one are discarded."""
	found = _found(('person|student', 'Lucas Moreno', 0.98), ('person|teacher', 'Lucas Moreno', 0.99), ('person', 'Lucas Moreno', 0.9))
	assert _hint_nodes(monkeypatch, tmp_path, found) == [
		{'mention': 'Lucas Moreno', 'type': 'person|teacher', 'confidence': 0.99, 'candidates': []}
	]


def test_hint_nodes_breaks_ties_between_equally_specific_types_by_confidence(monkeypatch, tmp_path):
	"""When the most confident type is an ancestor of several equally specific types, the most confident of them is chosen."""
	found = _found(('person', 'Noah', 0.9), ('person|teacher', 'Noah', 0.6), ('person|student', 'Noah', 0.8))
	assert _hint_nodes(monkeypatch, tmp_path, found) == [{'mention': 'Noah', 'type': 'person|student', 'confidence': 0.8, 'candidates': []}]


def test_hint_nodes_keeps_the_highest_confidence_of_a_repeated_mention(monkeypatch, tmp_path):
	"""A mention found twice with the same type is one node with the highest confidence."""
	found = _found(('person', 'Noah', 0.6), ('person', 'Noah', 0.8))
	assert _hint_nodes(monkeypatch, tmp_path, found) == [{'mention': 'Noah', 'type': 'person', 'confidence': 0.8, 'candidates': []}]


KNOWN = ['person|teacher|Elena Ruiz', 'organization|school|Riverside School', 'person|student|Noah Kim', 'person|teacher|Noah Brown',
		 'project|Helios Solar Car']


def _candidates_of(monkeypatch, directory, concept, mention, candidates = KNOWN, **conf):
	"""Return the candidates hint_nodes gives to a single mention of a type."""
	nodes = _hint_nodes(monkeypatch, directory, _found((concept, mention, 0.9)), candidates, **conf)
	assert len(nodes) == 1
	return nodes[0]['candidates']


def test_hint_nodes_gives_known_mentions_their_candidates(monkeypatch, tmp_path):
	"""Case 2: the mentions of known instances, found with their types, have them as candidates with score 1."""
	found = _found(('person|teacher', 'Elena Ruiz', 0.9), ('organization|school', 'Riverside School', 0.8))
	assert _hint_nodes(monkeypatch, tmp_path, found, KNOWN) == [
		{'mention': 'Elena Ruiz', 'type': 'person|teacher', 'confidence': 0.9, 'candidates': [{'id': 'person|teacher|Elena Ruiz', 'score': 1.0}]},
		{'mention': 'Riverside School', 'type': 'organization|school', 'confidence': 0.8,
		 'candidates': [{'id': 'organization|school|Riverside School', 'score': 1.0}]}
	]


def test_hint_nodes_accepts_ancestors_and_descendants_of_the_known_type(monkeypatch, tmp_path):
	"""Case 3: a mention found with an ancestor of the known type is not a conflict, nor is one found with a descendant."""
	assert _candidates_of(monkeypatch, tmp_path, 'person', 'Elena Ruiz') == [{'id': 'person|teacher|Elena Ruiz', 'score': 1.0}]
	assert _candidates_of(monkeypatch, tmp_path, 'person|teacher|science', 'Elena Ruiz') == [{'id': 'person|teacher|Elena Ruiz', 'score': 1.0}]


def test_hint_nodes_reports_a_type_conflict_with_a_candidate_of_another_branch(monkeypatch, tmp_path):
	"""Case 4: a mention found with a type of another branch of the same root keeps the candidate, with type_conflict."""
	assert _candidates_of(monkeypatch, tmp_path, 'person|student', 'Elena Ruiz') == [
		{'id': 'person|teacher|Elena Ruiz', 'score': 1.0, 'type_conflict': True}
	]


def test_hint_nodes_scores_a_partial_name_by_the_share_of_words_in_common(monkeypatch, tmp_path):
	"""Case 5: titles are ignored, so "Ms. Ruiz" shares one of the two words of "Elena Ruiz"."""
	assert _candidates_of(monkeypatch, tmp_path, 'person|teacher', 'Ms. Ruiz') == [{'id': 'person|teacher|Elena Ruiz', 'score': 0.5}]
	assert _candidates_of(monkeypatch, tmp_path, 'person|teacher', 'Ms. Ruiz', ignored_words = []) == [
		{'id': 'person|teacher|Elena Ruiz', 'score': pytest.approx(1/3)}
	]


def test_hint_nodes_gives_every_candidate_that_shares_a_word_from_the_highest_score(monkeypatch, tmp_path):
	"""A first name shared by two known instances gives both, and a full name ranks its own instance first."""
	assert _candidates_of(monkeypatch, tmp_path, 'person', 'Noah') == [
		{'id': 'person|student|Noah Kim', 'score': 0.5}, {'id': 'person|teacher|Noah Brown', 'score': 0.5}
	]
	assert _candidates_of(monkeypatch, tmp_path, 'person|teacher', 'Noah Brown') == [
		{'id': 'person|teacher|Noah Brown', 'score': 1.0}, {'id': 'person|student|Noah Kim', 'score': pytest.approx(1/3), 'type_conflict': True}
	]


def test_hint_nodes_leaves_out_the_words_of_the_types(monkeypatch, tmp_path):
	"""The words of the types are generic: "Helios project" shares only "helios" and "the school" names no school."""
	assert _candidates_of(monkeypatch, tmp_path, 'project', 'Helios project') == [{'id': 'project|Helios Solar Car', 'score': pytest.approx(1/3)}]
	assert _candidates_of(monkeypatch, tmp_path, 'organization|school', 'the school') == []


def test_hint_nodes_compares_names_without_case_accents_or_possessives(monkeypatch, tmp_path):
	"""Case, accents and possessives do not change the words of a name."""
	assert _candidates_of(monkeypatch, tmp_path, 'person', "ELENA RUÍZ's") == [{'id': 'person|teacher|Elena Ruiz', 'score': 1.0}]


def test_hint_nodes_only_gives_candidates_of_the_same_root_type(monkeypatch, tmp_path):
	"""A known instance of another root type is not a candidate, even with the same name, nor is an id without a type."""
	assert _candidates_of(monkeypatch, tmp_path, 'place', 'Riverside School', KNOWN + ['Riverside School']) == []


def _is_same_node(formalizer, index, other, texts = ()):
	"""Return the score of is_same_node for two ids, the first one with the given texts."""
	return formalizer.is_same_node({'node': {'id': index, 'texts': list(texts)}, 'other': {'id': other}})


def test_is_same_node_scores_the_names_of_nodes_of_the_same_root(monkeypatch, tmp_path):
	"""The score is the share of words in common of the names, whatever the branch, and 0 for another root type."""
	formalizer = _ready_formalizer(monkeypatch, tmp_path)
	assert _is_same_node(formalizer, 'person|Elena Ruiz', 'person|teacher|Elena Ruiz') == 1.0
	assert _is_same_node(formalizer, 'person|teacher|Ms. Ruiz', 'person|teacher|Elena Ruiz') == 0.5
	assert _is_same_node(formalizer, 'person|student|Elena Ruiz', 'person|teacher|Elena Ruiz') == 1.0
	assert _is_same_node(formalizer, 'place|Elena Ruiz', 'person|teacher|Elena Ruiz') == 0


def test_is_same_node_is_symmetric_and_ignores_the_texts(monkeypatch, tmp_path):
	"""Swapping the nodes gives the same score, and the texts do not change it in this Formalizer."""
	formalizer = _ready_formalizer(monkeypatch, tmp_path)
	score = _is_same_node(formalizer, 'person|teacher|Ms. Ruiz', 'person|teacher|Elena Ruiz')
	assert _is_same_node(formalizer, 'person|teacher|Elena Ruiz', 'person|teacher|Ms. Ruiz') == score
	assert _is_same_node(formalizer, 'person|teacher|Ms. Ruiz', 'person|teacher|Elena Ruiz', ['Ms. Ruiz teaches science.']) == score


def test_is_same_node_is_a_capability(monkeypatch, tmp_path):
	"""is_same_node can be run by its capability name."""
	formalizer = _ready_formalizer(monkeypatch, tmp_path)
	arguments  = {'node': {'id': 'person|Ada'}, 'other': {'id': 'person|Ada Lovelace'}}
	assert formalizer.run({'name': 'is_same_node_test', 'arguments': arguments}) == {'finish_reason': 'stop', 'message': 0.5}


def _link(monkeypatch, directory, concept, mention, candidates = KNOWN, **conf):
	"""Return the decision of link_mention for a single mention of a type found by the model."""
	formalizer = _ready_formalizer(monkeypatch, directory)
	formalizer.conf.update(conf)
	DummyModel.entities = _found((concept, mention, 0.9))
	nodes = formalizer.hint_nodes({'text': 'Some text.', 'candidates': candidates})
	return formalizer.link_mention(nodes[0], 'Some text.')


def test_link_mention_creates_a_mention_with_no_candidates(monkeypatch, tmp_path):
	"""Case 1: with no known instances, the mention is new, with its type followed by the mention as id."""
	assert _link(monkeypatch, tmp_path, 'person|teacher', 'Elena Ruiz', []) == {
		'mention': 'Elena Ruiz', 'id': 'person|teacher|Elena Ruiz', 'status': 'new'
	}


def test_link_mention_links_the_whole_name_of_a_known_instance(monkeypatch, tmp_path):
	"""Cases 2 and 3: the whole name of a known instance is that instance, found with its type or an ancestor."""
	expected = {'mention': 'Elena Ruiz', 'id': 'person|teacher|Elena Ruiz', 'status': 'known'}
	assert _link(monkeypatch, tmp_path, 'person|teacher', 'Elena Ruiz') == expected
	assert _link(monkeypatch, tmp_path, 'person', 'Elena Ruiz') == expected


def test_link_mention_links_the_whole_name_despite_a_type_conflict(monkeypatch, tmp_path):
	"""Case 4: the whole name with a type of another branch is the known instance, with type_conflict."""
	assert _link(monkeypatch, tmp_path, 'person|student', 'Elena Ruiz') == {
		'mention': 'Elena Ruiz', 'id': 'person|teacher|Elena Ruiz', 'status': 'known', 'type_conflict': True
	}


def test_link_mention_links_a_partial_name_from_the_threshold_on(monkeypatch, tmp_path):
	"""Case 5: a partial name is linked if is_same_node scores it from the threshold on, and new otherwise."""
	assert _link(monkeypatch, tmp_path, 'person|teacher', 'Ms. Ruiz') == {'mention': 'Ms. Ruiz', 'id': 'person|teacher|Elena Ruiz', 'status': 'known'}
	assert _link(monkeypatch, tmp_path, 'person|teacher', 'Ms. Ruiz', same_node_threshold = 0.6) == {
		'mention': 'Ms. Ruiz', 'id': 'person|teacher|Ms. Ruiz', 'status': 'new'
	}


def test_link_mention_reports_a_mention_of_several_instances_as_ambiguous(monkeypatch, tmp_path):
	"""A first name of two known instances is ambiguous, and so is the whole name of two homonyms."""
	assert _link(monkeypatch, tmp_path, 'person', 'Noah') == {
		'mention': 'Noah', 'id': None, 'status': 'ambiguous', 'candidates': ['person|student|Noah Kim', 'person|teacher|Noah Brown']
	}
	homonyms = KNOWN + ['person|student|Elena Ruiz']
	assert _link(monkeypatch, tmp_path, 'person', 'Elena Ruiz', homonyms) == {
		'mention': 'Elena Ruiz', 'id': None, 'status': 'ambiguous', 'candidates': ['person|teacher|Elena Ruiz', 'person|student|Elena Ruiz']
	}


def test_link_mention_discards_partial_names_with_a_type_conflict(monkeypatch, tmp_path):
	"""A partial name with a type of another branch is not enough: "Noah" as a principal is a new principal."""
	assert _link(monkeypatch, tmp_path, 'person|principal', 'Noah') == {'mention': 'Noah', 'id': 'person|principal|Noah', 'status': 'new'}


def test_link_mention_prefers_the_only_whole_name(monkeypatch, tmp_path):
	"""A whole name is the instance even if other candidates share some of its words."""
	assert _link(monkeypatch, tmp_path, 'person|teacher', 'Noah Brown') == {
		'mention': 'Noah Brown', 'id': 'person|teacher|Noah Brown', 'status': 'known'
	}


EDGE_ENTITIES  = ('person', 'person|teacher', 'person|student', 'organization', 'organization|school', 'place')
EDGE_RELATIONS = (('works_at', 'person', 'organization'), ('works_at|teaches_at', 'person|teacher', 'organization|school'),
				  ('located_in', 'place', 'place'))

NODES = [
	{'mention': 'Ms. Ruiz', 'id': 'person|teacher|Elena Ruiz', 'status': 'known'},
	{'mention': 'Tom', 'id': 'person|student|Tom', 'status': 'new'},
	{'mention': 'Riverside', 'id': 'organization|school|Riverside School', 'status': 'known'},
	{'mention': 'Noah', 'id': None, 'status': 'ambiguous', 'candidates': ['person|student|Noah Kim', 'person|teacher|Noah Brown']},
	{'mention': 'Rift Valley', 'id': 'place|Rift Valley', 'status': 'new'},
	{'mention': 'Africa', 'id': 'place|Africa', 'status': 'known'}
]


def _span(text, confidence = 0.9):
	"""Return a span of GLiNER2 with confidence."""
	return {'text': text, 'confidence': confidence}


def _hint_edges(monkeypatch, directory, structures, pairs = None, **arguments):
	"""Return the formalizer and the output of hint_edges on NODES, with the given structures and pairs found by the model."""
	formalizer = _ready_formalizer(monkeypatch, directory, EDGE_ENTITIES, EDGE_RELATIONS)
	DummyModel.structures = structures
	DummyModel.pairs = pairs or {}
	arguments = {'text': 'Some text.', 'nodes': NODES, **arguments}
	return formalizer, formalizer.hint_edges(arguments)


def test_hint_edges_replaces_the_mentions_by_the_ids_of_the_nodes(monkeypatch, tmp_path):
	"""Every source and destination mention of a match is an edge between their ids, with the lowest confidence of both."""
	structures = {'Definition of works_at|teaches_at.': [
		{'person|teacher': [_span('Ms. Ruiz', 0.9)], 'organization|school': [_span('Riverside', 0.7)]}
	]}
	formalizer, edges = _hint_edges(monkeypatch, tmp_path, structures)
	assert edges == [{'src': 'person|teacher|Elena Ruiz', 'relation': 'works_at|teaches_at', 'dst': 'organization|school|Riverside School', 'confidence': 0.7}]
	assert formalizer._model.json_request[1] == {
		'Definition of works_at.': ['person', 'organization'], 'Definition of works_at|teaches_at.': ['person|teacher', 'organization|school'],
		'Definition of located_in.': ['place', 'place']
	}


def test_hint_edges_drops_ends_that_are_not_nodes_or_have_no_id(monkeypatch, tmp_path):
	"""An end that is not the mention of a node, or that is ambiguous, gives no edge."""
	structures = {'Definition of works_at.': [{'person': [_span('Noah'), _span('Ana')], 'organization': [_span('Riverside')]}]}
	assert _hint_edges(monkeypatch, tmp_path, structures)[1] == []


def test_hint_edges_requires_ends_of_the_types_of_the_relationship(monkeypatch, tmp_path):
	"""Ends of descendant types are valid, while those of other types are not (a student does not teach)."""
	structures = {
		'Definition of works_at.': [{'person': [_span('Tom')], 'organization': [_span('Riverside')]}],
		'Definition of works_at|teaches_at.': [{'person|teacher': [_span('Tom')], 'organization|school': [_span('Riverside')]}]
	}
	assert _hint_edges(monkeypatch, tmp_path, structures)[1] == [
		{'src': 'person|student|Tom', 'relation': 'works_at', 'dst': 'organization|school|Riverside School', 'confidence': 0.9}
	]


def test_hint_edges_keeps_the_highest_confidence_of_a_repeated_edge(monkeypatch, tmp_path):
	"""The same edge found twice is one edge with its highest confidence."""
	structures = {'Definition of works_at.': [
		{'person': [_span('Tom', 0.6)], 'organization': [_span('Riverside', 0.6)]},
		{'person': [_span('Tom', 0.8)], 'organization': [_span('Riverside', 0.9)]}
	]}
	assert _hint_edges(monkeypatch, tmp_path, structures)[1] == [
		{'src': 'person|student|Tom', 'relation': 'works_at', 'dst': 'organization|school|Riverside School', 'confidence': 0.8}
	]


def test_hint_edges_drops_an_edge_when_the_same_pair_has_a_more_specific_one(monkeypatch, tmp_path):
	"""works_at is implied by works_at|teaches_at between the same nodes."""
	structures = {
		'Definition of works_at.': [{'person': [_span('Ms. Ruiz')], 'organization': [_span('Riverside')]}],
		'Definition of works_at|teaches_at.': [{'person|teacher': [_span('Ms. Ruiz')], 'organization|school': [_span('Riverside')]}]
	}
	assert [edge['relation'] for edge in _hint_edges(monkeypatch, tmp_path, structures)[1]] == ['works_at|teaches_at']


def test_hint_edges_asks_for_pairs_of_relationships_with_the_same_type_at_both_ends(monkeypatch, tmp_path):
	"""The structure of place to place only tells that located_in is in the text: its direction comes from the (head, tail) pairs."""
	structures = {'Definition of located_in.': [{'place': [_span('Rift Valley')]}, {'place': [_span('Africa')]}]}
	pairs = {'located_in': [{'head': _span('Rift Valley', 0.8), 'tail': _span('Africa', 0.8)}]}
	formalizer, edges = _hint_edges(monkeypatch, tmp_path, structures, pairs)
	assert edges == [{'src': 'place|Rift Valley', 'relation': 'located_in', 'dst': 'place|Africa', 'confidence': 0.8}]
	assert formalizer._model.relations_request == ('Some text.', {'located_in': 'Definition of located_in.'}, True)


def test_hint_edges_does_not_ask_for_pairs_when_no_relationship_needs_them(monkeypatch, tmp_path):
	"""Without mentions of a relationship with the same type at both ends, the model is not asked for pairs."""
	formalizer, edges = _hint_edges(monkeypatch, tmp_path, {'Definition of located_in.': [{'place': []}]})
	assert edges == []
	assert not hasattr(formalizer._model, 'relations_request')


def test_hint_edges_finds_new_nodes_when_it_is_not_given_any(monkeypatch, tmp_path):
	"""Without nodes, those found by hint_nodes in the text are the ends, all of them new (as for an Agent using it as a tool)."""
	formalizer = _ready_formalizer(monkeypatch, tmp_path, EDGE_ENTITIES, EDGE_RELATIONS)
	DummyModel.entities = _found(('person|teacher', 'Ms. Ruiz', 0.9), ('organization|school', 'Riverside', 0.8))
	DummyModel.structures = {'Definition of works_at|teaches_at.': [
		{'person|teacher': [_span('Ms. Ruiz', 0.9)], 'organization|school': [_span('Riverside', 0.8)]}
	]}
	assert formalizer.hint_edges({'text': 'Ms. Ruiz teaches at Riverside.'}) == [
		{'src': 'person|teacher|Ms. Ruiz', 'relation': 'works_at|teaches_at', 'dst': 'organization|school|Riverside', 'confidence': 0.8}
	]


def test_hint_edges_only_asks_for_the_given_relationships(monkeypatch, tmp_path):
	"""With concepts, only those relationships are asked for."""
	formalizer, _ = _hint_edges(monkeypatch, tmp_path, {}, concepts = ['located_in'])
	assert formalizer._model.json_request[1] == {'Definition of located_in.': ['place', 'place']}


def test_formalizer_request_state_errors_and_close():
	"""Cover unavailable request handling, logging, and resource cleanup."""
	formalizer = Formalizer(schema = 'errors', extra_args = _configuration(), logger = [])
	assert formalizer.hint_nodes({'text': 'Ada'}) is None
	assert formalizer.hint_edges({'text': 'Ada'}) is None
	assert formalizer.is_same_node({}) is None
	formalizer._meta_['state'] = FormalizerState.READY.value
	assert formalizer.hint_nodes({}) is None
	assert formalizer.hint_edges({}) is None
	assert formalizer.is_same_node({'node': {'id': 'person|Ada'}}) is None
	formalizer._ontology = object()
	formalizer._model = object()
	formalizer.close(False)
	assert formalizer._ontology is None
	assert formalizer._model is None
	assert len(formalizer.logger) == 6


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
