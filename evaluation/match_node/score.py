""" Scores the runs of match_node saved by run.py, without running any model.

Run it from the root of the repository:

	python -m evaluation.match_node.score <run.jsonl> [<run.jsonl> ...] [--threshold T] [--by FIELD ...] [--errors] [--save]
	python -m evaluation.match_node.score --history

It prints the scores of every run (see metrics.py), with the threshold of its Decider unless --threshold is given, broken down by the
fields of --by (by default, those of its dataset). --errors lists the pairs whose answer is wrong. --save keeps the scores next to the
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

	for key in ('pairs', 'precision', 'recall', 'f1', 'auc', 'best_threshold', 'best_f1', 'top_1'):
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


def score_line(label: str, scores: dict) -> str:
	""" Returns the line of a table for the scores of some pairs. """

	line = '%-20s %6d %6d' % (label, scores['pairs'], scores['right'])
	if 'auc' not in scores:
		return line

	values = [number(scores['precision'], 9), number(scores['recall'], 7), number(scores['f1'], 6), number(scores['auc'], 6)]

	return line + ' ' + ' '.join(values)


def print_scores(run: dict, scores: dict) -> None:
	""" Prints the scores of a run: by every field of the breakdown, of all the pairs, the best threshold and top-1. """

	dataset = run['dataset']
	print('Run %s: Decider %s, threshold %s, dataset %s (%d pairs of %d mentions).' % (run['name'], run['decider']['name'],
		  scores['threshold'], dataset['name'], dataset['pairs'], dataset['mentions']))

	for field, by_value in scores['by'].items():
		print('\n%-20s %6s %6s %9s %7s %6s %6s' % (field, 'pairs', 'right', 'precision', 'recall', 'F1', 'AUC'))
		for value in ordered(field, list(by_value)):
			print(score_line(value, by_value[value]))

	overall = scores['all']
	print('\n%-20s %6s %6s %9s %7s %6s %6s' % ('', 'pairs', 'right', 'precision', 'recall', 'F1', 'AUC'))
	print(score_line('all', overall))

	top_1 = number(overall['top_1'], 0)
	print('\nbest threshold %.3f (F1 %.2f)   top-1 %d/%d (%s)' % (overall['best_threshold'], overall['best_f1'], overall['top_1_hits'],
		  overall['top_1_mentions'], top_1))

	print('%.1f seconds, %d pairs cut by the model, %d errors.' % (run['seconds'], run['truncated'], run['errors']))


def print_errors(run: dict, mentions: List[dict], threshold: float) -> None:
	""" Prints the pairs whose answer is wrong, with the mention as written in the dataset of the run. """

	dataset = data.load(data.source_of(run['dataset']))
	if dataset.sha256 != run['dataset']['sha256']:
		print('\nThe dataset %s has changed since the run: its errors are not listed.' % dataset.name)

		return

	print()
	for pair in metrics.pairs_of(mentions):
		same = pair['score'] >= threshold
		if same == pair['gold']:
			continue

		kind	= 'missed' if pair['gold'] else 'wrong '
		mention = data.find(dataset, pair['mention_id'])['mention']['mention']
		group	= pair['meta'].get('group', '')
		print('%-8s %s %-18s %-24s vs %-45s score %.3f' % (pair['mention_id'], kind, group, '"%s"' % mention, pair['id'], pair['score']))


def print_history() -> None:
	""" Prints the history of the runs, one line per run. """

	if not os.path.exists(HISTORY):
		print('No runs have been saved yet.')

		return

	with open(HISTORY) as f:
		rows = [json.loads(line) for line in f if line.strip() != '']

	print('%-19s %-12s %-26s %5s %6s %5s %5s %5s %5s %13s %5s' % ('date', 'dataset', 'decider', 'thr', 'pairs', 'P', 'R', 'F1', 'AUC',
		  'best (F1)', 'top-1'))
	for row in rows:
		best   = '%.3f (%.2f)' % (row['best_threshold'], row['best_f1'])
		values = ' '.join(number(row[key], 5) for key in ('precision', 'recall', 'f1', 'auc'))
		print('%-19s %-12s %-26s %5s %6d %s %13s %s' % (row['date'], row['dataset'], row['decider'], row['threshold'], row['pairs'],
			  values, best, number(row['top_1'], 5)))


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
