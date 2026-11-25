""" Scores a model at every epoch of a fine-tune of finetune.py, on samples of mentions of match_node: the curves of the training.

A curve set is a sample of whole mentions of a dataset, with all their pairs:

- "train": mentions of the data the model is trained on, every pair of which is trained on (none is in the calibration slice), so
  that the model is scored on what it learns from,
- "val": mentions of a dataset the model never sees, such as the val split of ZESHEL, whose worlds are not in train.

Before the training (epoch 0) and at the end of every epoch, EpochScorer scores every pair of every set with the model as it is
(temperature 1, in evaluation mode) and keeps:

- in history.json, for every set: the log-loss, the accuracy, the mean confidence, the ECE and the Brier score of the pairs (those
  of `laya.train.evaluate_records`), with the mean training loss of Laya of the epoch,
- in curves/<set>__epoch_<n>.jsonl, the probability of yes of every pair, as a run of evaluation/match_node/ (its first line
  describes it, every other line is a mention with the score of every candidate), so that evaluation/match_node/score.py scores the
  decisions of every epoch.

The score of a pair is the probability of yes with the logits of the model and temperature 1, as `laya.train` scores its items: it may
differ slightly from that of MatchNodeLayaDecider, which applies the temperature of the checkpoint.
"""

import datetime, json, math, os, platform, random, time
from importlib.metadata import version
from typing import Dict, List, Tuple

from laya.train import evaluate_records

from data.match_node.dataset import Dataset, load_file
from training.match_node.export import create_rows


METRICS = ('loss', 'accuracy', 'mean_confidence', 'ece', 'brier')	# The metrics of the pairs kept in history.json.


class EpochScorer:
	""" Scores the model of a Finetuner on every curve set before the training and at the end of every epoch, and writes
	history.json and the scores of every epoch in a folder. """

	def __init__(self, finetuner, curve_sets: List[dict], folder: str):
		self.finetuner	= finetuner
		self.curve_sets = curve_sets
		self.folder		= folder
		self.history	= {'checkpoint': os.path.abspath(folder), 'sets': describe_sets(curve_sets), 'epochs': [], 'best': None}


	def score_epoch(self, epoch: int, train_loss) -> dict:
		""" Scores the model on every curve set after an epoch (0 is before the training), writes its scores and history.json and
		returns the entry of the epoch in the history. """

		entry = {'epoch': epoch, 'train_loss': train_loss}
		for curve_set in self.curve_sets:
			entry[curve_set['name']] = self._score_set(curve_set, epoch)

		self.history['epochs'].append(entry)
		self.write_history()

		return entry


	def mark_best(self, epoch: int, loss: float) -> None:
		""" Keeps the epoch of the best checkpoint and its log-loss in val. """

		self.history['best'] = {'epoch': epoch, 'val_loss': loss}
		self.write_history()


	def write_history(self) -> None:
		""" Writes history.json in the folder. """

		os.makedirs(self.folder, exist_ok = True)
		with open(os.path.join(self.folder, 'history.json'), 'w') as f:
			json.dump(self.history, f, indent = 2)


	def _score_set(self, curve_set: dict, epoch: int) -> dict:
		start	= time.time()
		records = self.finetuner.score_items(curve_set['items'])
		seconds = time.time() - start

		mentions = create_scored_mentions(curve_set['mentions'], records)
		run		 = self._describe_run(curve_set, epoch, seconds)
		path	 = os.path.join(self.folder, 'curves', '%s__epoch_%d.jsonl' % (curve_set['name'], epoch))
		write_run(path, run, mentions)

		summary = summarize(records)
		summary['seconds'] = round(seconds, 1)

		return summary


	def _describe_run(self, curve_set: dict, epoch: int, seconds: float) -> dict:
		checkpoint = os.path.basename(os.path.normpath(self.folder))
		name	   = '%s__%s__epoch_%d' % (checkpoint, curve_set['name'], epoch)
		conf	   = {'model': os.path.abspath(self.folder), 'epoch': epoch, 'temperature': 1.0, 'threshold': 0.5}
		decider	   = {'name': 'laya:%s@epoch_%d' % (checkpoint, epoch), 'class': 'EpochScorer', 'conf': conf}
		versions   = {'laya': version('laya'), 'python': platform.python_version()}
		now		   = datetime.datetime.now().isoformat(timespec = 'seconds')

		run = {'name': name, 'date': now, 'dataset': curve_set['info'], 'decider': decider, 'versions': versions,
			   'seconds': round(seconds, 1), 'truncated': curve_set['truncated'], 'errors': 0}

		return run


def create_train_set(finetuner, path: str, count: int, seed: int) -> dict:
	""" Returns the curve set "train": a sample of count mentions of the dataset of the training data (path) every pair of which is
	trained on, with the items the model is trained on. """

	dataset	 = load_file(path)
	trained	 = finetuner.index_trained_items()
	eligible = select_trained_mentions(dataset.mentions, trained)
	mentions = select_mentions(eligible, count, seed)
	items	 = collect_items(mentions, trained)

	return create_curve_set('train', dataset, mentions, items, finetuner)


def create_val_set(finetuner, path: str, count: int, seed: int) -> dict:
	""" Returns the curve set "val": a sample of count mentions of a dataset (all of them if it has fewer), with their items. """

	dataset	 = load_file(path)
	mentions = select_mentions(dataset.mentions, count, seed)
	sample	 = Dataset(dataset.name, dataset.path, dataset.ontology, mentions, dataset.breakdowns)
	rows	 = create_rows(sample)
	items	 = finetuner.create_row_items(rows)

	return create_curve_set('val', dataset, mentions, items, finetuner)


def create_curve_set(name: str, dataset: Dataset, mentions: List[dict], items: List[dict], finetuner) -> dict:
	""" Returns a curve set: its name, its mentions, the item of every pair (in the order of the mentions and their candidates),
	the description of the dataset for its runs and how many pairs the model cuts. """

	info = dataset.info()
	info['mentions'] = len(mentions)
	info['pairs']	 = len(items)
	info['sample']	 = True

	curve_set = {'name': name, 'mentions': mentions, 'items': items, 'info': info, 'truncated': finetuner.count_cut(items)}

	return curve_set


def describe_sets(curve_sets: List[dict]) -> Dict[str, dict]:
	""" Returns what history.json keeps of every curve set: its dataset, its mentions and its pairs. """

	described = {}
	for curve_set in curve_sets:
		info = curve_set['info']
		described[curve_set['name']] = {'dataset': info['name'], 'path': info['path'], 'sha256': info['sha256'],
										'mentions': info['mentions'], 'pairs': info['pairs']}

	return described


def select_trained_mentions(mentions: List[dict], trained: Dict[Tuple[str, str], dict]) -> List[dict]:
	""" Returns the mentions every pair of which is trained on. """

	selected = []
	for mention in mentions:
		if is_trained(mention, trained):
			selected.append(mention)

	return selected


def is_trained(mention: dict, trained: Dict[Tuple[str, str], dict]) -> bool:
	""" Returns True if every pair of the mention is trained on. """

	for candidate in mention['candidates']:
		key = (mention['mention_id'], candidate['node']['id'])
		if key not in trained:
			return False

	return True


def select_mentions(mentions: List[dict], count: int, seed: int) -> List[dict]:
	""" Returns count mentions chosen at random with a seed, in their order (all of them if there are no more than count). """

	if count >= len(mentions):
		return list(mentions)

	chosen = random.Random(seed).sample(range(len(mentions)), count)
	chosen.sort()

	selected = []
	for index in chosen:
		selected.append(mentions[index])

	return selected


def collect_items(mentions: List[dict], trained: Dict[Tuple[str, str], dict]) -> List[dict]:
	""" Returns the trained item of every pair of the mentions, in the order of the mentions and their candidates. """

	items = []
	for mention in mentions:
		for candidate in mention['candidates']:
			key = (mention['mention_id'], candidate['node']['id'])
			items.append(trained[key])

	return items


def summarize(records: list) -> dict:
	""" Returns the metrics of the pairs of the records of `laya.train.calibration_records`, with temperature 1. """

	evaluated = evaluate_records(records)

	summary = {}
	for metric in METRICS:
		summary[metric] = evaluated[metric]

	return summary


def yes_probability(logits) -> float:
	""" Returns the probability of yes of a pair from its logits (no, yes), with temperature 1. """

	difference = float(logits[0]) - float(logits[1])
	if difference >= 0:
		odds = math.exp(-difference)

		return odds/(1 + odds)

	return 1/(1 + math.exp(difference))


def create_scored_mentions(mentions: List[dict], records: list) -> List[dict]:
	""" Returns every mention with the score of every candidate, as a run of evaluation/match_node/ keeps them. The records are in
	the order of the mentions and their candidates. """

	scored = []
	index  = 0
	for mention in mentions:
		candidates = []
		for candidate in mention['candidates']:
			logits = records[index][1]
			score  = yes_probability(logits)
			candidates.append({'id': candidate['node']['id'], 'gold': candidate['gold'], 'score': score, 'meta': candidate['meta']})
			index += 1

		scored.append({'mention_id': mention['mention_id'], 'meta': mention['meta'], 'candidates': candidates})

	return scored


def write_run(path: str, run: dict, mentions: List[dict]) -> None:
	""" Writes a run as evaluation/match_node/run.py does: its description in the first line, and a mention in every other line. """

	os.makedirs(os.path.dirname(path), exist_ok = True)
	with open(path, 'w') as f:
		f.write(json.dumps({'run': run}) + '\n')
		for mention in mentions:
			f.write(json.dumps(mention) + '\n')
