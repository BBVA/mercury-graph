import os, logging, warnings

from mercury.graph.evidence import Decider, DeciderState
from mercury.graph.evidence.agentic import AgenticRunInvalidRequest, AgenticRunInvalidState


class Gl2Decider(Decider):
	""" The base of the [`Decider`][mercury.graph.evidence.Decider]s that answer with a GLiNER2 model.

	It is not a Decider by itself: it answers no question. It implements what every GLiNER2 Decider shares: `pilot()` loads the model,
	`_run()` checks the request and the state and passes the arguments to `_answer()`, which the subclass implements, and `close()`
	releases the model.

	Its configuration (`extra_args`) is:

	- "description" (optional): exposed in the metadata of the Decider. It can be a string or a list of strings.
	- "model" (mandatory): the model to load (e.g., "fastino/gliner2.5-base-v1").
	- "map_location", "quantize" and "compile" (optional): passed to `AutoExtractor.from_pretrained()` when they are not null.

	Every GLiNER2 Decider loads its own model.

	Args:
		schema (str): a schema (a unique name) to use for the Decider's ID.
		extra_args (dict): the configuration for the Decider.
		endpoint (Agentic): an optional Endpoint. It becomes part of the Decider's ID and is available via `self.endpoint`. If not
			provided, the Decider becomes its own Endpoint.
		logger (list): an optional logger to use for logging events. It must provide an `append()` method to add new events.
	"""

	MODEL_OPTIONS = ['map_location', 'quantize', 'compile']		# Passed to AutoExtractor.from_pretrained() when they are not None.

	def __init__(self, schema, extra_args, endpoint = None, logger = None):
		super().__init__(schema, extra_args, endpoint = endpoint, logger = logger)

		self._model = None


	def _run(self, request):
		""" Answers the question of the Decider with the arguments of the request.

			(See [`Agentic.run()`][mercury.graph.evidence.Agentic.run].)
		"""

		name	   = request.get('name', None)
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
		""" Returns the answer to the question of the Decider. It MUST be implemented by the subclasses.

		Args:
			arguments (dict): The arguments of the question, as defined in [`Question`][mercury.graph.evidence.Question].
		"""

		raise NotImplementedError


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

		extractor = self._import_extractor()
		if extractor is None:
			self.log_error('GLiNER2 is not installed (gliner2.AutoExtractor cannot be imported) for Decider %s.' % self.id)

			return DeciderState.ERR_MODEL_INIT.value

		options = self._model_options()

		try:
			self._model = self._load_model(extractor, name, options)

		except Exception as e:
			self.log_error('Failed to load model "%s" in Decider %s: %s' % (name, self.id, str(e)))

			return DeciderState.ERR_MODEL_INIT.value

		return DeciderState.MODEL_LOADED_OK.value


	def _import_extractor(self):
		""" Returns gliner2.AutoExtractor, or None if it cannot be imported. """

		os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL', '3')
		os.environ.setdefault('USE_TF', '0')

		try:
			from gliner2 import AutoExtractor

		except ImportError:
			return None

		return AutoExtractor


	def _model_options(self):
		""" Returns the options of the configuration to pass to `AutoExtractor.from_pretrained()`: those that are not None. """

		options = {}
		for option in self.MODEL_OPTIONS:
			value = self.conf.get(option, None)
			if value is not None:
				options[option] = value

		return options


	def _load_model(self, extractor, name, options):
		""" Returns the model loaded with the options, with the logs and warnings of the libraries silenced while loading. """

		previous_disable_level = logging.root.manager.disable
		logging.disable(logging.WARNING)

		try:
			with warnings.catch_warnings():
				warnings.simplefilter('ignore')

				model = extractor.from_pretrained(name, **options)

		finally:
			logging.disable(previous_disable_level)

		return model


	def close(self, endpoint_locked):
		""" Closes the Decider and releases the model. It has no state to persist.

		(See [`Agentic.close()`][mercury.graph.evidence.Agentic.close].)
		"""

		self._model = None
