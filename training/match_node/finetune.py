""" Fine-tunes a Laya model on data written by export.py, with the steps and the pieces of `laya.train.finetune`, and scores it at
every epoch (see curves.py).

Run it from the root of the repository:

	python -m training.match_node.finetune [data.jsonl] [--base MODEL] [--out FOLDER] [--epochs N] [--limit N]
		[--micro-batch N] [--checkpointing] [--device DEVICE] [--curve-train DATASET] [--curve-val DATASET]
		[--curve-mentions N] [--no-curves] [--keep-best]

The data is training/match_node/laya_data/zeshel_train.jsonl unless another file is given, and the base model is
convaiinnovations/laya, the model of MatchNodeLayaDecider. --limit trains on the first N rows only (to measure the time of a run
before a full one) and --epochs changes the number of epochs (4 by default).

A fine-tune follows the steps of `laya.train.finetune`, with the same pieces of Laya, so that it trains the same model:

1. load the base model and move it to the device,
2. read the rows and turn them into items (the tokenized state, the question and the target of every row),
3. hold out the calibration slice (10% of the items, 400 at most) before any training,
4. train with `laya.train.train_model`, which calls Finetuner at the end of every epoch,
5. score the calibration slice and fit the temperature and the abstention thresholds of Laya on it,
6. save the checkpoint with the questions of the data.

Unlike `laya.train.finetune`, it does not save checkpoint_latest/, nor compare the model before and after on an --eval file: at the
end of every epoch, curves.py scores 500 mentions of the data trained on (--curve-train, the dataset the data was exported from) and
500 of a dataset the model never sees (--curve-val), and writes history.json and the scores of every epoch in the checkpoint.
--curve-mentions changes how many mentions every set has, and --no-curves trains without scoring. With --keep-best, the checkpoint of
the epoch with the lowest log-loss in val is also saved, calibrated, in best/.

--micro-batch and --checkpointing need less memory for the same training: --micro-batch N trains on N rows at a time and adds up
EFFECTIVE_BATCH/N of them before every update, so that every update is still on EFFECTIVE_BATCH rows, and --checkpointing computes
the activations of the model again instead of keeping them, which is slower. Without them, Laya needs about 19 GB on Apple Silicon.

The checkpoint is saved by default in checkpoints/<data>__<date>/ (which is not committed), where `laya.load()` and
MatchNodeLayaDecider ("model": <the folder>) load it, with finetune.json: the arguments, the data and the SHA-256 of its file, the
versions, the time and the summary of the training.
"""

import argparse, datetime, json, os, platform, sys, time, warnings
from dataclasses import asdict
from importlib.metadata import version
from typing import Dict, List, Optional, Tuple

from laya import train as laya_train
from laya.common import uses_parallel_layout

from data.match_node.dataset import ROOT, sha256_of
from training.match_node import curves


HERE		= os.path.dirname(os.path.abspath(__file__))
DATA		= os.path.join(HERE, 'laya_data', 'zeshel_train.jsonl')
OUT			= os.path.join(HERE, 'checkpoints')
BASE		= 'convaiinnovations/laya'
CURVE_TRAIN = os.path.join(ROOT, 'data', 'match_node', 'zeshel_data', 'zeshel_train.jsonl')
CURVE_VAL	= os.path.join(ROOT, 'data', 'match_node', 'zeshel_data', 'zeshel_val.jsonl')
CURVE_SEED	= 0		# The seed of the mentions of the curve sets.

EFFECTIVE_BATCH = 64	# The rows of every update of the model: Laya's default (micro_batch 8 x grad_accum 8).


class Finetuner:
	""" Fine-tunes a Laya model as `laya.train.finetune` does: it loads the base model, turns rows into items, holds out the
	calibration slice, trains, calibrates and saves. At the end of every epoch, it scores the model with an EpochScorer and, if asked,
	saves the best checkpoint. """

	def __init__(self, base: str, config, device: str):
		config.validate()

		self.config = config
		self.device = laya_train.resolve_device(device)

		model, tok, cfg = laya_train.load_checkpoint(base)
		model.to(self.device)

		if config.option_layout is not None:
			cfg = dict(cfg, option_layout = config.option_layout)

		self.model		  = model
		self.tok		  = tok
		self.cfg		  = cfg
		self.max_len	  = config.max_len or cfg.get('max_len', 512)
		self.head_max_len = config.head_max_len or cfg.get('head_max_len', 192)
		self.parallel	  = uses_parallel_layout(cfg)

		self.rows		 = []
		self.items		 = []
		self.skipped	 = {}
		self.train_index = []
		self.calib_items = []
		self.scorer		 = None
		self.best_folder = None
		self.best		 = None


	def prepare(self, rows: List[dict]) -> None:
		""" Turns the rows into items and holds out the calibration slice, as `laya.train.finetune` does. """

		items, skipped = laya_train.items_from_rows(self.tok, rows, self.max_len, self.head_max_len,
													label_smoothing = self.config.label_smoothing)
		if len(items) == 0:
			raise ValueError('The data produced no training items (skipped: %r).' % skipped)

		indexes = list(range(len(items)))
		train_index, calib_index = laya_train.split_calibration(indexes, self.config.calib_max, self.config.calib_frac,
															   self.config.calib_seed)

		self.rows		 = rows
		self.items		 = items
		self.skipped	 = skipped
		self.train_index = train_index
		self.calib_items = self._select_items(calib_index)


	def create_row_items(self, rows: List[dict]) -> List[dict]:
		""" Returns the item of every row, in order; it fails if a row gives no item. """

		items, skipped = laya_train.items_from_rows(self.tok, rows, self.max_len, self.head_max_len)
		if len(items) != len(rows):
			raise ValueError('%d rows gave %d items (skipped: %r): the curves need one item per row.' % (len(rows), len(items), skipped))

		return items


	def index_trained_items(self) -> Dict[Tuple[str, str], dict]:
		""" Returns the trained item of every pair, by its mention and its candidate ("meta" of the rows of export.py). """

		if len(self.items) != len(self.rows):
			raise ValueError('%d rows gave %d items: the curves need one item per row.' % (len(self.rows), len(self.items)))

		trained = {}
		for index in self.train_index:
			meta = self.rows[index]['meta']
			trained[(meta['mention_id'], meta['id'])] = self.items[index]

		return trained


	def score_items(self, items: List[dict]) -> list:
		""" Returns the records of the items with the model as it is: (type, logits, target, options), in order. """

		records = laya_train.calibration_records(self.model, self.tok, items, self.device, self.max_len, self.head_max_len,
												 parallel = self.parallel)

		return records


	def count_cut(self, items: List[dict]) -> int:
		""" Returns how many items do not fit the model: their sequence reaches max_len, so their state is cut. """

		cut = 0
		for item in items:
			encoded = laya_train.encode_item(self.tok, item, self.max_len, self.head_max_len, parallel = self.parallel)
			cut += len(encoded['ids']) >= self.max_len

		return cut


	def train(self, scorer: Optional[curves.EpochScorer] = None, best_folder: Optional[str] = None) -> List[float]:
		""" Trains the model on the training items, scoring it before the training and at the end of every epoch with the scorer, if
		any, and saving the best checkpoint in best_folder, if any. Returns the mean training loss of every epoch. """

		self.scorer		 = scorer
		self.best_folder = best_folder
		if scorer is not None:
			scorer.score_epoch(0, None)

		train_items = self._select_items(self.train_index)
		print('train items %d, calibration items %d, skipped %r, device %s' % (len(train_items), len(self.calib_items), self.skipped,
																				self.device), flush = True)
		print(laya_train.update_budget_message(len(train_items), self.config), flush = True)

		history = laya_train.train_model(self.model, self.tok, train_items, self.config, self.device, self.max_len,
										 self.head_max_len, on_epoch_end = self.end_epoch, parallel = self.parallel)

		return history


	def end_epoch(self, epoch: int, loss: float) -> None:
		""" Called by `laya.train.train_model` at the end of every epoch (from 0): scores the model, saves it if it is the best and
		leaves it ready to train again. """

		if self.scorer is None:
			return

		entry = self.scorer.score_epoch(epoch + 1, loss)
		self._print_epoch(entry)
		self._keep_if_best(entry)
		self._restore_training_mode()


	def calibrate(self) -> dict:
		""" Scores the calibration slice and fits the temperature and the abstention thresholds on it, as `laya.train.finetune`
		does. """

		records = self.score_items(self.calib_items)
		message = laya_train.prior_collapse_message(records)
		if message:
			warnings.warn(message, RuntimeWarning)

		fitted		= laya_train.fit_temperature_map(records)
		calibration = laya_train.calibration_report(records, fitted['temperature'])
		warn_calibration(calibration)
		thresholds	= self._fit_abstention_thresholds(records, fitted)

		calibrated = {'fitted': fitted, 'calibration': calibration, 'abstention_thresholds': thresholds}

		return calibrated


	def save(self, folder: str, calibrated: dict) -> None:
		""" Saves the checkpoint in the layout `laya.load` reads, with the configuration of `laya.train.finetune` and the questions
		of the data. """

		fitted = calibrated['fitted']
		report = {'note': 'Scored at every epoch by training/match_node/curves.py: see history.json.',
				  'calibration': calibrated['calibration'], 'abstention_thresholds': calibrated['abstention_thresholds'],
				  'training': asdict(self.config)}

		cfg = dict(self.cfg, max_len = self.max_len, head_max_len = self.head_max_len, fine_tuned = True,
				   temperature = fitted['temperature'])
		cfg.pop('temperature_by_options', None)
		if fitted['temperature_by_options']:
			cfg['temperature_by_options'] = fitted['temperature_by_options']

		training = dict(cfg.get('training') or {}, laya_train = asdict(self.config), laya_train_calibration = calibrated['calibration'],
						train_report = report)
		if calibrated['abstention_thresholds']:
			training['abstention_thresholds'] = calibrated['abstention_thresholds']

		cfg['training'] = training

		laya_train.save_checkpoint(self.model, self.tok, cfg, folder)
		write_json(os.path.join(folder, 'questions.json'), collect_questions(self.rows))
		write_json(os.path.join(folder, 'train_report.json'), report)


	def _select_items(self, indexes: List[int]) -> List[dict]:
		selected = []
		for index in indexes:
			selected.append(self.items[index])

		return selected


	def _print_epoch(self, entry: dict) -> None:
		line = 'epoch %d: training loss %.4f' % (entry['epoch'], entry['train_loss'])
		for curve_set in self.scorer.curve_sets:
			name  = curve_set['name']
			line += ', %s log-loss %.4f accuracy %.4f' % (name, entry[name]['loss'], entry[name]['accuracy'])

		print(line, flush = True)


	def _keep_if_best(self, entry: dict) -> None:
		if self.best_folder is None:
			return

		loss	= entry['val']['loss']
		is_best = self.best is None or loss < self.best
		if not is_best:
			return

		self.best = loss
		self.save(self.best_folder, self.calibrate())
		self.scorer.mark_best(entry['epoch'], loss)
		print('epoch %d is the best so far: saved in %s' % (entry['epoch'], self.best_folder), flush = True)


	def _restore_training_mode(self) -> None:
		# Scoring puts the model in evaluation mode; `train_model` sets the training mode only before the first epoch.
		self.model.train()
		if self.config.freeze_encoder:
			self.model.encoder.eval()


	def _fit_abstention_thresholds(self, records: list, fitted: dict) -> dict:
		try:
			thresholds = laya_train.fit_abstention_thresholds(records, temperature = fitted['temperature'],
															  temperature_by_options = fitted['temperature_by_options'],
															  target_error = self.config.target_error,
															  min_bucket_n = self.config.min_abstain_n)

		except Exception as e:
			warnings.warn('Failed to fit abstention thresholds: %s' % e, RuntimeWarning)
			thresholds = {}

		return thresholds


def warn_calibration(calibration: dict) -> None:
	""" Warns of every issue of the calibration, as `laya.train.finetune` does. """

	for name, entry in calibration.items():
		for issue in entry['issues']:
			warnings.warn('%s calibration: %s' % (name, issue), RuntimeWarning)


def collect_questions(rows: List[dict]) -> dict:
	""" Returns the first definition of every question of the rows, as `laya.train.finetune` saves them in questions.json. """

	questions = {}
	for row in rows:
		for question_id, definition in row.get('questions', {}).items():
			if question_id not in questions:
				questions[question_id] = definition

	return questions


def write_json(path: str, data) -> None:
	""" Writes data as JSON. """

	with open(path, 'w') as f:
		json.dump(data, f, indent = 2, default = str)


def read_rows(path: str, limit: Optional[int]) -> List[dict]:
	""" Returns the rows of the data, only the first limit ones if limit is given. """

	rows = laya_train.read_jsonl(path)
	if limit is not None:
		rows = rows[:limit]

	return rows


def create_config(args: argparse.Namespace):
	""" Returns the training configuration of Laya: its defaults, with the epochs, the micro-batch and the gradient checkpointing of
	the arguments. """

	config = laya_train.TrainConfig()
	if args.epochs is not None:
		config.epochs = args.epochs

	if args.micro_batch is not None:
		config.micro_batch = args.micro_batch
		config.grad_accum  = EFFECTIVE_BATCH//args.micro_batch

	if args.checkpointing:
		config.gradient_checkpointing = True

	return config


def create_scorer(finetuner: Finetuner, args: argparse.Namespace, out: str) -> Optional[curves.EpochScorer]:
	""" Returns the EpochScorer of the curve sets of the arguments, or None with --no-curves. """

	if args.no_curves:
		return None

	train_set = curves.create_train_set(finetuner, args.curve_train, args.curve_mentions, CURVE_SEED)
	val_set	  = curves.create_val_set(finetuner, args.curve_val, args.curve_mentions, CURVE_SEED)
	scorer	  = curves.EpochScorer(finetuner, [train_set, val_set], out)

	return scorer


def summarize(finetuner: Finetuner, history: List[float], calibrated: dict) -> dict:
	""" Returns the summary of the training, as that of `laya.train.finetune`. """

	fitted	= calibrated['fitted']
	summary = {'train_items': len(finetuner.train_index), 'calibration_items': len(finetuner.calib_items),
			   'skipped': finetuner.skipped, 'epoch_loss': history, 'temperature': fitted['temperature'],
			   'temperature_by_options': fitted['temperature_by_options'], 'n_by_bucket': fitted['n_by_bucket'],
			   'calibration': calibrated['calibration'], 'abstention_thresholds': calibrated['abstention_thresholds']}

	return summary


def write_info(out: str, args: argparse.Namespace, seconds: float, summary: dict, best: Optional[dict]) -> None:
	""" Writes finetune.json in the checkpoint: how it was trained, the summary of the training and its best epoch. """

	data   = {'path': os.path.abspath(args.data), 'sha256': sha256_of(args.data), 'limit': args.limit}
	curve_sets = None
	if not args.no_curves:
		curve_sets = {'train': args.curve_train, 'val': args.curve_val, 'mentions': args.curve_mentions, 'seed': CURVE_SEED}

	info = {'base': args.base, 'data': data, 'epochs': args.epochs, 'device': args.device, 'micro_batch': args.micro_batch,
			'checkpointing': args.checkpointing, 'curves': curve_sets, 'keep_best': args.keep_best, 'best': best,
			'versions': {'laya': version('laya'), 'python': platform.python_version()}, 'seconds': round(seconds, 1),
			'summary': summary}

	write_json(os.path.join(out, 'finetune.json'), info)


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description = 'Fine-tunes a Laya model on data written by export.py.')
	parser.add_argument('data', nargs = '?', default = DATA, help = 'the data (by default, laya_data/zeshel_train.jsonl)')
	parser.add_argument('--base', default = BASE, help = 'the model to fine-tune (by default, %s)' % BASE)
	parser.add_argument('--out', help = 'the folder of the checkpoint (by default, checkpoints/<data>__<date>/)')
	parser.add_argument('--epochs', type = int, help = 'the number of epochs (by default, that of Laya: 4)')
	parser.add_argument('--limit', type = int, help = 'train on the first N rows only')
	parser.add_argument('--micro-batch', type = int, choices = [1, 2, 4, 8, 16],
						help = 'rows at a time, with the same %d rows per update (by default, that of Laya: 8)' % EFFECTIVE_BATCH)
	parser.add_argument('--checkpointing', action = 'store_true', help = 'compute the activations again instead of keeping them')
	parser.add_argument('--device', default = 'auto', help = 'the device: auto, cpu, mps or cuda (by default, auto)')
	parser.add_argument('--curve-train', default = CURVE_TRAIN, help = 'the dataset the data was exported from')
	parser.add_argument('--curve-val', default = CURVE_VAL, help = 'a dataset the model never sees (by default, zeshel_val)')
	parser.add_argument('--curve-mentions', type = int, default = 500, help = 'the mentions of every curve set (by default, 500)')
	parser.add_argument('--no-curves', action = 'store_true', help = 'train without scoring the model at every epoch')
	parser.add_argument('--keep-best', action = 'store_true', help = 'also save the epoch with the lowest log-loss in val in best/')

	args = parser.parse_args()
	if args.keep_best and args.no_curves:
		parser.error('--keep-best needs the curves.')

	return args


def main() -> int:
	args = parse_args()

	name = '%s__%s' % (os.path.splitext(os.path.basename(args.data))[0], datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
	out	 = args.out if args.out is not None else os.path.join(OUT, name)
	best = os.path.join(out, 'best') if args.keep_best else None

	start	  = time.time()
	finetuner = Finetuner(args.base, create_config(args), args.device)
	finetuner.prepare(read_rows(args.data, args.limit))

	scorer	   = create_scorer(finetuner, args, out)
	history	   = finetuner.train(scorer, best)
	calibrated = finetuner.calibrate()
	finetuner.save(out, calibrated)
	seconds	   = time.time() - start

	best_epoch = scorer.history['best'] if scorer is not None else None
	write_info(out, args, seconds, summarize(finetuner, history, calibrated), best_epoch)
	print('%.1f seconds. Saved in %s.' % (seconds, out))

	return 0


if __name__ == '__main__':
	sys.exit(main())
