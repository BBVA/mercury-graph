""" Runs the GLiNER2 Formalizer on every case of a dataset and scores its output against the expected one.

For every case, the Formalizer is used as the EvidenceGraph will use it:

1. hint_nodes, given the known instances of the case (the known graph and extra_known_nodes) as candidates,
2. link_mention on every node, to decide whether it is a known instance, a new one or ambiguous,
3. hint_edges, given the linked nodes.

Only the text of every case is used (no second call with its context).

Scores (micro-averaged precision, recall and F1 over all cases):

- mentions: (mention), whatever its id, i.e., whether the text was found,
- entities: (mention, id, status), i.e., whether it was also linked to the right instance,
- edges: (src, relation, dst).

Run it from the root of the repository: python evaluation/formalizer/run_eval.py [dataset] [-v]

The dataset is cases.json unless another .json file of this directory is given. -v lists what is missing and what is extra in every
case.
"""

import sys, time
from dataclasses import dataclass, field

import networkx as nx

from mercury.graph.evidence import AgenticGraph, Formalizer

from check_cases import Case, Output, get_dataset_name, load_context, load_dataset


MODEL	= {'library': 'gliner2', 'model': 'fastino/gliner2.5-base-v1'}


@dataclass
class Score:
	tp		: int = 0
	fp		: int = 0
	fn		: int = 0
	missing : list = field(default_factory = list)
	extra	: list = field(default_factory = list)

	def add(self, other: 'Score') -> None:
		self.tp += other.tp
		self.fp += other.fp
		self.fn += other.fn

	def precision(self) -> float:
		return self.tp/(self.tp + self.fp) if self.tp + self.fp > 0 else 0.0

	def recall(self) -> float:
		return self.tp/(self.tp + self.fn) if self.tp + self.fn > 0 else 0.0

	def f1(self) -> float:
		p, r = self.precision(), self.recall()

		return 2*p*r/(p + r) if p + r > 0 else 0.0


METRICS = ('mentions', 'entities', 'edges')


def build_formalizer(ontology: AgenticGraph) -> Formalizer:
	""" Returns a ready GLiNER2 Formalizer that uses the ontology. """

	formalizer = Formalizer(schema = 'GLiNER2', extra_args = {'model': MODEL, 'ontology': 'ontology'})
	formalizer.tools['%s/%s' % (formalizer.id.split('/')[0], ontology.id)] = ontology
	formalizer.pilot(100)

	return formalizer


def known_nodes(known: nx.MultiDiGraph, case: Case) -> list[dict]:
	""" Returns the known instances of a case (the known graph and extra_known_nodes), with their descriptions, sorted by id. """

	nodes  = [{'id': index, 'description': description} for index, description in known.nodes(data = 'description')]
	nodes += case.get('extra_known_nodes', [])

	return sorted(nodes, key = lambda node: node['id'])


def formalize(text: str, formalizer: Formalizer, candidates: list[dict]) -> Output:
	""" Returns the output of the Formalizer for a text in the format of the cases, given the known instances as candidates. """

	nodes	 = formalizer.hint_nodes({'text': text, 'candidates': candidates})
	entities = [formalizer.link_mention(node, text) for node in nodes]
	found	 = formalizer.hint_edges({'text': text, 'nodes': entities})
	edges	 = [{'src': edge['src'], 'relation': edge['relation'], 'dst': edge['dst']} for edge in found]

	return {'entities': entities, 'edges': edges}


def keys(output: Output, metric: str) -> set[tuple]:
	""" Returns what is compared of an output for a metric. """

	if metric == 'mentions':
		return {(e['mention'],) for e in output['entities']}

	if metric == 'entities':
		return {(e['mention'], e['id'], e['status']) for e in output['entities']}

	return {(e['src'], e['relation'], e['dst']) for e in output['edges']}


def score(expected: set[tuple], predicted: set[tuple]) -> Score:
	""" Returns the hits, the misses and the extras of a prediction. """

	return Score(len(expected & predicted), len(predicted - expected), len(expected - predicted),
				 sorted(expected - predicted, key = str), sorted(predicted - expected, key = str))


def score_case(case: Case, predicted: Output) -> dict[str, Score]:
	""" Returns the score of an output for every metric. """

	return {metric: score(keys(case, metric), keys(predicted, metric)) for metric in METRICS}


def print_case(case: Case, scores: dict[str, Score], verbose: bool) -> None:
	""" Prints the hits, misses and extras of a case and, if verbose, what is missing and what is extra. """

	print('%-4s %s' % (case['id'], '   '.join('%s %d/%d/%d' % (m, scores[m].tp, scores[m].fn, scores[m].fp) for m in METRICS)))
	if not verbose:
		return

	for metric in ('entities', 'edges'):
		for item in scores[metric].missing:
			print('       missing %-8s %s' % (metric, item))

		for item in scores[metric].extra:
			print('       extra   %-8s %s' % (metric, item))


def print_totals(totals: dict[str, Score]) -> None:
	""" Prints a table with the micro-averaged precision, recall and F1 of every metric. """

	print('\n%-9s %9s %9s %9s' % ('', 'precision', 'recall', 'F1'))
	for metric in METRICS:
		s = totals[metric]
		print('%-9s %9.2f %9.2f %9.2f' % (metric, s.precision(), s.recall(), s.f1()))


def main() -> int:
	verbose = '-v' in sys.argv[1:]
	dataset = load_dataset(get_dataset_name())

	ontology, known = load_context(dataset['context'])
	formalizer		= build_formalizer(ontology)
	totals			= {metric: Score() for metric in METRICS}
	start			= time.time()

	print('case  hits/miss/extra')
	for case in dataset['cases']:
		candidates = known_nodes(known, case)
		predicted  = formalize(case['text'], formalizer, candidates)
		scores	  = score_case(case, predicted)
		print_case(case, scores, verbose)
		for metric in METRICS:
			totals[metric].add(scores[metric])

	print_totals(totals)
	print('\n%d cases in %.1f seconds.' % (len(dataset['cases']), time.time() - start))

	return 0


if __name__ == '__main__':
	sys.exit(main())
