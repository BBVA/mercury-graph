""" The datasets of match_node, in a common format.

A dataset is a list of mentions. Every mention has the arguments of match_node for the mention and its candidates, the known instances
it is compared with, each one with the expected answer:

	{
		"mention_id": "H03#1",
		"meta": {"case": "H03", "status": "known"},
		"mention": {"mention": "Ms. Ruiz", "type": "person|teacher", "texts": ["..."]},
		"candidates": [
			{"node": {"id": "person|teacher|Elena Ruiz", "description": "..."}, "gold": true, "meta": {"group": "positive exact"}},
			...
		]
	}

A pair is a mention with one of its candidates. "meta" holds what the scores can be broken down by: of the mention (e.g., its case) or
of the pair (e.g., its group).

The datasets are:

- "cases" and "hard_cases": the cases of the Formalizer (evaluation/formalizer/), with the ontology and the known graph of their
  context,
- a .jsonl file (e.g., the datasets of ZESHEL made by zeshel.py): a mention per line after a first line that describes the dataset,

	{"dataset": {"name": "zeshel_test", "types": [{"id": "entity", "definition": "..."}], "breakdowns": ["category", "group"], ...}}

  with its name, the types of its mentions (with their definitions, the ontology the Formalizer is given) and the fields of "meta" its
  scores are broken down by by default. Other keys describe how it was made.
"""

import hashlib, json, os, re, tempfile
from typing import List, Optional, Set

import networkx as nx

from mercury.graph.evidence import AgenticGraph

from evaluation.formalizer.check_cases import HERE as CASES_DIR, Case, Entity, load_context, load_dataset, text_type


ROOT	   = os.path.dirname(os.path.dirname(CASES_DIR))		# The root of the repository.
CASES	   = ('cases', 'hard_cases')
PRONOUNS   = {'he', 'she', 'it', 'they', 'him', 'her', 'them', 'his', 'its', 'their'}
GROUPS	   = ('positive exact', 'positive different', 'negative homonym', 'negative other')
BREAKDOWNS = ['group']


class Dataset:
	""" A dataset of match_node: its name, its file and the hash of that file, the ontology the Formalizer needs, the mentions and the
	fields of "meta" its scores are broken down by by default. """

	def __init__(self, name: str, path: str, ontology: AgenticGraph, mentions: List[dict], breakdowns: List[str]):
		self.name		= name
		self.path		= path
		self.sha256		= sha256_of(path)
		self.ontology	= ontology
		self.mentions	= mentions
		self.breakdowns = breakdowns


	def pairs(self) -> int:
		""" Returns the number of pairs of the dataset. """

		total = 0
		for mention in self.mentions:
			total += len(mention['candidates'])

		return total


	def info(self) -> dict:
		""" Returns what a run keeps of the dataset. """

		path = os.path.relpath(self.path, ROOT)
		info = {'name': self.name, 'path': path, 'sha256': self.sha256, 'mentions': len(self.mentions), 'pairs': self.pairs(),
				'breakdowns': self.breakdowns}

		return info


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


def load_file(path: str) -> Dataset:
	""" Returns the dataset of a .jsonl file: its first line describes it, and every other line is a mention. """

	with open(path) as f:
		lines = [json.loads(line) for line in f if line.strip() != '']

	header	 = lines[0]['dataset']
	ontology = ontology_of(header['types'])

	return Dataset(header['name'], path, ontology, lines[1:], header['breakdowns'])


def ontology_of(types: List[dict]) -> AgenticGraph:
	""" Returns a ready ontology with the types (their "id" and "definition") and no relationships. """

	with tempfile.TemporaryDirectory() as folder:
		nodes = os.path.join(folder, 'entities_concepts.csv')
		edges = os.path.join(folder, 'relationships_concepts.csv')
		write_types(nodes, types)
		with open(edges, 'w') as f:
			f.write('id\tsrc\tdst\tdefinition\n')

		ontology = AgenticGraph(schema = 'ontology', extra_args = {'nodes': {'type': 'csv', 'path': nodes},
																	'edges': {'type': 'csv', 'path': edges}})
		ontology.pilot(100)

	return ontology


def write_types(path: str, types: List[dict]) -> None:
	""" Writes the types (their "id" and "definition") as the tab separated file of the types of an ontology. """

	with open(path, 'w') as f:
		f.write('id\tdefinition\n')
		for concept in types:
			f.write('%s\t%s\n' % (concept['id'], concept['definition']))


def load_cases(name: str) -> Dataset:
	""" Returns the dataset of the cases of the Formalizer of a name (one of CASES). """

	path	= os.path.join(CASES_DIR, name + '.json')
	dataset = load_dataset(name + '.json')

	ontology, known = load_context(dataset['context'])

	mentions = []
	for case in dataset['cases']:
		mentions += mentions_of(case, known)

	return Dataset(name, path, ontology, mentions, BREAKDOWNS)


def sha256_of(path: str) -> str:
	""" Returns the SHA-256 of a file. """

	with open(path, 'rb') as f:
		digest = hashlib.sha256(f.read()).hexdigest()

	return digest


def words(text: str) -> Set[str]:
	""" Returns the words of a text, in lower case. """

	return set(re.findall(r'\w+', text.lower()))


def name_of(node_id: str) -> str:
	""" Returns the name of a known instance: the last level of its id (e.g., "Elena Ruiz" for "person|teacher|Elena Ruiz"). """

	return node_id.split('|')[-1]


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


def find(dataset: Dataset, mention_id: str) -> Optional[dict]:
	""" Returns the mention of a dataset with an id, or None. """

	for mention in dataset.mentions:
		if mention['mention_id'] == mention_id:
			return mention

	return None
