""" Exports a dataset of match_node as data to fine-tune a Laya model on, in the JSONL format of `laya.train` (laya-train --data).

Run it from the root of the repository:

	python -m training.match_node.export <dataset.jsonl> [--out FILE]

The dataset is a .jsonl file in the format of data/match_node/dataset.py (e.g., data/match_node/zeshel_data/zeshel_train.jsonl).
Every pair of the dataset is a row:

	{"state": <the state of the pair>, "questions": {"same": ...}, "expected": {"same": <gold>}, "meta": {"mention_id": ..., "id": ...}}

The state and the questions are those MatchNodeLayaDecider asks the model, created by MatchNodeLayaPrompter from the arguments the
Formalizer gives the Decider (with the definition of the type of the mention), so that the model is trained on the same input it is
asked. "meta" tells the pair of every row; Laya does not read it. The file is written by default in laya_data/ (which is not committed)
as <dataset>.jsonl.
"""

import argparse, json, os, sys
from typing import List

from mercury.graph.evidence import Decider, Formalizer
from mercury.graph.evidence.deciders import MatchNodeLayaPrompter

from data.match_node.dataset import Dataset, build_formalizer, load_file


OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'laya_data')


class ArgumentsRecorder(Decider):
	""" A Decider of match_node that keeps the arguments of its last request and answers that the mention is not the instance. """

	def __init__(self, schema, extra_args, endpoint = None, logger = None):
		super().__init__(schema, extra_args, endpoint = endpoint, logger = logger)

		self.question  = 'MATCH_NODE'
		self.arguments = None

		self._meta_ = self._meta()


	def _run(self, request):
		self.arguments = request['arguments']

		return {'finish_reason': 'stop', 'message': {'score': 0.0, 'same': False}}


	def _dry_run(self, request):
		return {'status': 0, 'description': 'Valid request.'}


def create_row(formalizer: Formalizer, recorder: ArgumentsRecorder, mention: dict, candidate: dict) -> dict:
	""" Returns the row of a pair: the state Laya is asked, the questions, the expected answer and the pair. """

	arguments = {'mention': mention['mention'], 'node': candidate['node']}
	formalizer.match_node(arguments)

	state	 = MatchNodeLayaPrompter.create_state(recorder.arguments)
	expected = {'same': candidate['gold']}
	meta	 = {'mention_id': mention['mention_id'], 'id': candidate['node']['id']}
	row		 = {'state': state, 'questions': MatchNodeLayaPrompter.QUESTIONS, 'expected': expected, 'meta': meta}

	return row


def create_rows(dataset: Dataset) -> List[dict]:
	""" Returns the rows of every pair of the dataset, in order. """

	recorder   = ArgumentsRecorder('Recorder', {})
	formalizer = build_formalizer(dataset.ontology, recorder)

	rows = []
	for mention in dataset.mentions:
		for candidate in mention['candidates']:
			rows.append(create_row(formalizer, recorder, mention, candidate))

	return rows


def write(path: str, rows: List[dict]) -> None:
	""" Writes the rows, one per line. """

	os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok = True)
	with open(path, 'w') as f:
		for row in rows:
			f.write(json.dumps(row) + '\n')


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description = 'Exports a dataset of match_node as data to fine-tune Laya on.')
	parser.add_argument('dataset', help = 'the .jsonl file of the dataset')
	parser.add_argument('--out', help = 'the file to write (by default, laya_data/<dataset>.jsonl)')

	return parser.parse_args()


def main() -> int:
	args	= parse_args()
	dataset = load_file(args.dataset)
	rows	= create_rows(dataset)

	path = args.out if args.out is not None else os.path.join(OUT, dataset.name + '.jsonl')
	write(path, rows)

	positives = 0
	for row in rows:
		positives += row['expected']['same']

	print('%d rows (%d positive) of %d mentions of %s -> %s' % (len(rows), positives, len(dataset.mentions), dataset.name, path))

	return 0


if __name__ == '__main__':
	sys.exit(main())
