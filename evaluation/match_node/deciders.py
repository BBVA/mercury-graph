""" The Deciders of match_node that can be evaluated, by name:

- "names": NamesDecider, a baseline defined here,
- "laya": MatchNodeLayaDecider with the model convaiinnovations/laya (it needs `pip install laya`),
- "laya/<subfolder>": the same with the checkpoint of that model in the subfolder (e.g., "laya/typed-decisions"),
- "laya:<folder>": the same with a local checkpoint, such as one fine-tuned by training/match_node/finetune.py.
"""

import os
from typing import List

from mercury.graph.evidence import Decider
from mercury.graph.evidence.deciders import MatchNodeLayaDecider

from data.match_node.dataset import name_of, words


THRESHOLD = 0.5
LAYA	  = 'convaiinnovations/laya'


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
		mention	  = words(arguments['mention']['mention'])
		name	  = words(name_of(arguments['node']['id']))
		common	  = mention & name
		score	  = len(common)/len(mention) if len(mention) > 0 else 0.0
		threshold = self.conf.get('threshold', THRESHOLD)
		answer	  = {'score': score, 'same': score >= threshold}

		return {'finish_reason': 'stop', 'message': answer}


	def _dry_run(self, request):
		return {'status': 0, 'description': 'Valid request.'}


def create(name: str, threshold: float, logger: List[dict]) -> Decider:
	""" Returns the Decider of a name (see above) with a threshold, logging its events in the logger. """

	if name == 'names':
		return NamesDecider('Names', {'threshold': threshold}, logger = logger)

	if name.startswith('laya:'):
		return create_local_laya(name, threshold, logger)

	model, _, subfolder = name.partition('/')
	if model != 'laya':
		raise ValueError('Unknown Decider "%s": it must be "names", "laya", "laya/<subfolder>" or "laya:<folder>".' % name)

	conf = {'model': LAYA, 'threshold': threshold}
	if subfolder != '':
		conf['subfolder'] = subfolder

	return MatchNodeLayaDecider('Laya', conf, logger = logger)


def create_local_laya(name: str, threshold: float, logger: List[dict]) -> Decider:
	""" Returns MatchNodeLayaDecider with the local checkpoint of a name "laya:<folder>". """

	folder = os.path.abspath(name[len('laya:'):])
	if not os.path.isdir(folder):
		raise ValueError('The checkpoint "%s" is not a folder.' % folder)

	conf = {'model': folder, 'threshold': threshold}

	return MatchNodeLayaDecider('Laya', conf, logger = logger)


def info(name: str, decider: Decider) -> dict:
	""" Returns what a run keeps of the Decider: its name, its class and its configuration. """

	return {'name': name, 'class': type(decider).__name__, 'conf': dict(decider.conf)}
