""" Runs match_node of the Formalizer on pairs of mentions and known instances of a dataset and scores its decisions.

Every mention of a case that is "known" or "new" is paired with every known instance (the known graph and the extra_known_nodes of the
case) of the same root type (e.g., every "person|..." for a "person|teacher"). A pair is positive if the instance is the expected id
of the mention, and negative otherwise. Ambiguous and unresolved mentions and pronouns are left out: a pronoun needs coreference, which
match_node does not resolve.

The mention is given with its expected type (its text_type or, by default, the type of its id), so that the errors of extract_nodes do
not count here, and with the text of the case as its only text.

Scores:

- same: precision, recall and F1 of the answer "same", which depends on the threshold of the Decider,
- AUC: the probability that a positive pair gets a higher score than a negative one (1 orders every pair right, 0.5 is chance),
  which does not depend on any threshold,
- best threshold: the threshold on the score with the highest F1 on these pairs, and that F1,
- top-1: the share of known mentions whose expected instance is the only one with the highest score among their pairs.

Every score is also given by group of pairs: positives written as the name of the instance (exact) or not (different), negatives that
share a word with the name of the instance (homonym) or not (other).

Run it from the root of the repository: python evaluation/formalizer/run_match_node_eval.py [dataset] [-v]

The dataset is cases.json unless another .json file of this directory is given. -v lists the pairs whose answer is wrong.
"""

import re, sys, time

import networkx as nx

from mercury.graph.evidence import AgenticGraph, Decider, DeciderState, Formalizer

from check_cases import Case, Entity, get_dataset_name, load_context, load_dataset
from run_eval import Score, text_type


PRONOUNS  = {'he', 'she', 'it', 'they', 'him', 'her', 'them', 'his', 'its', 'their'}
GROUPS	  = ('positive exact', 'positive different', 'negative homonym', 'negative other')
THRESHOLD = 0.5


class NamesDecider(Decider):
	""" A Decider of match_node for this evaluation only: it compares the words of the mention with those of the name of the known
	instance (the last level of its id), ignoring case. The score is the share of the words of the mention that are in the name, and
	the mention is the same instance if the score reaches "threshold" (0.5 by default). It reads neither the texts nor the description. """

	def __init__(self, schema, extra_args, endpoint = None, logger = None):
		super().__init__(schema, extra_args, endpoint = endpoint, logger = logger)

		self.question = 'MATCH_NODE'

		self._meta_ = self._meta()


	def _run(self, request):
		arguments = request['arguments']
		mention	  = self._words(arguments['mention']['mention'])
		name	  = self._words(arguments['node']['id'].split('|')[-1])
		common	  = mention & name
		score	  = len(common)/len(mention) if len(mention) > 0 else 0.0
		threshold = self.conf.get('threshold', THRESHOLD)
		answer	  = {'score': score, 'same': score >= threshold}

		return {'finish_reason': 'stop', 'message': answer}


	def _dry_run(self, request):
		return {'status': 0, 'description': 'Valid request.'}


	def _words(self, text):
		return set(re.findall(r'\w+', text.lower()))


def build_formalizer(ontology: AgenticGraph, decider: Decider) -> Formalizer:
	""" Returns a ready Formalizer that uses the ontology and answers match_node with the Decider. """

	conf	   = {'ontology': 'ontology', 'match_node': decider.name}
	formalizer = Formalizer(schema = 'Formalizer', extra_args = conf)
	formalizer.tools['%s/%s' % (formalizer.id.split('/')[0], ontology.id)] = ontology

	decider.pilot(DeciderState.READY.value)
	formalizer.add_tool(decider)
	formalizer.pilot(100)

	return formalizer


def known_instances(known: nx.MultiDiGraph, case: Case) -> list[dict]:
	""" Returns the known instances of a case (the known graph and extra_known_nodes), with their descriptions, sorted by id. """

	nodes  = [{'id': index, 'description': description} for index, description in known.nodes(data = 'description')]
	nodes += case.get('extra_known_nodes', [])

	return sorted(nodes, key = lambda node: node['id'])


def root_of(concept: str) -> str:
	""" Returns the root type of a type or an id (e.g., "person" for "person|teacher|Elena Ruiz"). """

	return concept.split('|')[0]


def is_paired(entity: Entity) -> bool:
	""" Returns True if a mention is paired with known instances: it is known or new, it has a type and it is not a pronoun. """

	if entity['status'] not in ('known', 'new'):
		return False

	if entity['mention'].lower() in PRONOUNS:
		return False

	return text_type(entity) is not None


def group_of(entity: Entity, instance: dict) -> str:
	""" Returns the group of a pair: a positive written as the name of the instance or not, or a negative that shares a word with it
	or not. """

	name = instance['id'].split('|')[-1]

	if entity['id'] == instance['id']:
		return 'positive exact' if entity['mention'] == name else 'positive different'

	mention_words = set(re.findall(r'\w+', entity['mention'].lower()))
	name_words	  = set(re.findall(r'\w+', name.lower()))

	return 'negative homonym' if len(mention_words & name_words) > 0 else 'negative other'


def pairs_of(case: Case, known: nx.MultiDiGraph) -> list[dict]:
	""" Returns the pairs of a case: every paired mention with every known instance of its root type. """

	instances = known_instances(known, case)
	pairs	  = []
	for entity in case['entities']:
		if not is_paired(entity):
			continue

		concept = text_type(entity)
		for instance in instances:
			if root_of(instance['id']) != root_of(concept):
				continue

			pair = {'case': case['id'], 'entity': entity, 'concept': concept, 'instance': instance, 'text': case['text'],
					'positive': entity['id'] == instance['id'], 'group': group_of(entity, instance)}
			pairs.append(pair)

	return pairs


def decide(formalizer: Formalizer, pair: dict) -> dict:
	""" Returns the answer of match_node for a pair. """

	mention = {'mention': pair['entity']['mention'], 'type': pair['concept'], 'texts': [pair['text']]}
	answer	= formalizer.match_node({'mention': mention, 'node': pair['instance']})

	return answer


def score_same(pairs: list[dict]) -> Score:
	""" Returns the hits, misses and extras of the answer "same" over the pairs. """

	result = Score()
	for pair in pairs:
		result.tp += pair['positive'] and pair['same']
		result.fp += (not pair['positive']) and pair['same']
		result.fn += pair['positive'] and not pair['same']

	return result


def auc(pairs: list[dict]) -> float | None:
	""" Returns the probability that a positive pair has a higher score than a negative one (ties count half), or None if there are no
	positives or no negatives. """

	positives = [pair['score'] for pair in pairs if pair['positive']]
	negatives = [pair['score'] for pair in pairs if not pair['positive']]

	if len(positives) == 0 or len(negatives) == 0:
		return None

	wins = 0.0
	for positive in positives:
		for negative in negatives:
			wins += 1.0 if positive > negative else 0.5 if positive == negative else 0.0

	return wins/(len(positives)*len(negatives))


def best_threshold(pairs: list[dict]) -> tuple[float, float]:
	""" Returns the threshold on the score (same if score >= threshold) with the highest F1 on the pairs, and that F1. """

	best = (0.0, -1.0)
	for threshold in sorted({pair['score'] for pair in pairs}):
		decided = [{**pair, 'same': pair['score'] >= threshold} for pair in pairs]
		f1		= score_same(decided).f1()
		if f1 > best[1]:
			best = (threshold, f1)

	return best


def top_1(pairs: list[dict]) -> tuple[int, int]:
	""" Returns how many known mentions have their expected instance as the only one with the highest score, and how many known
	mentions there are. """

	by_mention = {}
	for pair in pairs:
		if pair['entity']['status'] == 'known':
			by_mention.setdefault((pair['case'], pair['entity']['mention']), []).append(pair)

	hits = 0
	for mention_pairs in by_mention.values():
		highest = max(pair['score'] for pair in mention_pairs)
		winners = [pair for pair in mention_pairs if pair['score'] == highest]
		hits   += len(winners) == 1 and winners[0]['positive']

	return hits, len(by_mention)


def print_scores(pairs: list[dict]) -> None:
	""" Prints the scores of every group of pairs and of all of them. """

	print('\n%-20s %6s %6s %9s %7s %6s %6s' % ('', 'pairs', 'right', 'precision', 'recall', 'F1', 'AUC'))
	for group in GROUPS:
		group_pairs = [pair for pair in pairs if pair['group'] == group]
		right		= sum(pair['same'] == pair['positive'] for pair in group_pairs)
		print('%-20s %6d %6d' % (group, len(group_pairs), right))

	s		= score_same(pairs)
	right	= sum(pair['same'] == pair['positive'] for pair in pairs)
	area	= auc(pairs)
	print('%-20s %6d %6d %9.2f %7.2f %6.2f %6s' % ('all', len(pairs), right, s.precision(), s.recall(), s.f1(),
		  '%.2f' % area if area is not None else '-'))

	threshold, f1 = best_threshold(pairs)
	hits, total	  = top_1(pairs)
	print('\nbest threshold %.3f (F1 %.2f)   top-1 %d/%d (%.2f)' % (threshold, f1, hits, total, hits/total if total > 0 else 0.0))


def print_errors(pairs: list[dict]) -> None:
	""" Prints the pairs whose answer is wrong. """

	print()
	for pair in pairs:
		if pair['same'] == pair['positive']:
			continue

		kind = 'missed' if pair['positive'] else 'wrong '
		print('%-4s %s %-18s %-24s vs %-45s score %.3f' % (pair['case'], kind, pair['group'], '"%s"' % pair['entity']['mention'],
			  pair['instance']['id'], pair['score']))


def main() -> int:
	verbose = '-v' in sys.argv[1:]
	dataset = load_dataset(get_dataset_name())

	ontology, known = load_context(dataset['context'])
	decider			= NamesDecider('Names', {'threshold': THRESHOLD})
	formalizer		= build_formalizer(ontology, decider)
	start			= time.time()

	pairs = []
	for case in dataset['cases']:
		pairs += pairs_of(case, known)

	for pair in pairs:
		answer = decide(formalizer, pair)
		pair.update(answer)

	print('Decider: %s, %d pairs of %d cases.' % (type(decider).__name__, len(pairs), len(dataset['cases'])))
	print_scores(pairs)
	if verbose:
		print_errors(pairs)

	print('\n%.1f seconds.' % (time.time() - start))

	return 0


if __name__ == '__main__':
	sys.exit(main())
