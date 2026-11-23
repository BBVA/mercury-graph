""" Scores the runs of match_node saved by run.py, without running any model.

Run it from the root of the repository:

	python -m evaluation.match_node.score <run.jsonl> [<run.jsonl> ...] [--threshold T] [--by FIELD ...] [--errors] [--save]
	python -m evaluation.match_node.score --history

It prints the scores of every run (see metrics.py), with the threshold of its Decider unless --threshold is given, broken down by the
fields of --by (by default, those of its dataset). --errors lists the pairs whose answer is wrong and the mentions whose decision is wrong. --save keeps the scores next to the
run (<run>.metrics.json) and adds them to the history of the runs (runs/results.jsonl). --history prints that history.
"""

import argparse, json, os, sys
from typing import List, Optional, Tuple

from evaluation.match_node import data, metrics


RUNS	= os.path.join(os.path.dirname(os.path.abspath(__file__)), 'runs')
HISTORY = os.path.join(RUNS, 'results.jsonl')
ORDER	= {'group': data.GROUPS}		# The order of the values of a field in the breakdown; other fields are sorted.


def load_run(path: str) -> Tuple[dict, List[dict]]:
	""" Returns the description of a run (its first line) and its mentions with their scores (the other lines). """

	with open(path) as f:
		lines = [json.loads(line) for line in f if line.strip() != '']

	return lines[0]['run'], lines[1:]


def metrics_path(path: str) -> str:
	""" Returns the file of the scores of a run. """

	return os.path.splitext(path)[0] + '.metrics.json'


def save(path: str, run: dict, scores: dict) -> None:
	""" Saves the scores of a run next to it and adds them to the history of the runs. """

	scores = dict(scores, run = run['name'])
	with open(metrics_path(path), 'w') as f:
		json.dump(scores, f, indent = 2)

	row = history_row(run, scores)
	os.makedirs(os.path.dirname(HISTORY), exist_ok = True)
	with open(HISTORY, 'a') as f:
		f.write(json.dumps(row) + '\n')


def history_row(run: dict, scores: dict) -> dict:
	""" Returns the row of a run in the history: what was run and its main scores. """

	overall = scores['all']
	row		= {'run': run['name'], 'date': run['date'], 'dataset': run['dataset']['name'], 'sha256': run['dataset']['sha256'],
			   'decider': run['decider']['name'], 'threshold': scores['threshold']}

	for key in ('pairs', 'precision', 'recall', 'f1', 'auc', 'best_threshold', 'best_f1', 'top_1', 'decision', 'best_decision_threshold',
				'best_decision'):
		row[key] = overall.get(key)

	return row


def ordered(field: str, values: List[str]) -> List[str]:
	""" Returns the values of a field in the order they are printed. """

	if field not in ORDER:
		return sorted(values)

	known = [value for value in ORDER[field] if value in values]
	other = sorted(value for value in values if value not in ORDER[field])

	return known + other


def number(value: Optional[float], width: int) -> str:
	""" Returns a score with two decimals, or "-" if there is none, right-aligned in a width. """

	text = '-' if value is None else '%.2f' % value

	return text.rjust(width)


HEADER = '%-20s %6s %6s %9s %7s %6s %6s %6s %8s'
TITLES = ('pairs', 'right', 'precision', 'recall', 'F1', 'AUC', 'top-1', 'decision')


def score_line(label: str, scores: dict) -> str:
	""" Returns the line of a table for the scores of some pairs, with "-" for the scores they do not have (e.g., the AUC of pairs that
	are all positive, or top-1 and decision by a field of the pairs). """

	values = [number(scores.get('precision'), 9), number(scores.get('recall'), 7), number(scores.get('f1'), 6),
			  number(scores.get('auc'), 6), number(scores.get('top_1'), 6), number(scores.get('decision'), 8)]

	return '%-20s %6d %6d ' % (label, scores['pairs'], scores['right']) + ' '.join(values)


def print_scores(run: dict, scores: dict) -> None:
	""" Prints the scores of a run: by every field of the breakdown, of all the pairs and mentions, and the best thresholds. """

	dataset = run['dataset']
	print('Run %s: Decider %s, threshold %s, dataset %s (%d pairs of %d mentions).' % (run['name'], run['decider']['name'],
		  scores['threshold'], dataset['name'], dataset['pairs'], dataset['mentions']))

	for field, by_value in scores['by'].items():
		print('\n' + HEADER % ((field,) + TITLES))
		for value in ordered(field, list(by_value)):
			print(score_line(value, by_value[value]))

	overall = scores['all']
	print('\n' + HEADER % (('',) + TITLES))
	print(score_line('all', overall))

	top_1 = number(overall['top_1'], 0)
	print('\nbest threshold %.3f (F1 %.2f)   top-1 %d/%d (%s)' % (overall['best_threshold'], overall['best_f1'], overall['top_1_hits'],
		  overall['top_1_mentions'], top_1))
	print_decisions(overall)

	print('%.1f seconds, %d pairs cut by the model, %d errors.' % (run['seconds'], run['truncated'], run['errors']))


def print_decisions(overall: dict) -> None:
	""" Prints the decisions of the mentions: how many are right, what the known and the new ones get, and the best threshold. """

	print('decision %d/%d (%s): known linked %d/%d (%s; wrong link %d, missed %d), new detected %d/%d (%s; wrong link %d)' % (
		  overall['decision_right'], overall['decision_mentions'], number(overall['decision'], 0), overall['known_linked'],
		  overall['known_mentions'], number(overall['linked'], 0), overall['known_wrong'], overall['known_missed'],
		  overall['new_detected'], overall['new_mentions'], number(overall['detected'], 0), overall['new_wrong']))

	if overall['best_decision_threshold'] is not None:
		print('best decision threshold %.3f (%.2f)' % (overall['best_decision_threshold'], overall['best_decision']))


def print_errors(run: dict, mentions: List[dict], threshold: float) -> None:
	""" Prints the pairs whose answer is wrong and the mentions whose decision is wrong, as written in the dataset of the run. """

	dataset = data.load(data.source_of(run['dataset']))
	if dataset.sha256 != run['dataset']['sha256']:
		print('\nThe dataset %s has changed since the run: its errors are not listed.' % dataset.name)

		return

	print_pair_errors(dataset, mentions, threshold)
	print_decision_errors(dataset, mentions, threshold)


def print_pair_errors(dataset: data.Dataset, mentions: List[dict], threshold: float) -> None:
	""" Prints the pairs whose answer is wrong. """

	print('\nPairs:')
	for pair in metrics.pairs_of(mentions):
		same = pair['score'] >= threshold
		if same == pair['gold']:
			continue

		kind	= 'missed' if pair['gold'] else 'wrong '
		mention = data.find(dataset, pair['mention_id'])['mention']['mention']
		group	= pair['meta'].get('group', '')
		print('%-8s %s %-18s %-24s vs %-45s score %.3f' % (pair['mention_id'], kind, group, '"%s"' % mention, pair['id'], pair['score']))


def top_candidate(mention: dict) -> dict:
	""" Returns the first candidate of a mention with the highest score. """

	candidates = metrics.scored(mention['candidates'])
	highest	   = max(candidate['score'] for candidate in candidates)
	for candidate in candidates:
		if candidate['score'] == highest:
			return candidate


def print_decision_errors(dataset: data.Dataset, mentions: List[dict], threshold: float) -> None:
	""" Prints the mentions whose decision is wrong, with the candidate with the highest score. """

	print('\nDecisions:')
	for mention in mentions:
		decision = metrics.decision_of(mention)
		if decision is None:
			continue

		outcome = metrics.outcome_of(decision, threshold)
		if metrics.is_right(decision, outcome):
			continue

		kind	= 'known' if decision['known'] else 'new'
		text	= data.find(dataset, mention['mention_id'])['mention']['mention']
		top		= top_candidate(mention)
		print('%-8s %-5s %-10s %-24s top %-45s score %.3f' % (mention['mention_id'], kind, outcome, '"%s"' % text, top['id'],
			  top['score']))


def print_history() -> None:
	""" Prints the history of the runs, one line per run. """

	if not os.path.exists(HISTORY):
		print('No runs have been saved yet.')

		return

	with open(HISTORY) as f:
		rows = [json.loads(line) for line in f if line.strip() != '']

	print('%-19s %-12s %-26s %5s %6s %5s %5s %5s %5s %13s %5s %5s %13s' % ('date', 'dataset', 'decider', 'thr', 'pairs', 'P', 'R', 'F1',
		  'AUC', 'best (F1)', 'top-1', 'dec', 'best (dec)'))
	for row in rows:
		print(history_line(row))


def history_line(row: dict) -> str:
	""" Returns the line of a run in the history ("-" for the scores of the decision of the runs saved before it existed). """

	best	 = '%.3f (%.2f)' % (row['best_threshold'], row['best_f1'])
	values	 = ' '.join(number(row[key], 5) for key in ('precision', 'recall', 'f1', 'auc'))
	decision = number(row.get('decision'), 5)

	best_decision = '-'
	if row.get('best_decision_threshold') is not None:
		best_decision = '%.3f (%.2f)' % (row['best_decision_threshold'], row['best_decision'])

	line = '%-19s %-12s %-26s %5s %6d %s %13s %s %s %13s' % (row['date'], row['dataset'], row['decider'], row['threshold'], row['pairs'],
		   values, best, number(row['top_1'], 5), decision, best_decision)

	return line


def check_same_dataset(runs: List[dict]) -> None:
	""" Warns if the runs are not on the same dataset (the same file), since their scores cannot be compared. """

	hashes = {run['dataset']['sha256'] for run in runs}
	if len(hashes) > 1:
		print('Warning: these runs are not on the same dataset, their scores cannot be compared.\n')


def score_run(path: str, args: argparse.Namespace) -> dict:
	""" Prints (and saves, with --save) the scores of a run, and returns its description. """

	run, mentions = load_run(path)

	threshold = args.threshold if args.threshold is not None else run['decider']['conf']['threshold']
	fields	  = args.by if args.by else run['dataset']['breakdowns']
	scores	  = metrics.summary(mentions, threshold, fields)

	print_scores(run, scores)
	if args.errors:
		print_errors(run, mentions, threshold)

	if args.save:
		save(path, run, scores)

	return run


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description = 'Scores the runs of match_node saved by run.py.')
	parser.add_argument('runs', nargs = '*', help = 'the .jsonl files of the runs')
	parser.add_argument('--threshold', type = float, help = 'the threshold of "same" (by default, that of the Decider of the run)')
	parser.add_argument('--by', action = 'append', help = 'a field of "meta" to break the scores down by (it can be repeated)')
	parser.add_argument('--errors', action = 'store_true', help = 'list the pairs whose answer is wrong')
	parser.add_argument('--save', action = 'store_true', help = 'save the scores next to the run and add them to the history')
	parser.add_argument('--history', action = 'store_true', help = 'print the history of the runs')

	return parser.parse_args()


def main() -> int:
	args = parse_args()
	if args.history:
		print_history()

		return 0

	runs = []
	for path in args.runs:
		if len(runs) > 0:
			print('\n' + '-'*100 + '\n')

		runs.append(score_run(path, args))

	check_same_dataset(runs)

	return 0


if __name__ == '__main__':
	sys.exit(main())
