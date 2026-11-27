""" The datasets of match_node, in a common format, and the Formalizer that gives a Decider the arguments of their pairs.

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

A pair is a mention with one of its candidates. "meta" holds what the scores can be broken down by: of the mention (e.g., its status)
or of the pair (e.g., its group).

A dataset is saved as a .jsonl file (e.g., the datasets of ZESHEL made by zeshel.py): a mention per line after a first line that
describes the dataset,

	{"dataset": {"name": "zeshel_test", "types": [{"id": "entity", "definition": "..."}], "breakdowns": ["category", "group"], ...}}

with its name, the types of its mentions (with their definitions, the ontology the Formalizer is given) and the fields of "meta" its
scores are broken down by by default. Other keys describe how it was made.
"""

import hashlib, json, os, re, tempfile
from typing import List, Optional, Set

from mercury.graph.evidence import AgenticGraph, Decider, DeciderState, Formalizer


ROOT   = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))	# The root of the repository.
GROUPS = ('positive exact', 'positive different', 'negative homonym', 'negative other')	# The groups of the pairs, in order.


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


def load_file(path: str) -> Dataset:
	""" Returns the dataset of a .jsonl file: its first line describes it, and every other line is a mention. """

	with open(path) as f:
		lines = [json.loads(line) for line in f if line.strip() != '']

	header	 = lines[0]['dataset']
	ontology = create_ontology(header['types'])

	return Dataset(header['name'], path, ontology, lines[1:], header['breakdowns'])


def create_ontology(types: List[dict]) -> AgenticGraph:
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


def build_formalizer(ontology: AgenticGraph, decider: Decider) -> Formalizer:
	""" Returns a ready Formalizer that uses the ontology and answers match_node with the Decider: it gives the Decider the arguments
	of a pair as in the Endpoint, with the definition of the type of the mention. """

	conf	   = {'ontology': 'ontology', 'match_node': decider.name}
	formalizer = Formalizer(schema = 'Formalizer', extra_args = conf)
	formalizer.tools['%s/%s' % (formalizer.id.split('/')[0], ontology.id)] = ontology

	decider.pilot(DeciderState.READY.value)
	formalizer.add_tool(decider)
	formalizer.pilot(100)

	return formalizer


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


def find(dataset: Dataset, mention_id: str) -> Optional[dict]:
	""" Returns the mention of a dataset with an id, or None. """

	for mention in dataset.mentions:
		if mention['mention_id'] == mention_id:
			return mention

	return None
