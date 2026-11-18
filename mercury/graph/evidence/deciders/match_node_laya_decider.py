import logging, warnings

from mercury.graph.evidence import Decider, DeciderState
from mercury.graph.evidence.agentic import AgenticRunInvalidRequest, AgenticRunInvalidState


class MatchNodeLayaDecider(Decider):
	""" A [`Decider`][mercury.graph.evidence.Decider] that answers `match_node` with a local Laya model: whether a mention is a known
	instance.

	Laya answers a yes/no question about a state (a JSON object) with the probability of "yes". The state has the known instance
	(`id`, `description` and `names`, if any), the mention (`mention`, `type`, the `type_definition` and `texts`, if any) and the
	`context` of the question, if any, in that order: if the state does not fit the model, Laya cuts it from the end, so the context and
	then the texts are cut first. A cut is logged.

	The answer is `{"score": <the probability of yes>, "same": score >= threshold}`.

	Its configuration (`extra_args`) is:

	- "description" (optional): exposed in the metadata of the Decider. It can be a string or a list of strings.
	- "model" (mandatory): the model to load (e.g., "convaiinnovations/laya").
	- "threshold" (optional): the score from which the mention is the known instance (0.5 by default).
	- "subfolder", "device" and "revision" (optional): passed to `laya.load()` when they are not null (e.g., "subfolder":
	  "typed-decisions" loads that checkpoint of the model).

	Laya requires Python 3.10 or later and is not installed with mercury-graph: install it with `pip install laya`.

	Args:
		schema (str): a schema (a unique name) to use for the Decider's ID.
		extra_args (dict): the configuration for the Decider.
		endpoint (Agentic): an optional Endpoint. It becomes part of the Decider's ID and is available via `self.endpoint`. If not
			provided, the Decider becomes its own Endpoint.
		logger (list): an optional logger to use for logging events. It must provide an `append()` method to add new events.
	"""

	MODEL_OPTIONS = ['subfolder', 'device', 'revision']	# Passed to laya.load() when they are not None.
	THRESHOLD	  = 0.5

	QUESTIONS = {
		'same': {
			'type': 'noul',
			'instructions': 'Does the mention refer to the same real-world entity as the known instance?',
			'criteria': {
				'true': 'the mention refers to the known instance',
				'false': 'the mention refers to a different entity'
			}
		}
	}

	def __init__(self, schema, extra_args, endpoint = None, logger = None):
		super().__init__(schema, extra_args, endpoint = endpoint, logger = logger)

		self.question = 'MATCH_NODE'

		self._meta_ = self._meta()	# Must be called again after setting self.question to update the capability.
		self._model = None


	def _run(self, request):
		""" Answers `match_node` with the arguments of the request.

			(See [`Agentic.run()`][mercury.graph.evidence.Agentic.run].)
		"""

		name = request.get('name', None)
		capability = self.meta['capabilities'][0]['function']['name']
		if name != capability:
			self.log_error('Decider %s does not have a function named "%s".' % (self.id, name))
			raise AgenticRunInvalidRequest

		state = self.meta['state']
		if state != DeciderState.READY.value:
			self.log_error('Decider %s is not ready (state %d).' % (self.id, state))
			raise AgenticRunInvalidState

		answer = self._answer(request['arguments'])

		return {'finish_reason': 'stop', 'message': answer}


	def _answer(self, arguments):
		""" Returns the score and the decision of the model for the mention and the known instance of the arguments. """

		state  = self._state(arguments)
		result = self._model.predict(state, self.QUESTIONS)

		self._log_cut(result)

		score	  = float(result['answers']['same']['noul'])
		threshold = self.conf.get('threshold', self.THRESHOLD)

		return {'score': score, 'same': score >= threshold}


	def _state(self, arguments):
		""" Returns the state for the model: the known instance, the mention and the context, in that order. """

		node  = arguments['node']
		known = {'id': node['id'], 'description': node['description']}
		if 'names' in node:
			known['names'] = node['names']

		mention = arguments['mention']
		found	= {'mention': mention['mention'], 'type': mention['type'], 'type_definition': mention.get('definition', None)}
		if 'texts' in mention:
			found['texts'] = mention['texts']

		state = {'known_instance': known, 'mention': found}
		if 'context' in arguments:
			state['context'] = arguments['context']

		return state


	def _log_cut(self, result):
		""" Logs that the model cut the state, if it did. """

		usage = result.get('usage', {})
		if not usage.get('truncated', False):
			return

		dropped = usage.get('state_tokens_dropped', '?')
		self.log_message('Decider %s: the state did not fit the model and %s tokens were cut from its end.' % (self.id, dropped))


	def _dry_run(self, request):
		""" Simulates running the Decider with the given request.

			(See [`Agentic.dry_run()`][mercury.graph.evidence.Agentic.dry_run].)

		## NOTE:

		The Endpoint takes care of validating the request according to the capabilities exposed by the Decider. It is not necessary to
		validate again here. This method is provided as a requirement of the Agentic interface.
		"""

		return {'status': 0, 'description': 'Valid request.'}


	def pilot(self, intent, just_once = False):
		""" Pilots the Decider to a new state based on the given intent: loading the model makes it ready.

		(See [`Agentic.pilot()`][mercury.graph.evidence.Agentic.pilot].)
		"""

		if self.meta['state'] < 0:
			self.log_error('Decider %s is in error state %d' % (self.id, self._meta_['state']))

			return

		while self._meta_['state'] < intent:
			if self._meta_['state'] == DeciderState.INITIAL.value:
				self._meta_['state'] = self._pilot_model()

				if self._meta_['state'] < 0 or just_once:
					break

			if self._meta_['state'] == DeciderState.MODEL_LOADED_OK.value:
				self._meta_['state'] = DeciderState.READY.value

				if just_once:
					break


	def _pilot_model(self):
		""" Loads the model and returns the new state: MODEL_LOADED_OK or, logging the problem, ERR_MODEL_INIT. """

		name = self.conf.get('model', None)
		if name is None:
			self.log_error('"model" is missing in the configuration of Decider %s.' % self.id)

			return DeciderState.ERR_MODEL_INIT.value

		load = self._import_load()
		if load is None:
			self.log_error('Laya is not installed (laya.load cannot be imported) for Decider %s.' % self.id)

			return DeciderState.ERR_MODEL_INIT.value

		options = self._model_options()

		try:
			self._model = self._load_model(load, name, options)

		except Exception as e:
			self.log_error('Failed to load model "%s" in Decider %s: %s' % (name, self.id, str(e)))

			return DeciderState.ERR_MODEL_INIT.value

		return DeciderState.MODEL_LOADED_OK.value


	def _import_load(self):
		""" Returns laya.load, or None if it cannot be imported. """

		try:
			from laya import load

		except ImportError:
			return None

		return load


	def _model_options(self):
		""" Returns the options of the configuration to pass to `laya.load()`: those that are not None. """

		options = {}
		for option in self.MODEL_OPTIONS:
			value = self.conf.get(option, None)
			if value is not None:
				options[option] = value

		return options


	def _load_model(self, load, name, options):
		""" Returns the model loaded with the options, with the logs and warnings of the libraries silenced while loading. """

		previous_disable_level = logging.root.manager.disable
		logging.disable(logging.WARNING)

		try:
			with warnings.catch_warnings():
				warnings.simplefilter('ignore')

				model = load(name, **options)

		finally:
			logging.disable(previous_disable_level)

		return model


	def close(self, endpoint_locked):
		""" Closes the Decider and releases the model. It has no state to persist.

		(See [`Agentic.close()`][mercury.graph.evidence.Agentic.close].)
		"""

		self._model = None
