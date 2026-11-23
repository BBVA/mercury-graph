""" The scores of match_node, computed from the scores of a run (see run.py): pure functions, no model.

A pair is a candidate of a mention with its expected answer ("gold"), the score of the Decider and the "meta" of the mention and of
the candidate together. The answer "same" is score >= threshold.

- same: precision, recall and F1 of the answer "same", which depends on the threshold,
- AUC: the probability that a positive pair gets a higher score than a negative one (1 orders every pair right, 0.5 is chance),
  which does not depend on any threshold,
- best threshold: the threshold with the highest F1 on these pairs, and that F1,
- top-1: the share of the mentions with an expected candidate whose expected candidate is the only one with the highest score,
- decision: the share of the mentions whose final decision is right. A mention is linked to its candidate with the highest score if
  that score reaches the threshold and no other candidate has it, and it is new if no candidate reaches the threshold (a tie at the
  top is a wrong link). A mention with an expected candidate ("known") is right if it is linked to it: otherwise it is linked to
  another one (a wrong link) or missed (new). A mention without one ("new") is right if it is new: otherwise it is a wrong link,
- best decision threshold: the threshold with the most right decisions, and their share.

The scores of a breakdown by a field of the mentions (e.g., their category) have top-1 and decision too; those by a field of the pairs
(e.g., their group) do not, since the pairs of a mention can have different values.
"""

import collections
from typing import Counter, Dict, List, Optional, Tuple


def scored(candidates: List[dict]) -> List[dict]:
	""" Returns the candidates that have a score: those whose call to the Decider did not fail. """

	result = []
	for candidate in candidates:
		if candidate['score'] is not None:
			result.append(candidate)

	return result


def pairs_of(mentions: List[dict]) -> List[dict]:
	""" Returns the pairs of the mentions of a run that have a score, in order. """

	pairs = []
	for mention in mentions:
		for candidate in scored(mention['candidates']):
			meta = dict(mention['meta'])
			meta.update(candidate.get('meta', {}))

			pair = {'mention_id': mention['mention_id'], 'id': candidate['id'], 'gold': candidate['gold'], 'score': candidate['score'],
					'meta': meta}
			pairs.append(pair)

	return pairs


def counts(pairs: List[dict], threshold: float) -> Tuple[int, int, int]:
	""" Returns the hits, the extras and the misses of the answer "same" over the pairs. """

	tp, fp, fn = 0, 0, 0
	for pair in pairs:
		same = pair['score'] >= threshold

		tp += pair['gold'] and same
		fp += (not pair['gold']) and same
		fn += pair['gold'] and not same

	return tp, fp, fn


def precision_recall_f1(tp: int, fp: int, fn: int) -> Tuple[float, float, float]:
	""" Returns the precision, the recall and the F1 of some hits, extras and misses. """

	precision = tp/(tp + fp) if tp + fp > 0 else 0.0
	recall	  = tp/(tp + fn) if tp + fn > 0 else 0.0
	f1		  = 2*precision*recall/(precision + recall) if precision + recall > 0 else 0.0

	return precision, recall, f1


def right(pairs: List[dict], threshold: float) -> int:
	""" Returns how many pairs get the expected answer. """

	total = 0
	for pair in pairs:
		same   = pair['score'] >= threshold
		total += same == pair['gold']

	return total


def auc(pairs: List[dict]) -> Optional[float]:
	""" Returns the probability that a positive pair has a higher score than a negative one (ties count half), or None if there are no
	positives or no negatives. """

	positives = [pair['score'] for pair in pairs if pair['gold']]
	negatives = [pair['score'] for pair in pairs if not pair['gold']]

	if len(positives) == 0 or len(negatives) == 0:
		return None

	wins = 0.0
	for positive in positives:
		for negative in negatives:
			wins += win(positive, negative)

	return wins/(len(positives)*len(negatives))


def win(positive: float, negative: float) -> float:
	""" Returns 1 if the positive score is higher than the negative one, 0.5 if they are equal and 0 otherwise. """

	if positive > negative:
		return 1.0

	if positive == negative:
		return 0.5

	return 0.0


def best_threshold(pairs: List[dict]) -> Tuple[float, float]:
	""" Returns the threshold with the highest F1 on the pairs, and that F1. """

	best_threshold, best_f1 = 0.0, -1.0
	for threshold in sorted({pair['score'] for pair in pairs}):
		tp, fp, fn = counts(pairs, threshold)
		_, _, f1   = precision_recall_f1(tp, fp, fn)

		if f1 > best_f1:
			best_threshold, best_f1 = threshold, f1

	return best_threshold, best_f1


def top_1(mentions: List[dict]) -> Tuple[int, int]:
	""" Returns how many mentions with an expected candidate have it as the only one with the highest score, and how many mentions
	with an expected candidate there are. """

	hits, total = 0, 0
	for mention in mentions:
		candidates = scored(mention['candidates'])
		has_gold   = any(candidate['gold'] for candidate in candidates)
		if not has_gold:
			continue

		highest = max(candidate['score'] for candidate in candidates)
		winners = [candidate for candidate in candidates if candidate['score'] == highest]

		total += 1
		hits  += len(winners) == 1 and winners[0]['gold']

	return hits, total


def scores_of(pairs: List[dict], threshold: float) -> dict:
	""" Returns the scores of some pairs: how many there are and get the expected answer and, if there are both positives and negatives,
	the precision, the recall and the F1 of "same" and the AUC. """

	scores = {'pairs': len(pairs), 'right': right(pairs, threshold)}

	area = auc(pairs)
	if area is None:
		return scores

	tp, fp, fn = counts(pairs, threshold)
	precision, recall, f1 = precision_recall_f1(tp, fp, fn)

	scores.update({'precision': precision, 'recall': recall, 'f1': f1, 'auc': area})

	return scores


def breakdown(pairs: List[dict], field: str, threshold: float) -> Dict[str, dict]:
	""" Returns the scores of the pairs by the value of a field of their "meta", in the order the values appear. """

	by_value = {}
	for pair in pairs:
		value = str(pair['meta'].get(field, '-'))
		by_value.setdefault(value, []).append(pair)

	result = {}
	for value, value_pairs in by_value.items():
		result[value] = scores_of(value_pairs, threshold)

	return result


def ratio(hits: int, total: int) -> Optional[float]:
	""" Returns hits/total, or None if there is nothing to count. """

	if total == 0:
		return None

	return hits/total


def decision_of(mention: dict) -> Optional[dict]:
	""" Returns what the decision of a mention depends on: whether it has an expected candidate, the highest score and whether the
	expected candidate is the only one with it; None if no candidate has a score. """

	candidates = scored(mention['candidates'])
	if len(candidates) == 0:
		return None

	highest = max(candidate['score'] for candidate in candidates)
	winners = []
	for candidate in candidates:
		if candidate['score'] == highest:
			winners.append(candidate)

	known	  = any(candidate['gold'] for candidate in candidates)
	gold_wins = len(winners) == 1 and winners[0]['gold']

	return {'known': known, 'highest': highest, 'gold_wins': gold_wins}


def decisions_of(mentions: List[dict]) -> List[dict]:
	""" Returns the decisions of the mentions that have a score. """

	decisions = []
	for mention in mentions:
		decision = decision_of(mention)
		if decision is not None:
			decisions.append(decision)

	return decisions


def outcome_of(decision: dict, threshold: float) -> str:
	""" Returns the outcome of a decision: "linked" to the expected candidate, "wrong link" to another one or "new" if no candidate
	reaches the threshold. """

	if decision['highest'] < threshold:
		return 'new'

	if decision['gold_wins']:
		return 'linked'

	return 'wrong link'


def is_right(decision: dict, outcome: str) -> bool:
	""" Returns True if the outcome is the expected one: linked for a known mention, new for a new one. """

	if decision['known']:
		return outcome == 'linked'

	return outcome == 'new'


def outcomes(decisions: List[dict], threshold: float) -> Counter:
	""" Returns how many decisions are right, and how many known and new mentions get every outcome ("known linked", "new new"...). """

	counts = collections.Counter()
	for decision in decisions:
		kind	= 'known' if decision['known'] else 'new'
		outcome = outcome_of(decision, threshold)

		counts[kind] += 1
		counts[kind + ' ' + outcome] += 1
		counts['right'] += is_right(decision, outcome)

	return counts


def decision_scores(decisions: List[dict], threshold: float) -> dict:
	""" Returns the scores of the decisions: the share of right ones, of known mentions linked to their expected candidate and of new
	mentions found new, with their counts. """

	counts = outcomes(decisions, threshold)
	scores = {'decision': ratio(counts['right'], len(decisions)), 'decision_right': counts['right'], 'decision_mentions': len(decisions),
			  'linked': ratio(counts['known linked'], counts['known']), 'known_linked': counts['known linked'],
			  'known_wrong': counts['known wrong link'], 'known_missed': counts['known new'], 'known_mentions': counts['known'],
			  'detected': ratio(counts['new new'], counts['new']), 'new_detected': counts['new new'],
			  'new_wrong': counts['new wrong link'], 'new_mentions': counts['new']}

	return scores


def best_decision_threshold(decisions: List[dict]) -> Tuple[Optional[float], Optional[float]]:
	""" Returns the threshold, among the highest scores of the mentions, with the most right decisions, and their share. """

	best_threshold, best_right = None, -1
	for threshold in sorted({decision['highest'] for decision in decisions}):
		right = outcomes(decisions, threshold)['right']

		if right > best_right:
			best_threshold, best_right = threshold, right

	share = ratio(max(best_right, 0), len(decisions))

	return best_threshold, share


def mention_scores(mentions: List[dict], threshold: float) -> dict:
	""" Returns the scores of some mentions: top-1 and their decisions. """

	hits, total = top_1(mentions)
	scores		= {'top_1': ratio(hits, total), 'top_1_hits': hits, 'top_1_mentions': total}

	decisions = decisions_of(mentions)
	scores.update(decision_scores(decisions, threshold))

	return scores


def mention_scores_by(mentions: List[dict], field: str, threshold: float) -> Dict[str, dict]:
	""" Returns the scores of the mentions by the value of a field of their "meta" (none if it is a field of the pairs, such as
	"group"). """

	by_value = {}
	for mention in mentions:
		if field not in mention['meta']:
			continue

		value = str(mention['meta'][field])
		by_value.setdefault(value, []).append(mention)

	result = {}
	for value, value_mentions in by_value.items():
		result[value] = mention_scores(value_mentions, threshold)

	return result


def summary(mentions: List[dict], threshold: float, fields: List[str]) -> dict:
	""" Returns every score of the mentions of a run: of all the pairs and mentions, the best thresholds and the breakdown by every
	field. """

	pairs	= pairs_of(mentions)
	overall = scores_of(pairs, threshold)

	threshold_f1, f1 = best_threshold(pairs)
	overall.update({'best_threshold': threshold_f1, 'best_f1': f1})
	overall.update(mention_scores(mentions, threshold))

	threshold_decision, decision = best_decision_threshold(decisions_of(mentions))
	overall.update({'best_decision_threshold': threshold_decision, 'best_decision': decision})

	by = {}
	for field in fields:
		by[field] = breakdown(pairs, field, threshold)
		for value, scores in mention_scores_by(mentions, field, threshold).items():
			by[field][value].update(scores)

	return {'threshold': threshold, 'all': overall, 'by': by}
