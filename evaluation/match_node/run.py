""" Runs match_node of the Formalizer on every pair of a dataset, saves the scores of the Decider and prints the scores of the run.

Run it from the root of the repository:

	python -m evaluation.match_node.run [dataset] [--decider NAME] [--threshold T] [--out FILE] [-v]

The dataset is "cases" unless another one, or a .jsonl file, is given (see data.py), and the Decider is "names" unless another one is
given (see deciders.py). -v lists the pairs whose answer is wrong.

The run is saved as a .jsonl file (by default, runs/<dataset>__<decider>__<date>.jsonl): its first line describes the run (the
dataset and the hash of its file, the Decider and its configuration, the versions, the time, how many pairs the model cut and how many
calls failed), and every other line is a mention with the score of every candidate. Its scores are saved next to it
(<run>.metrics.json) and added to the history of the runs (runs/results.jsonl). score.py scores a saved run again, e.g., with
another threshold.
"""

import argparse, datetime, json, os, platform, subprocess, sys, time
from importlib.metadata import PackageNotFoundError, version
from typing import List, Optional

from mercury.graph.evidence import AgenticGraph, Decider, DeciderState, Formalizer

from evaluation.match_node import data, deciders, metrics, score


def build_formalizer(ontology: AgenticGraph, decider: Decider) -> Formalizer:
	""" Returns a ready Formalizer that uses the ontology and answers match_node with the Decider. """

	conf	   = {'ontology': 'ontology', 'match_node': decider.name}
	formalizer = Formalizer(schema = 'Formalizer', extra_args = conf)
	formalizer.tools['%s/%s' % (formalizer.id.split('/')[0], ontology.id)] = ontology

	decider.pilot(DeciderState.READY.value)
	formalizer.add_tool(decider)
	formalizer.pilot(100)

	return formalizer


def is_cut(logger: List[dict], start: int) -> bool:
	""" Returns True if the Decider logged a message since the event start: it only logs one when the model cuts its input. """

	for event in logger[start:]:
		if event['type'] == 'message':
			return True

	return False


def decide(formalizer: Formalizer, logger: List[dict], mention: dict, candidate: dict) -> dict:
	""" Returns the score of a candidate of a mention, with its expected answer and whether the model cut the input. The score is None
	if the call failed. """

	start	  = len(logger)
	arguments = {'mention': mention['mention'], 'node': candidate['node']}

	try:
		answer = formalizer.match_node(arguments)
		value  = answer['score']

	except Exception as e:
		print('%s vs %s failed: %s' % (mention['mention_id'], candidate['node']['id'], e))
		value = None

	result = {'id': candidate['node']['id'], 'gold': candidate['gold'], 'score': value, 'meta': candidate['meta']}
	if is_cut(logger, start):
		result['truncated'] = True

	return result


def run_mentions(formalizer: Formalizer, logger: List[dict], dataset: data.Dataset) -> List[dict]:
	""" Returns every mention of the dataset with the score of every candidate. """

	scored = []
	for mention in dataset.mentions:
		candidates = []
		for candidate in mention['candidates']:
			candidates.append(decide(formalizer, logger, mention, candidate))

		scored.append({'mention_id': mention['mention_id'], 'meta': mention['meta'], 'candidates': candidates})

	return scored


def count(mentions: List[dict], key: str, value) -> int:
	""" Returns how many candidates of the mentions have a value in a key. """

	total = 0
	for mention in mentions:
		for candidate in mention['candidates']:
			total += candidate.get(key) == value

	return total


def git(*args: str) -> str:
	""" Returns the output of a git command in the repository, or "" if it fails. """

	try:
		output = subprocess.run(['git'] + list(args), capture_output = True, text = True, check = True).stdout

	except (OSError, subprocess.CalledProcessError):
		return ''

	return output.strip()


def package_version(name: str) -> Optional[str]:
	""" Returns the installed version of a package, or None. """

	try:
		return version(name)

	except PackageNotFoundError:
		return None


def versions() -> dict:
	""" Returns the commit of the repository (and whether it has uncommitted changes) and the versions of Laya and Python. """

	commit = git('rev-parse', '--short', 'HEAD')
	dirty  = git('status', '--porcelain') != ''

	return {'mercury_graph': commit, 'dirty': dirty, 'laya': package_version('laya'), 'python': platform.python_version()}


def label_of(decider_name: str) -> str:
	""" Returns the Decider name as it is written in the name of a run (e.g., "laya-typed-decisions" for "laya/typed-decisions"). """

	return decider_name.replace('/', '-')


def save_run(path: str, run: dict, mentions: List[dict]) -> None:
	""" Saves a run: its description in the first line, and a mention with its scores in every other line. """

	os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok = True)
	with open(path, 'w') as f:
		f.write(json.dumps({'run': run}) + '\n')
		for mention in mentions:
			f.write(json.dumps(mention) + '\n')


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description = 'Runs match_node on a dataset and saves and prints its scores.')
	parser.add_argument('dataset', nargs = '?', default = 'cases', help = 'the dataset: %s or a .jsonl file' % ', '.join(data.CASES))
	parser.add_argument('--decider', default = 'names', help = 'names, laya or laya/<subfolder>')
	parser.add_argument('--threshold', type = float, default = deciders.THRESHOLD, help = 'the threshold of "same"')
	parser.add_argument('--out', help = 'the file of the run (by default, in runs/)')
	parser.add_argument('-v', action = 'store_true', help = 'list the pairs whose answer is wrong')

	return parser.parse_args()


def main() -> int:
	args	= parse_args()
	dataset = data.load(args.dataset)
	logger	= []
	decider = deciders.create(args.decider, args.threshold, logger)

	formalizer = build_formalizer(dataset.ontology, decider)
	if decider.meta['state'] != DeciderState.READY.value:
		print('The Decider is not ready (state %d).' % decider.meta['state'])

		return 1

	now		 = datetime.datetime.now()
	start	 = time.time()
	mentions = run_mentions(formalizer, logger, dataset)
	seconds	 = time.time() - start

	name = '%s__%s__%s' % (dataset.name, label_of(args.decider), now.strftime('%Y%m%d-%H%M%S'))
	path = args.out if args.out is not None else os.path.join(score.RUNS, name + '.jsonl')
	run	 = {'name': name, 'date': now.isoformat(timespec = 'seconds'), 'dataset': dataset.info(),
			'decider': deciders.info(args.decider, decider), 'versions': versions(), 'seconds': round(seconds, 1),
			'truncated': count(mentions, 'truncated', True), 'errors': count(mentions, 'score', None)}

	save_run(path, run, mentions)

	scores = metrics.summary(mentions, args.threshold, dataset.breakdowns)
	score.print_scores(run, scores)
	if args.v:
		score.print_errors(run, mentions, args.threshold)

	score.save(path, run, scores)
	print('Saved in %s.' % path)

	return 0


if __name__ == '__main__':
	sys.exit(main())
