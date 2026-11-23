""" The datasets that can be evaluated: the cases of the Formalizer or a .jsonl file, in the format of data/match_node/dataset.py.

"cases" and "hard_cases" are the cases of the Formalizer (evaluation/formalizer/), with the ontology and the known graph of their
context: every mention of a case that is known or new is paired with every known instance of its root type.
"""

import os
from typing import List

import networkx as nx

from data.match_node.dataset import ROOT, Dataset, load_file, name_of, words
from evaluation.formalizer.check_cases import HERE as CASES_DIR, Case, Entity, load_context, load_dataset, text_type


CASES	   = ('cases', 'hard_cases')
PRONOUNS   = {'he', 'she', 'it', 'they', 'him', 'her', 'them', 'his', 'its', 'their'}
BREAKDOWNS = ['status', 'group']


def load(name: str) -> Dataset:
	""" Returns the dataset of a name (one of CASES) or of the path of a .jsonl file. """

	if name in CASES:
		return load_cases(name)

	if name.endswith('.jsonl') and os.path.isfile(name):
		return load_file(name)

	raise ValueError('Unknown dataset "%s": it must be one of %s or a .jsonl file.' % (name, ', '.join(CASES)))


def source_of(info: dict) -> str:
	""" Returns what load() needs to load again the dataset of a run (see Dataset.info()). """

	if info['name'] in CASES:
		return info['name']

	return os.path.join(ROOT, info['path'])





def load_cases(name: str) -> Dataset:
	""" Returns the dataset of the cases of the Formalizer of a name (one of CASES). """

	path	= os.path.join(CASES_DIR, name + '.json')
	dataset = load_dataset(name + '.json')

	ontology, known = load_context(dataset['context'])

	mentions = []
	for case in dataset['cases']:
		mentions += mentions_of(case, known)

	return Dataset(name, path, ontology, mentions, BREAKDOWNS)





def root_of(concept: str) -> str:
	""" Returns the root type of a type or an id (e.g., "person" for "person|teacher|Elena Ruiz"). """

	return concept.split('|')[0]


def known_instances(known: nx.MultiDiGraph, case: Case) -> List[dict]:
	""" Returns the known instances of a case (the known graph and extra_known_nodes), with their descriptions, sorted by id. """

	nodes = []
	for node_id, description in known.nodes(data = 'description'):
		nodes.append({'id': node_id, 'description': description})

	nodes += case.get('extra_known_nodes', [])

	return sorted(nodes, key = lambda node: node['id'])


def is_paired(entity: Entity) -> bool:
	""" Returns True if a mention is paired with known instances: it is known or new, it has a type and it is not a pronoun.
	Ambiguous and unresolved mentions and pronouns are left out: a pronoun needs coreference, which match_node does not resolve. """

	if entity['status'] not in ('known', 'new'):
		return False

	if entity['mention'].lower() in PRONOUNS:
		return False

	return text_type(entity) is not None


def group_of(entity: Entity, instance: dict) -> str:
	""" Returns the group of a pair: a positive written as the name of the instance or not, or a negative that shares a word with it
	or not. """

	name = name_of(instance['id'])

	if entity['id'] == instance['id']:
		return 'positive exact' if entity['mention'] == name else 'positive different'

	common = words(entity['mention']) & words(name)

	return 'negative homonym' if len(common) > 0 else 'negative other'


def mentions_of(case: Case, known: nx.MultiDiGraph) -> List[dict]:
	""" Returns the mentions of a case: every paired mention, with every known instance of its root type as a candidate. """

	instances = known_instances(known, case)
	mentions  = []
	for index, entity in enumerate(case['entities']):
		if not is_paired(entity):
			continue

		mention = mention_of(case, index, entity, instances)
		mentions.append(mention)

	return mentions


def mention_of(case: Case, index: int, entity: Entity, instances: List[dict]) -> dict:
	""" Returns a mention of a case with its candidates. The mention is given with the type the text gives it, so that the errors of
	extract_nodes do not count here, and with the text of the case as its only text. """

	concept = text_type(entity)
	found	= {'mention': entity['mention'], 'type': concept, 'texts': [case['text']]}

	candidates = []
	for instance in instances:
		if root_of(instance['id']) != root_of(concept):
			continue

		candidate = candidate_of(entity, instance)
		candidates.append(candidate)

	mention_id = '%s#%d' % (case['id'], index)
	meta	   = {'case': case['id'], 'status': entity['status']}

	return {'mention_id': mention_id, 'meta': meta, 'mention': found, 'candidates': candidates}


def candidate_of(entity: Entity, instance: dict) -> dict:
	""" Returns a known instance as a candidate of a mention, with the expected answer and the group of the pair. """

	node = {'id': instance['id'], 'description': instance['description']}
	gold = entity['id'] == instance['id']
	meta = {'group': group_of(entity, instance)}

	return {'node': node, 'gold': gold, 'meta': meta}
