""" Runs the Formalizer, with the GLiNER2 Deciders, on every case of a dataset and scores its extraction against the expected one.

For every case, the Formalizer is asked, with the text of the case:

1. extract_nodes, to find the mentions of the text and their types,
2. extract_edges, given the expected nodes of the case (those with an id), so that the edges do not depend on any linking.

Linking the mentions to the known instances is not evaluated. Only the text of every case is used (no second call with its context).

Scores (micro-averaged precision, recall and F1 over all cases):

- mentions: (mention), whatever its id, i.e., whether the text was found,
- types: (mention, type) of the mentions whose type the text gives (their text_type or, by default, the type of their id), i.e.,
  whether the type chosen by extract_nodes is the right one,
- edges: (src, relation, dst).

Run it from the root of the repository: python evaluation/formalizer/run_eval.py [dataset] [-v]

The dataset is cases.json unless another .json file of this directory is given. -v lists what is missing and what is extra in every
case.
"""

import sys, time
from dataclasses import dataclass, field

from mercury.graph.evidence import AgenticGraph, Formalizer
from mercury.graph.evidence.deciders import XEdgesGl2Decider, XNodesGl2Decider

from check_cases import Case, Entity, Output, get_dataset_name, load_context, load_dataset


MODEL	= {'model': 'fastino/gliner2.5-base-v1'}


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


METRICS = ('mentions', 'types', 'edges')


def build_formalizer(ontology: AgenticGraph) -> Formalizer:
	""" Returns a ready Formalizer that uses the ontology and answers extract_nodes and extract_edges with the GLiNER2 Deciders. """

	conf	   = {'ontology': 'ontology', 'extract_nodes': 'NodesGLiNER2', 'extract_edges': 'EdgesGLiNER2'}
	formalizer = Formalizer(schema = 'Formalizer', extra_args = conf)
	formalizer.tools['%s/%s' % (formalizer.id.split('/')[0], ontology.id)] = ontology

	for decider in (XNodesGl2Decider('NodesGLiNER2', MODEL), XEdgesGl2Decider('EdgesGLiNER2', MODEL)):
		decider.pilot(100)
		formalizer.add_tool(decider)

	formalizer.pilot(100)

	return formalizer


def expected_nodes(case: Case) -> list[dict]:
	""" Returns the expected nodes of a case that have an id, as given to extract_edges. """

	return [{'mention': e['mention'], 'id': e['id']} for e in case['entities'] if e['id'] is not None]


def formalize(case: Case, formalizer: Formalizer) -> Output:
	""" Returns the output of the Formalizer for the text of a case in the format of the cases: the nodes found by extract_nodes (with
	their mention and type) and the edges found by extract_edges given the expected nodes of the case. """

	nodes = formalizer.extract_nodes({'text': case['text']})
	found = formalizer.extract_edges({'text': case['text'], 'nodes': expected_nodes(case)})
	edges = [{'src': edge['src'], 'relation': edge['relation'], 'dst': edge['dst']} for edge in found]

	return {'entities': nodes, 'edges': edges}


def keys(output: Output, metric: str) -> set[tuple]:
	""" Returns what is compared of an output for a metric. """

	if metric == 'mentions':
		return {(e['mention'],) for e in output['entities']}

	return {(e['src'], e['relation'], e['dst']) for e in output['edges']}


def text_type(entity: Entity) -> str | None:
	""" Returns the type the text gives an entity: its text_type or, by default, the type of its id (None if it has no id or its
	type conflicts with the known one). """

	if 'text_type' in entity:
		return entity['text_type']

	if entity['id'] is None or entity.get('type_conflict', False):
		return None

	return AgenticGraph.parent_of(entity['id'])


def expected_types(case: Case) -> set[tuple]:
	""" Returns (mention, type) of the entities of a case whose type the text gives. """

	typed  = [(e['mention'], text_type(e)) for e in case['entities']]
	result = {(mention, concept) for mention, concept in typed if concept is not None}

	return result


def score_types(case: Case, predicted: Output) -> Score:
	""" Returns the score of the types chosen for the mentions of a case whose type the text gives. Other mentions are left out. """

	expected = expected_types(case)
	mentions = {mention for mention, _ in expected}
	found	 = {(e['mention'], e['type']) for e in predicted['entities'] if e['mention'] in mentions}
	result	 = score(expected, found)

	return result


def score(expected: set[tuple], predicted: set[tuple]) -> Score:
	""" Returns the hits, the misses and the extras of a prediction. """

	return Score(len(expected & predicted), len(predicted - expected), len(expected - predicted),
				 sorted(expected - predicted, key = str), sorted(predicted - expected, key = str))


def score_case(case: Case, predicted: Output) -> dict[str, Score]:
	""" Returns the score of an output for every metric. """

	result			= {metric: score(keys(case, metric), keys(predicted, metric)) for metric in METRICS if metric != 'types'}
	result['types'] = score_types(case, predicted)

	return result


def print_case(case: Case, scores: dict[str, Score], verbose: bool) -> None:
	""" Prints the hits, misses and extras of a case and, if verbose, what is missing and what is extra. """

	print('%-4s %s' % (case['id'], '   '.join('%s %d/%d/%d' % (m, scores[m].tp, scores[m].fn, scores[m].fp) for m in METRICS)))
	if not verbose:
		return

	for metric in METRICS:
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

	ontology, _ = load_context(dataset['context'])
	formalizer	= build_formalizer(ontology)
	totals			= {metric: Score() for metric in METRICS}
	start			= time.time()

	print('case  hits/miss/extra')
	for case in dataset['cases']:
		predicted = formalize(case, formalizer)
		scores	  = score_case(case, predicted)
		print_case(case, scores, verbose)
		for metric in METRICS:
			totals[metric].add(scores[metric])

	print_totals(totals)
	print('\n%d cases in %.1f seconds.' % (len(dataset['cases']), time.time() - start))

	return 0


if __name__ == '__main__':
	sys.exit(main())
