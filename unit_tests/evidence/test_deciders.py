import logging
import sys
import types

import pytest

from mercury.graph.evidence.decider import MatchNodeRulesDecider
from mercury.graph.evidence.gliner_deciders import ExtractEdgesGliner2Decider, ExtractNodesGliner2Decider
from mercury.graph.evidence.question import Question


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

	def __init__(self, entities = None, structures = None, pairs = None):
		"""Keep what the model finds: entities, structures and (head, tail) pairs, as GLiNER2 returns them with confidence."""
		self.entities	= entities or {}
		self.structures = structures or {}
		self.pairs		= pairs or {}

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
		"""Record the request and return the configured entities."""
		self.extracted = (text, include_confidence)
		return {'entities': self.entities}

	def extract_json(self, text, format, include_confidence = False):
		"""Record the request and return the configured structures."""
		self.json_request = (text, format, include_confidence)
		return self.structures

	def extract_relations(self, text, relations, include_confidence = False):
		"""Record the request and return the configured (head, tail) pairs."""
		self.relations_request = (text, relations, include_confidence)
		return {'relation_extraction': self.pairs}


@pytest.fixture
def gliner(monkeypatch):
	"""Make `from gliner2 import AutoExtractor` return DummyModel, which loads without failing."""
	module = types.ModuleType('gliner2')
	module.AutoExtractor = DummyModel
	monkeypatch.setitem(sys.modules, 'gliner2', module)
	monkeypatch.setattr(DummyModel, 'loaded', [])
	monkeypatch.setattr(DummyModel, 'fail_loading', False)


def _ontology(entities = (), relations = ()):
	"""Return the argument 'ontology' with the given type ids and (id, src, dst) relations, all of them with a definition."""
	concepts = [{'id': index, 'definition': 'Definition of %s.' % index} for index in entities]
	edges	 = [{'id': index, 'src': src, 'dst': dst, 'definition': 'Definition of %s.' % index} for index, src, dst in relations]
	return {'types': concepts, 'relations': edges}


# MatchNodeRulesDecider


def _match(decider, concept, mention, index, texts = ()):
	"""Return the answer of a MatchNodeRulesDecider for a mention of a type, with the given texts, and the id of a known instance."""
	known = {'id': index, 'description': 'Description of %s.' % index, 'names': []}
	arguments = {'mention': {'mention': mention, 'type': concept, 'texts': list(texts)}, 'node': known, 'ontology': _ontology()}
	return decider.run(arguments)


def test_match_node_rules_answers_match_node():
	"""The match_node_rules decider is the Decider of match_node."""
	assert MatchNodeRulesDecider.QUESTION is Question.MATCH_NODE


def test_match_node_rules_scores_the_names_of_nodes_of_the_same_root():
	"""The score is the share of words in common of the names, whatever the branch, and 0 for another root."""
	decider = MatchNodeRulesDecider({})
	assert _match(decider, 'person', 'Elena Ruiz', 'person|teacher|Elena Ruiz')['score'] == 1.0
	assert _match(decider, 'person|teacher', 'Ms. Ruiz', 'person|teacher|Elena Ruiz')['score'] == 0.5
	assert _match(decider, 'person|student', 'Elena Ruiz', 'person|teacher|Elena Ruiz')['score'] == 1.0
	assert _match(decider, 'place', 'Elena Ruiz', 'person|teacher|Elena Ruiz')['score'] == 0
	assert _match(decider, 'person', 'Person', 'person|teacher|Teacher')['score'] == 0


def test_match_node_rules_answers_same_from_its_threshold_on():
	"""A score from "same_node_threshold" on (0.3 by default) is the same node."""
	assert _match(MatchNodeRulesDecider({}), 'person|teacher', 'Ms. Ruiz', 'person|teacher|Elena Ruiz') == {'score': 0.5, 'same': True}
	strict = MatchNodeRulesDecider({'same_node_threshold': 0.6})
	assert _match(strict, 'person|teacher', 'Ms. Ruiz', 'person|teacher|Elena Ruiz') == {'score': 0.5, 'same': False}
	assert _match(MatchNodeRulesDecider({'same_node_threshold': 0.5}), 'person|teacher', 'Ms. Ruiz', 'person|teacher|Elena Ruiz')['same'] is True


def test_match_node_rules_ignores_the_texts():
	"""The texts do not change the answer of the match_node_rules decider."""
	decider = MatchNodeRulesDecider({})
	answer	= _match(decider, 'person|teacher', 'Ms. Ruiz', 'person|teacher|Elena Ruiz')
	assert _match(decider, 'person|teacher', 'Ms. Ruiz', 'person|teacher|Elena Ruiz', ['Ms. Ruiz teaches science.']) == answer


def test_match_node_rules_takes_its_ignored_words():
	"""Without titles to ignore, "Ms." is a word of the name."""
	decider = MatchNodeRulesDecider({'ignored_words': []})
	assert _match(decider, 'person|teacher', 'Ms. Ruiz', 'person|teacher|Elena Ruiz')['score'] == pytest.approx(1/3)


# GLiNER2 Deciders: loading the model


def test_gliner2_deciders_answer_their_questions():
	"""Each GLiNER2 Decider answers its question."""
	assert ExtractNodesGliner2Decider.QUESTION is Question.EXTRACT_NODES
	assert ExtractEdgesGliner2Decider.QUESTION is Question.EXTRACT_EDGES


def test_gliner2_decider_loads_its_model_with_the_options_that_are_not_null(gliner):
	"""ready() loads the model, passing only the options that are not null."""
	decider = ExtractNodesGliner2Decider({'model': 'dummy', 'map_location': 'cpu', 'quantize': True, 'compile': None})
	assert decider.ready() == []
	assert DummyModel.loaded == [('dummy', {'map_location': 'cpu', 'quantize': True})]
	assert type(decider.model) is DummyModel


def test_gliner2_decider_requires_a_model(gliner):
	"""Without "model", the Decider is not ready."""
	assert ExtractEdgesGliner2Decider({}).ready() == ['"model" is missing in the configuration.']


def test_gliner2_decider_requires_gliner2(monkeypatch):
	"""Without GLiNER2 installed, the Decider is not ready."""
	monkeypatch.setitem(sys.modules, 'gliner2', None)
	problems = ExtractNodesGliner2Decider({'model': 'dummy'}).ready()
	assert len(problems) == 1 and 'GLiNER2 is not installed' in problems[0]


def test_gliner2_decider_reports_a_model_that_cannot_be_loaded_and_restores_logging(gliner):
	"""A model that fails to load is a problem, and the logs silenced while loading are restored."""
	DummyModel.fail_loading = True
	previous = logging.root.manager.disable
	problems = ExtractNodesGliner2Decider({'model': 'dummy'}).ready()
	assert problems == ['Failed to load model "dummy": cannot load']
	assert logging.root.manager.disable == previous


# ExtractNodesGliner2Decider


def _found(*matches):
	"""Return GLiNER2 entities with confidence from (type, mention, confidence) triples."""
	entities = {}
	for concept, mention, confidence in matches:
		entities.setdefault(concept, []).append({'text': mention, 'confidence': confidence})
	return entities


def _extract_nodes(found, entities = ('person', 'place')):
	"""Return the ExtractNodesGliner2Decider and its output when its model finds the given entities, with an ontology of the given types."""
	decider = ExtractNodesGliner2Decider({'model': 'dummy'})
	decider.model = DummyModel(entities = found)
	nodes = decider.run({'text': 'Some text.', 'ontology': _ontology(entities)})
	return decider, nodes


def test_extract_nodes_gliner2_asks_the_model_for_the_types_of_the_ontology():
	"""The model is given every type of the ontology, named by its id and described by its definition."""
	decider, nodes = _extract_nodes({})
	assert nodes == []
	assert decider.model.extracted == ('Some text.', True)
	assert decider.model.entity_schema == {'person': 'Definition of person.', 'place': 'Definition of place.'}


def test_extract_nodes_gliner2_returns_one_node_per_mention():
	"""Every mention is a node with its type and confidence, in the order the model found them."""
	found = _found(('person|teacher', 'Elena Ruiz', 0.9), ('organization|school', 'Riverside School', 0.8))
	assert _extract_nodes(found)[1] == [
		{'mention': 'Elena Ruiz', 'type': 'person|teacher', 'confidence': 0.9},
		{'mention': 'Riverside School', 'type': 'organization|school', 'confidence': 0.8}
	]


def test_extract_nodes_gliner2_gives_a_mention_the_most_specific_compatible_type():
	"""A mention found as a type and its ancestor is one node with the most specific type, even if it is less confident."""
	found = _found(('person', 'Ms. Ruiz', 0.95), ('person|teacher', 'Ms. Ruiz', 0.7))
	assert _extract_nodes(found)[1] == [{'mention': 'Ms. Ruiz', 'type': 'person|teacher', 'confidence': 0.7}]


def test_extract_nodes_gliner2_discards_the_types_of_other_branches():
	"""Types that are neither ancestors nor descendants of the most confident one are discarded."""
	found = _found(('person|student', 'Lucas Moreno', 0.98), ('person|teacher', 'Lucas Moreno', 0.99), ('person', 'Lucas Moreno', 0.9))
	assert _extract_nodes(found)[1] == [{'mention': 'Lucas Moreno', 'type': 'person|teacher', 'confidence': 0.99}]


def test_extract_nodes_gliner2_breaks_ties_between_equally_specific_types_by_confidence():
	"""When the most confident type is an ancestor of several equally specific types, the most confident of them is chosen."""
	found = _found(('person', 'Noah', 0.9), ('person|teacher', 'Noah', 0.6), ('person|student', 'Noah', 0.8))
	assert _extract_nodes(found)[1] == [{'mention': 'Noah', 'type': 'person|student', 'confidence': 0.8}]


def test_extract_nodes_gliner2_keeps_the_first_of_equally_specific_and_confident_types():
	"""Between equally specific types with the same confidence, the first one found is chosen."""
	found = _found(('person', 'Noah', 0.9), ('person|teacher', 'Noah', 0.8), ('person|student', 'Noah', 0.8))
	assert _extract_nodes(found)[1] == [{'mention': 'Noah', 'type': 'person|teacher', 'confidence': 0.8}]


def test_extract_nodes_gliner2_keeps_the_highest_confidence_of_a_repeated_mention():
	"""A mention found twice with the same type is one node with the highest confidence."""
	found = _found(('person', 'Noah', 0.6), ('person', 'Noah', 0.8))
	assert _extract_nodes(found)[1] == [{'mention': 'Noah', 'type': 'person', 'confidence': 0.8}]


# ExtractEdgesGliner2Decider


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


def _extract_edges(structures, pairs = None, relations = EDGE_RELATIONS):
	"""Return the ExtractEdgesGliner2Decider and its output on NODES, with the given structures and pairs found by the model."""
	decider = ExtractEdgesGliner2Decider({'model': 'dummy'})
	decider.model = DummyModel(structures = structures, pairs = pairs)
	edges = decider.run({'text': 'Some text.', 'nodes': NODES, 'ontology': _ontology(EDGE_ENTITIES, relations)})
	return decider, edges


def test_extract_edges_gliner2_replaces_the_mentions_by_the_ids_of_the_nodes():
	"""Every source and destination mention of a match is an edge between their ids, with the lowest confidence of both."""
	structures = {'Definition of works_at|teaches_at.': [
		{'person|teacher': [_span('Ms. Ruiz', 0.9)], 'organization|school': [_span('Riverside', 0.7)]}
	]}
	decider, edges = _extract_edges(structures)
	assert edges == [{'src': 'person|teacher|Elena Ruiz', 'relation': 'works_at|teaches_at', 'dst': 'organization|school|Riverside School', 'confidence': 0.7}]
	assert decider.model.json_request == ('Some text.', {
		'Definition of works_at.': ['person', 'organization'], 'Definition of works_at|teaches_at.': ['person|teacher', 'organization|school'],
		'Definition of located_in.': ['place', 'place']
	}, True)


def test_extract_edges_gliner2_only_asks_for_the_relations_of_the_ontology():
	"""A filtered ontology asks only for its relations."""
	decider, _ = _extract_edges({}, relations = (('located_in', 'place', 'place'),))
	assert decider.model.json_request[1] == {'Definition of located_in.': ['place', 'place']}


def test_extract_edges_gliner2_drops_ends_that_are_not_nodes_or_have_no_id():
	"""An end that is not the mention of a node, or that is ambiguous, gives no edge."""
	structures = {'Definition of works_at.': [{'person': [_span('Noah'), _span('Ana')], 'organization': [_span('Riverside')]}]}
	assert _extract_edges(structures)[1] == []


def test_extract_edges_gliner2_requires_ends_of_the_types_of_the_relation():
	"""Ends of descendant types are valid, while those of other types are not (a student does not teach)."""
	structures = {
		'Definition of works_at.': [{'person': [_span('Tom')], 'organization': [_span('Riverside')]}],
		'Definition of works_at|teaches_at.': [{'person|teacher': [_span('Tom')], 'organization|school': [_span('Riverside')]}]
	}
	assert _extract_edges(structures)[1] == [
		{'src': 'person|student|Tom', 'relation': 'works_at', 'dst': 'organization|school|Riverside School', 'confidence': 0.9}
	]


def test_extract_edges_gliner2_keeps_the_highest_confidence_of_a_repeated_edge():
	"""The same edge found twice is one edge with its highest confidence."""
	structures = {'Definition of works_at.': [
		{'person': [_span('Tom', 0.6)], 'organization': [_span('Riverside', 0.6)]},
		{'person': [_span('Tom', 0.8)], 'organization': [_span('Riverside', 0.9)]}
	]}
	assert _extract_edges(structures)[1] == [
		{'src': 'person|student|Tom', 'relation': 'works_at', 'dst': 'organization|school|Riverside School', 'confidence': 0.8}
	]


def test_extract_edges_gliner2_drops_an_edge_when_the_same_pair_has_a_more_specific_one():
	"""works_at is implied by works_at|teaches_at between the same nodes."""
	structures = {
		'Definition of works_at.': [{'person': [_span('Ms. Ruiz')], 'organization': [_span('Riverside')]}],
		'Definition of works_at|teaches_at.': [{'person|teacher': [_span('Ms. Ruiz')], 'organization|school': [_span('Riverside')]}]
	}
	assert [edge['relation'] for edge in _extract_edges(structures)[1]] == ['works_at|teaches_at']


def test_extract_edges_gliner2_asks_for_pairs_of_relations_with_the_same_type_at_both_ends():
	"""The structure of place to place only tells that located_in is in the text: its direction comes from the (head, tail) pairs."""
	structures = {'Definition of located_in.': [{'place': [_span('Rift Valley')]}, {'place': [_span('Africa')]}]}
	pairs = {'located_in': [{'head': _span('Rift Valley', 0.8), 'tail': _span('Africa', 0.8)}]}
	decider, edges = _extract_edges(structures, pairs)
	assert edges == [{'src': 'place|Rift Valley', 'relation': 'located_in', 'dst': 'place|Africa', 'confidence': 0.8}]
	assert decider.model.relations_request == ('Some text.', {'located_in': 'Definition of located_in.'}, True)


def test_extract_edges_gliner2_does_not_ask_for_pairs_when_no_relation_needs_them():
	"""Without mentions of a relation with the same type at both ends, the model is not asked for pairs."""
	decider, edges = _extract_edges({'Definition of located_in.': [{'place': []}]})
	assert edges == []
	assert not hasattr(decider.model, 'relations_request')
