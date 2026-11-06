import pandas as pd
import pytest

from mercury.graph.evidence import AgenticGraph, Formalizer
from mercury.graph.evidence.decider import Decider
from mercury.graph.evidence.formalizer import DECIDERS, FormalizerState
from mercury.graph.evidence.linking import find_candidates, link_mention, ontology_argument
from mercury.graph.evidence.question import Question


ONTOLOGY = {'types': [], 'relations': []}

KNOWN = ['person|teacher|Elena Ruiz', 'organization|school|Riverside School', 'person|student|Noah Kim', 'person|teacher|Noah Brown',
		 'project|Helios Solar Car']


def _known_nodes(ids):
	"""Return the known instances of the given ids, each one described as "Description of <id>."."""
	return [{'id': index, 'description': 'Description of %s.' % index} for index in ids]


def _node(concept, mention):
	"""Return a node as extract_nodes returns it."""
	return {'mention': mention, 'type': concept, 'confidence': 0.9}


# ontology_argument


def test_ontology_argument_lists_the_types_and_relations_in_order(tmp_path):
	"""The ontology becomes its types and relations, in the order of its nodes and edges, with an empty missing definition."""
	nodes = pd.DataFrame({'id': ['person', 'project', 'place'], 'definition': ['A person.', 'A project.', None]})
	edges = pd.DataFrame({'id': ['works_on'], 'src': ['person'], 'dst': ['project'], 'definition': ['To work on.']})
	nodes.to_csv(tmp_path / 'nodes.csv', sep = '\t', index = False)
	edges.to_csv(tmp_path / 'edges.csv', sep = '\t', index = False)
	ontology = AgenticGraph(schema = 'ontology', extra_args = {
		'nodes': {'type': 'csv', 'path': str(tmp_path / 'nodes.csv')},
		'edges': {'type': 'csv', 'path': str(tmp_path / 'edges.csv')}})
	ontology.pilot(ontology.states.READY.value)

	argument = ontology_argument(ontology)

	assert [concept['id'] for concept in argument['types']] == ['person', 'project', 'place']
	assert argument['types'][0] == {'id': 'person', 'definition': 'A person.'}
	assert argument['relations'] == [{'id': 'works_on', 'src': 'person', 'dst': 'project', 'definition': 'To work on.'}]


# find_candidates


def _scores(candidates):
	"""Return the candidates without their description and names, to compare only their ids and scores."""
	result = []
	for candidate in candidates:
		scored = dict(candidate)
		del scored['description'], scored['names']
		result.append(scored)
	return result


def _candidates_of(concept, mention, known = KNOWN, **arguments):
	"""Return the ids and scores of the candidates of a mention of a type among the known instances."""
	candidates = find_candidates(_node(concept, mention), _known_nodes(known), **arguments)
	return _scores(candidates)


def test_find_candidates_gives_known_mentions_their_instance_with_its_description_and_names():
	"""The whole name of a known instance has it as candidate with score 1, its description and its names (empty if it has none)."""
	assert find_candidates(_node('person|teacher', 'Elena Ruiz'), _known_nodes(KNOWN)) == [
		{'id': 'person|teacher|Elena Ruiz', 'score': 1.0, 'description': 'Description of person|teacher|Elena Ruiz.', 'names': []}
	]
	known = [{'id': 'person|teacher|Elena Ruiz', 'description': 'A teacher.', 'names': ['Ms. Ruiz']}]
	assert find_candidates(_node('person|teacher', 'Elena Ruiz'), known)[0]['names'] == ['Ms. Ruiz']


def test_find_candidates_accepts_ancestors_and_descendants_of_the_known_type():
	"""A mention found with an ancestor of the known type is not a conflict, nor is one found with a descendant."""
	assert _candidates_of('person', 'Elena Ruiz') == [{'id': 'person|teacher|Elena Ruiz', 'score': 1.0}]
	assert _candidates_of('person|teacher|science', 'Elena Ruiz') == [{'id': 'person|teacher|Elena Ruiz', 'score': 1.0}]


def test_find_candidates_reports_a_type_conflict_with_a_candidate_of_another_branch():
	"""A mention found with a type of another branch of the same root keeps the candidate, with type_conflict."""
	assert _candidates_of('person|student', 'Elena Ruiz') == [{'id': 'person|teacher|Elena Ruiz', 'score': 1.0, 'type_conflict': True}]


def test_find_candidates_scores_a_partial_name_by_the_share_of_words_in_common():
	"""Titles are ignored, so "Ms. Ruiz" shares one of the two words of "Elena Ruiz"; without ignored words, it shares one of three."""
	assert _candidates_of('person|teacher', 'Ms. Ruiz') == [{'id': 'person|teacher|Elena Ruiz', 'score': 0.5}]
	assert _candidates_of('person|teacher', 'Ms. Ruiz', ignored_words = []) == [{'id': 'person|teacher|Elena Ruiz', 'score': pytest.approx(1/3)}]


def test_find_candidates_gives_every_candidate_that_shares_a_word_from_the_highest_score():
	"""A first name shared by two known instances gives both, and a full name ranks its own instance first."""
	assert _candidates_of('person', 'Noah') == [{'id': 'person|student|Noah Kim', 'score': 0.5}, {'id': 'person|teacher|Noah Brown', 'score': 0.5}]
	assert _candidates_of('person|teacher', 'Noah Brown') == [
		{'id': 'person|teacher|Noah Brown', 'score': 1.0}, {'id': 'person|student|Noah Kim', 'score': pytest.approx(1/3), 'type_conflict': True}
	]


def test_find_candidates_leaves_out_the_words_of_the_types():
	"""The words of the types are generic: "Helios project" shares only "helios" and "the school" names no school."""
	assert _candidates_of('project', 'Helios project') == [{'id': 'project|Helios Solar Car', 'score': pytest.approx(1/3)}]
	assert _candidates_of('organization|school', 'the school') == []


def test_find_candidates_compares_names_without_case_accents_or_possessives():
	"""Case, accents and possessives do not change the words of a name."""
	assert _candidates_of('person', "ELENA RUÍZ's") == [{'id': 'person|teacher|Elena Ruiz', 'score': 1.0}]


def test_find_candidates_only_gives_candidates_of_the_same_root_type():
	"""A known instance of another root type is not a candidate, even with the same name, nor is an id without a type."""
	assert _candidates_of('place', 'Riverside School', KNOWN + ['Riverside School']) == []


# link_mention


class SameDecider(Decider):
	"""A Decider of match_node that answers "same" for the ids of its configuration and records what it is asked."""

	QUESTION = Question.MATCH_NODE

	def __init__(self, extra_args):
		"""Start with nothing asked."""
		super().__init__(extra_args)
		self.asked = []

	def run(self, arguments):
		"""Record the arguments and answer "same" if the id of the node is in the configuration."""
		self.asked.append(arguments)
		same = arguments['node']['id'] in self.conf.get('same', [])
		return {'score': 1.0 if same else 0.0, 'same': same}


@pytest.fixture
def same_decider(monkeypatch):
	"""Register SameDecider as "same"."""
	monkeypatch.setitem(DECIDERS, 'same', SameDecider)


def _formalizer(decider = 'rules', **extra_args):
	"""Return a ready Formalizer that answers match_node with the given Decider and configuration."""
	formalizer = Formalizer(schema = 'test', extra_args = {'match_node': {'decider': decider, 'extra_args': extra_args}}, logger = [])
	formalizer.pilot(FormalizerState.READY.value)
	assert formalizer.meta['state'] == FormalizerState.READY.value
	return formalizer


def _link(concept, mention, known = KNOWN, formalizer = None):
	"""Return the decision of link_mention for a mention of a type, given its candidates among the known instances."""
	formalizer = formalizer or _formalizer()
	node	   = _node(concept, mention)
	candidates = find_candidates(node, _known_nodes(known))
	return link_mention(formalizer, node, candidates, ONTOLOGY, 'Some text.')


def test_link_mention_creates_a_mention_with_no_candidates():
	"""With no known instances, the mention is new, with its type followed by the mention as id."""
	assert _link('person|teacher', 'Elena Ruiz', []) == {'mention': 'Elena Ruiz', 'id': 'person|teacher|Elena Ruiz', 'status': 'new'}


def test_link_mention_links_the_whole_name_of_a_known_instance():
	"""The whole name of a known instance is that instance, found with its type or an ancestor."""
	expected = {'mention': 'Elena Ruiz', 'id': 'person|teacher|Elena Ruiz', 'status': 'known'}
	assert _link('person|teacher', 'Elena Ruiz') == expected
	assert _link('person', 'Elena Ruiz') == expected


def test_link_mention_links_the_whole_name_despite_a_type_conflict():
	"""The whole name with a type of another branch is the known instance, with type_conflict."""
	assert _link('person|student', 'Elena Ruiz') == {'mention': 'Elena Ruiz', 'id': 'person|teacher|Elena Ruiz', 'status': 'known', 'type_conflict': True}


def test_link_mention_links_a_partial_name_that_match_node_answers_same():
	"""A partial name is linked if match_node answers "same" (from the threshold of the rules decider on), and new otherwise."""
	assert _link('person|teacher', 'Ms. Ruiz') == {'mention': 'Ms. Ruiz', 'id': 'person|teacher|Elena Ruiz', 'status': 'known'}
	strict = _formalizer(same_node_threshold = 0.6)
	assert _link('person|teacher', 'Ms. Ruiz', formalizer = strict) == {'mention': 'Ms. Ruiz', 'id': 'person|teacher|Ms. Ruiz', 'status': 'new'}


def test_link_mention_reports_a_mention_of_several_instances_as_ambiguous():
	"""A first name of two known instances is ambiguous, and so is the whole name of two homonyms."""
	assert _link('person', 'Noah') == {
		'mention': 'Noah', 'id': None, 'status': 'ambiguous', 'candidates': ['person|student|Noah Kim', 'person|teacher|Noah Brown']
	}
	homonyms = KNOWN + ['person|student|Elena Ruiz']
	assert _link('person', 'Elena Ruiz', homonyms) == {
		'mention': 'Elena Ruiz', 'id': None, 'status': 'ambiguous', 'candidates': ['person|teacher|Elena Ruiz', 'person|student|Elena Ruiz']
	}


def test_link_mention_discards_partial_names_with_a_type_conflict():
	"""A partial name with a type of another branch is not enough: "Noah" as a principal is a new principal."""
	assert _link('person|principal', 'Noah') == {'mention': 'Noah', 'id': 'person|principal|Noah', 'status': 'new'}


def test_link_mention_prefers_the_only_whole_name():
	"""A whole name is the instance even if other candidates share some of its words."""
	assert _link('person|teacher', 'Noah Brown') == {'mention': 'Noah Brown', 'id': 'person|teacher|Noah Brown', 'status': 'known'}


def test_link_mention_asks_match_node_with_the_mention_the_text_and_the_ontology(same_decider):
	"""match_node is asked about every candidate, with the mention and its text, the known instance and the ontology."""
	formalizer = _formalizer('same', same = ['person|student|Noah Kim'])
	assert _link('person', 'Noah', formalizer = formalizer) == {'mention': 'Noah', 'id': 'person|student|Noah Kim', 'status': 'known'}
	asked = formalizer._deciders[Question.MATCH_NODE].asked
	assert asked[0] == {
		'mention': {'mention': 'Noah', 'type': 'person', 'texts': ['Some text.']},
		'node': {'id': 'person|student|Noah Kim', 'description': 'Description of person|student|Noah Kim.', 'names': []},
		'ontology': ONTOLOGY
	}
	assert [arguments['node']['id'] for arguments in asked] == ['person|student|Noah Kim', 'person|teacher|Noah Brown']


def test_link_mention_does_not_ask_match_node_about_the_only_whole_name(same_decider):
	"""A single candidate with the whole name is the instance without asking match_node."""
	formalizer = _formalizer('same')
	assert _link('person|teacher', 'Elena Ruiz', formalizer = formalizer)['status'] == 'known'
	assert formalizer._deciders[Question.MATCH_NODE].asked == []
