""" Linking the mentions found by a [`Formalizer`][mercury.graph.evidence.Formalizer] to the known instances of a graph.

This module is temporary: these rules belong to the caller of the Formalizer, and they will move to the EvidenceGraph (or to an Agent)
when it uses them. Until then, they are used by the evaluation of the Formalizer (`evaluation/formalizer/run_eval.py`).

For every mention found by `extract_nodes`:

1. `find_candidates()` gives the known instances it can be: those of its root type that share a word with it.
2. `link_mention()` decides whether it is one of them, a new instance or ambiguous, asking `match_node` of the Formalizer when the
name alone is not enough.

`ontology_argument()` gives an ontology in the format of the argument 'ontology' of the questions of the Formalizer.
"""

from .agentic_graph import AgenticGraph
from .decider import IGNORED_WORDS, compare_names


def ontology_argument(ontology):
	""" Returns an ontology as the argument 'ontology' of the questions of a Formalizer, in the order of its nodes and edges.

	Args:
		ontology (AgenticGraph): The ontology, loaded (piloted).

	Returns:
		(dict): 'types', a list of {'id', 'definition'}, and 'relations', a list of {'id', 'src', 'dst', 'definition'}. A missing
			definition is an empty string.
	"""

	ntx = ontology._graph.networkx

	types = []
	for index, definition in ntx.nodes(data = 'definition'):
		concept = {'id': index, 'definition': _text(definition)}
		types.append(concept)

	relations = []
	for src, dst, index, definition in ntx.edges(keys = True, data = 'definition'):
		relation = {'id': index, 'src': src, 'dst': dst, 'definition': _text(definition)}
		relations.append(relation)

	result = {'types': types, 'relations': relations}

	return result


def _text(value):
	""" Returns the value, or an empty string if it is None. """

	if value is None:
		return ''

	return value


def find_candidates(node, known_nodes, ignored_words = IGNORED_WORDS):
	""" Returns the known instances a mention can be: those of the root type of its type that share a word with it.

	The score of a candidate is the share of words in common (1.0 when all of them are), leaving out the words of both types,
	possessives, accents and the ignored words. A candidate whose type is neither an ancestor nor a descendant of the type of the mention
	has 'type_conflict' True. The score measures how alike the names are, not whether they are the same instance: that is decided by
	`link_mention()`.

	Args:
		node (dict): A node returned by `extract_nodes`, with 'mention' and 'type'.
		known_nodes (list): The known instances, as {'id', 'description', 'names'}: its type followed by its name (e.g.,
			`person|teacher|Elena Ruiz`), what tells it apart from other instances and its other names (optional).
		ignored_words (list): The words left out of the names (titles by default).

	Returns:
		(list): The candidates, as {'id', 'score', 'description', 'names'} (and 'type_conflict' if their types conflict), from the
			highest to the lowest score.
	"""

	mention_id = '%s|%s' % (node['type'], node['mention'])

	found = []
	for known_node in known_nodes:
		candidate = _score_candidate(mention_id, known_node, ignored_words)
		if candidate['score'] > 0:
			found.append(candidate)

	result = sorted(found, key = _candidate_score, reverse = True)

	return result


def _candidate_score(candidate):
	""" Returns the score of a candidate (to sort them). """

	return candidate['score']


def _score_candidate(mention_id, known_node, ignored_words):
	""" Returns {'id', 'score', 'description', 'names'} of a known instance for a mention, with 'type_conflict' if their types are in
	different branches. """

	index		  = known_node['id']
	concept		  = AgenticGraph.parent_of(mention_id)
	known_concept = AgenticGraph.parent_of(index)
	score		  = compare_names(mention_id, index, ignored_words)

	candidate = {'id': index, 'score': score}
	candidate['description'] = known_node.get('description', '')
	candidate['names']		 = known_node.get('names', [])

	if _have_conflicting_types(concept, known_concept):
		candidate['type_conflict'] = True

	return candidate


def _have_conflicting_types(concept, known_concept):
	""" Returns True if the known type is not None and neither of both types descends from the other. """

	if known_concept is None:
		return False

	descends = AgenticGraph.descends_from(concept, known_concept)
	ascends	 = AgenticGraph.descends_from(known_concept, concept)

	return not (descends or ascends)


def link_mention(formalizer, node, candidates, ontology, text = None):
	""" Decides whether a mention found by `extract_nodes` is a known instance, a new one or ambiguous.

	1. Candidates with `type_conflict` are discarded unless their score is 1 (the whole name).
	2. A single candidate with score 1 is the instance.
	3. Otherwise, `match_node` of the Formalizer is asked about the mention (with the text) and every candidate left, and those it
	answers "same" are kept.
	4. None kept: the mention is new. One: it is that instance. More than one: it is ambiguous.

	Args:
		formalizer (Formalizer): A ready Formalizer that answers `match_node`.
		node (dict): A node returned by `extract_nodes`, with 'mention' and 'type'.
		candidates (list): Its candidates, as returned by `find_candidates()`.
		ontology (dict): The ontology, as the argument 'ontology' of the questions (see `ontology_argument()`).
		text (str): The text where the mention was found, passed to `match_node`.

	Returns:
		(dict): The 'mention' with its 'id' and 'status': 'known' (with 'type_conflict' True if the type found contradicts the known
			one), 'new' (its type followed by the mention) or 'ambiguous' (id None, with the ids of the instances it can be in
			'candidates').
	"""

	texts = []
	if text is not None:
		texts.append(text)

	mention = {'mention': node['mention'], 'type': node['type'], 'texts': texts}
	viable	= _viable_candidates(candidates)
	whole	= _whole_name_candidates(viable)

	if len(whole) == 1:
		accepted = whole
	else:
		accepted = _confirm_candidates(formalizer, mention, viable, ontology)

	result = _build_link(node, accepted)

	return result


def _viable_candidates(candidates):
	""" Returns the candidates without a type conflict, or with one but the whole name (score 1). """

	viable = []
	for candidate in candidates:
		whole_name = candidate['score'] == 1
		conflict   = candidate.get('type_conflict', False)
		if whole_name or not conflict:
			viable.append(candidate)

	return viable


def _whole_name_candidates(candidates):
	""" Returns the candidates with the whole name of the mention (score 1). """

	whole = []
	for candidate in candidates:
		if candidate['score'] == 1:
			whole.append(candidate)

	return whole


def _confirm_candidates(formalizer, mention, candidates, ontology):
	""" Returns the candidates that `match_node` of the Formalizer answers "same" for the mention. """

	result = []
	for candidate in candidates:
		known_node = {'id': candidate['id'], 'description': candidate['description'], 'names': candidate['names']}
		arguments  = {'mention': mention, 'node': known_node, 'ontology': ontology}
		answer	   = formalizer.match_node(arguments)
		if answer is not None and answer['same']:
			result.append(candidate)

	return result


def _build_link(node, accepted):
	""" Returns the decision for a mention given the candidates accepted: new if none, known if one and ambiguous if several. """

	if len(accepted) == 0:
		index = '%s|%s' % (node['type'], node['mention'])
		link  = {'mention': node['mention'], 'id': index, 'status': 'new'}

		return link

	if len(accepted) == 1:
		link = {'mention': node['mention'], 'id': accepted[0]['id'], 'status': 'known'}
		if accepted[0].get('type_conflict', False):
			link['type_conflict'] = True

		return link

	ids = []
	for candidate in accepted:
		ids.append(candidate['id'])

	link = {'mention': node['mention'], 'id': None, 'status': 'ambiguous', 'candidates': ids}

	return link
