import importlib, json, os, pickle, re

from enum import Enum

from .agent import Agent
from .agentic import Agentic, AgenticRunException, AgenticRunInvalidRequest, AgenticRunInvalidState, AgenticRunFailed
from .agentic_graph import AgenticGraph
from .evidence_graph import EvidenceGraph
from .formalizer import Formalizer
from .source import Source


class AgenticFailedToFindCapability(AgenticRunException):
	""" The Endpoint could not identify which Agentic and/or which capability to call. """

	pass


class AgenticFailedToParseOutput(AgenticRunException):
	""" The Endpoint could not parse the output of an Agentic call. No {'finish_reason': ...} was found. """

	pass



class LockState(Enum):
	""" The `LockState` is an enumeration that defines the possible states of the Endpoint lock. """

	FORCE_FREE	 = -2	# Special command to force the mutex to be free. This is a dangerous operation that should be used with caution.
	INIT_IF_NONE = -1	# Special command create the mutex if it does not exist. Just returns the state if it does.
	FREE		 =  0	# The command to free the mutex and the state when free.
	LOCK		 =  1	# The command to lock the mutex and the state when locked.
	LOCK_FAILED	 =  2	# The state when a LOCK failed. Maybe locked by another process or not available.
	FREE_FAILED	 =  3	# The state when a FREE failed. Only if the mutex is not available.


class EndPointState(Enum):
	""" The `EndPointState` is an enumeration that defines the possible states of the Endpoint. """

	ERR_IN_OBJECT	= -5	# Some loaded object in the Endpoint is in an error state.
	ERR_PILOTING	= -4	# The Endpoint failed to pilot some objects.
	ERR_EXPOSING	= -3	# The Endpoint failed to building its API.
	ERR_LINKING		= -2	# The Endpoint failed to link some of its objects.
	ERR_LOADING_OBJ	= -1	# The Endpoint failed to load some of its objects.
	INITIAL			=  0	# The initial state of the source.
	LOADED_OBJ		=  1	# The Endpoint has loaded all the objects in its architecture. It is not ready to process queries yet.
	LINKED_OBJ		=  2	# The Endpoint has satisfied all the inter-dependencies of its objects.
	EXPOSED_API		=  3	# The Endpoint has exposed its Agentic API to the outside world.
	PILOT_REQUIRED	=  4	# The Endpoint has loaded all its architecture but some of them are not ready to process queries yet.
	ALL_READY		=  100	# The source is ready to be processed.


class Endpoint(Agentic):
	""" The `Endpoint` is the class that serves an entire Agentic architecture to the outside world using the Agentic interface itself.

	## Overview

	An `Endpoint` is a full project that contains any number of Agentic objects. It's metadata lives in a folder that contains a
	`mge_endpoint.jsonc` file and a file named either `mge_endpoint.free` or `mge_endpoint.locked` that acts as a write mutex.
	`Endpoint` is the only object that owns the architecture of the tree.

	For any "outside" Agentic user, an `Endpoint` is just another Agentic service. It is a graph of Agentic objects. There are
	two ways to do this: Create as many Endpoints as you want in your Python code and use them as Agentics or, more commonly,
	use the [`mge`](evidence_cli.md) cli to maintain and serve the Endpoints persisted in the file system as a folder.

	### What the Endpoint manages

	* The definition of the architecture. The Agentic objects are defined here but may be located anywhere.
		The architecture can have a life cycle defined by `intent` values. An intent is a desired state for the architecture. These
		intents can apply to each Agentic in the architecture. They will typically be ordered integer numbers with names such as "initial",
		"ready", "busy", etc. defined as an Enum to support human-friendly interfaces (E.g., `mge serve main_doc all_ready 8888').
		Negative values represent non recoverable errors, zero is the initial state, and positive values are sorted. Each class can have
		up to 99 intermediate states below READY which corresponds to 100. Those intents 1..99 represent: building indices, chunking
		documents, setting up vector databases, formalizing chunks of text, merging into evidence graphs, etc. across multiple Agentic
		objects. Also, the arrival/update of new documents may require updating the Evidence Graph setting back the state of some of them.
		So the Endpoint is ALL_READY (100) only when all of them are READY (100).
	* Saving, loading and parsing (manually edited) its own definition stored in a folder with its name and a `mge_endpoint.jsonc` file.
		That file also contains configuration of Agentics stored as separate files in the same folder.
	* A mechanism to `pilot` the Endpoint's state up to a desired state. This is different from the `run()` method which runs queries
		using the Endpoint's Agentic interface. Piloting is a process typically done using the [`mge`](evidence_cli.md) cli.
	* The mutex providing exclusive write access to the objects. The Endpoint is locked when the cli either serves or pilots the Endpoint.
		It can also be done programmatically by calling the `lock()` method. This is mandatory when the metadata is modified.
	* It's own Agentic API. This exposes a set of functions merged from the Agentics that are marked as "exposed" in the Endpoint's conf.
	* The interdependencies within the Agentic objects.

	### Http interface

	The cli provides a simple http interface to the Endpoint. The Endpoint exposes its Agentic API like any other Agentic object.

	### Self configuration

	Endpoints can use Agents to complete and verify their configuration with or without human intervention.

	Attributes:
		id (str): the Agentic ID of the Endpoint.
		logger (list): the logger to use for logging events. It must provide an `append()` method to add new events. It is optional.
		tools (dict): a dictionary of the Agentics in the Endpoint, keyed by their IDs.
		ids (dict): a dictionary of the Agentics in the Endpoint, keyed by their types. This connects the Agentic from their category and
			name in the architecture to IDs of the loaded objects.
		states (Enum): an optional Enum class that defines names for the states of an Agentic. It is used to improve readability and cli
			argument parsing.
		meta (dict): a dictionary of metadata about the Agentic. It is used to store the current state of the Agentic and other information.

	Args:
		path (str): the path to the Endpoint's home directory. The final name (the folder inside whatever path) must be identical to its
			._normalize_name() value, that is, a name with only letters, numbers or underscores.
		logger (list): an optional logger. If not provided, no logging will be done.
	"""

	def __init__(self, path = None, logger = None):
		if not os.path.isdir(path):
			raise ValueError('The path "%s" is not a valid directory.' % path)

		self.home		= os.path.abspath(path)
		schema			= self._normalize_name(os.path.basename(self.home))
		self.conf_fn	= os.path.join(self.home, 'mge_endpoint.jsonc')
		self.lock_fn	= os.path.join(self.home, 'mge_endpoint.locked')
		self.free_fn	= os.path.join(self.home, 'mge_endpoint.free')
		self.rex_remark = re.compile('^[ \\t]*//.*$')	# Regular expression to remove comments from JSONC files.

		if not os.path.isfile(self.conf_fn):
			raise ValueError('The path "%s" is not a valid Endpoint. The file "mge_endpoint.jsonc" is missing.' % self.conf_fn)

		self.conf = self._json_load(self.conf_fn)

		self.lock(LockState.INIT_IF_NONE)

		super().__init__(my_class = 'endpoint', schema = schema, endpoint = None, logger = logger)

		self.states = EndPointState
		self.ids = {'sources': {}, 'ontologies': {}, 'formalizers': {}, 'evidence_graphs': {}, 'agents': {}, 'custom_agentics': {}}

		auto_pilot = self.conf.get('auto_pilot', None)
		if auto_pilot is not None:
			path = os.path.abspath(os.path.join(self.home, auto_pilot['file_name']))

			if os.path.isfile(path):
				with open(path, 'rb') as f:
					obj = pickle.load(f)

				intent = obj.get('state', self.meta['state'])

				if intent > self.meta['state']:
					if self.logger is not None:
						msg	  = 'Auto-piloting Endpoint "%s" to state %d.' % (self.id, intent)
						event = {'type': 'message', 'timestamp': self._now(), 'id': self.id, 'seq_num': self.seq_num, 'message': msg}

						self.logger.append(event)
						self.seq_num += 1

					self.pilot(intent)


	def __str__(self):
		""" Returns a console friendly summary of the Endpoint state. """

		bold	 = '\033[1m'
		italic	 = '\033[3m'
		reset	 = '\033[0m'
		labels	 = ['name', 'creation_date', 'mge_version', 'description']
		sections = ['sources', 'ontologies', 'formalizers', 'evidence_graphs', 'agents', 'custom_agentics']
		no_name	 = '%sno name%s' % (italic, reset)
		no_obj	 = '%snot loaded%s' % (italic, reset)
		no_state = '%sno state%s' % (italic, reset)
		icons	 = {
			'endpoint': '🌐',
			'sources': '📚',
			'ontologies': '🏛️',
			'formalizers': '🧩',
			'evidence_graphs': '🕸️',
			'agents': '🤖',
			'custom_agentics': '🛠️'
		}

		txt = ['%s%s Endpoint%s' % (bold, icons['endpoint'], reset)]

		for label in labels:
			value = self.conf.get(label, '')

			txt.append('   %-14s: %s' % (label, value))

		state = self.meta['state']
		name  = self.state_name(state)
		if name is None:
			name = no_name

		txt.append('   %-14s: %s %s(%s)%s' % ('state', state, italic, name, reset))

		capabilities = self.meta.get('capabilities', None)
		if capabilities is not None:
			txt.append('   %-14s: %s' % ('capabilities', '(%d total) %s' % (len(capabilities), list(self.agentic_by_capability.keys()))))

		for section_name in sections:
			items = self.conf.get(section_name, {})
			txt.append('')
			txt.append('  %s%s %s%s (%d total)' % (bold, icons[section_name], section_name, reset, len(items)))

			if len(items) == 0:
				txt.append('     %sempty%s' % (italic, reset))
				continue

			for item_name in sorted(items.keys()):
				id = self.ids[section_name].get(item_name, None)

				if id is None:
					txt.append('     - %s: %s' % (item_name, no_obj))
				else:
					agentic = self.tools[id]
					state   = agentic.meta.get('state', None)
					if state is None:
						state = no_state
						name  = no_name
					else:
						name = agentic.state_name(state)
						if name is None:
							name = no_name

					txt.append('     - %s: %s (%s) id: %s' % (item_name, state, name, id))

		return '\n'.join(txt)


	def close(self, endpoint_locked):
		""" It calls the close() of each Agentic in the Endpoint. And persists its state to disk.

			(See [`Agentic.close()`][mercury.graph.evidence.Agentic.close].)
		"""

		for a in self.tools.values():
			if self.logger is not None:
				msg	  = 'Closing Agentic "%s" endpoint_locked = %s.' % (a.id, endpoint_locked)
				event = {'type': 'message', 'timestamp': self._now(), 'id': self.id, 'seq_num': self.seq_num, 'message': msg}

				self.logger.append(event)

			a.close(endpoint_locked)

		if self.logger is not None:
			msg	  = 'Closing Endpoint "%s".' % self.id
			event = {'type': 'message', 'timestamp': self._now(), 'id': self.id, 'seq_num': self.seq_num, 'message': msg}

			self.logger.append(event)
			self.seq_num += 1

		if endpoint_locked:
			auto_save = self.conf.get('auto_save', None)

			if auto_save is None:
				return

			path = os.path.abspath(os.path.join(self.home, self.conf['auto_save']['file_name']))

			obj = {}

			for key in self.conf['auto_save']['save']:
				obj[key] = self.meta[key]

			with open(path, 'wb') as f:
				pickle.dump(obj, f)


	def lock(self, cmd):
		""" Locks or unlocks the Endpoint's mutex. The mutex is used to provide exclusive write access to the Endpoint's metadata for
		piloting and serving.

		Args:
			cmd (LockState): the lock command. It must be one of the values of the `LockState` Enum. (See source code for details.)

		Returns:
			(LockState): the final state of the mutex after the command is executed. A value in the `LockState` Enum.
				(See source code for details.)
		"""

		if cmd == LockState.FREE:
			try:
				os.rename(self.lock_fn, self.free_fn)

				return LockState.FREE

			except Exception:
				if os.path.isfile(self.free_fn):
					return LockState.FREE
				else:
					return LockState.FREE_FAILED

		elif cmd == LockState.LOCK:
			try:
				os.rename(self.free_fn, self.lock_fn)

				return LockState.LOCK

			except Exception:
				return LockState.LOCK_FAILED

		elif cmd == LockState.INIT_IF_NONE:
			if os.path.isfile(self.lock_fn):
				return LockState.LOCK

			elif os.path.isfile(self.free_fn):
				return LockState.FREE

			open(self.free_fn, 'w').close()

			return LockState.FREE

		elif cmd == LockState.FORCE_FREE:
			try:
				os.path.remove(self.lock_fn)
			except Exception:
				pass

			open(self.free_fn, 'w').close()		# No need to check if it exists.

			return LockState.FREE

		else:
			raise ValueError('Invalid lock command "%s".' % cmd)


	def _run(self, request):
		""" Runs the Endpoint with the given request.

		(See [`Agentic.run()`][mercury.graph.evidence.Agentic.run].)

		This can raise its own AgenticRunException:

		* AgenticFailedToFindCapability When the Endpoint could not identify which Agentic and/or which capability to call.
		* AgenticFailedToParseOutput When the Endpoint could not parse the output.

		Notes:
			* Unlike _dry_run(), _run() does not call _request_issues(). The Agentic, not the Endpoint validates the call.
			* The Endpoint is responsible of handling Tool calls. If an Agentic (typically an Agent) calls a Tool, the Endpoint has
				to accept or reject the call based on resources (preventing infinite loops, etc.). If the call is rejected, the Endpoint
				provides a reason and a message history if possible. If accepted, the Endpoint, calls the tool and then calls the same
				Agentic with a message history that includes the result of the tool call.
			* In an Endpoint with more than one capability (the typical case), the request must be a pure function to identify the Agent.
				When tool calls are made, conversation becomes a message history assuming Agentics that call tools can behave as (or are)
				Agents. This is normal behavior, the First tool call is actually passing a message to a function.
		"""

		if self.meta['state'] < self.states.ALL_READY.value:
			raise AgenticRunInvalidState

		is_pure_call = type(request) == dict and 'name' in request and 'arguments' in request

		if is_pure_call or (self.num_capabilities > 1):
			if not is_pure_call:
				raise AgenticFailedToFindCapability

			name = request['name']

			agentic = self.agentic_by_capability.get(name, None)

			if agentic is None:
				raise AgenticFailedToFindCapability

			response = agentic.run(request)

			finish_reason = response.get('finish_reason', None)

			if finish_reason is None:
				raise AgenticFailedToParseOutput

			if finish_reason == 'stop' or finish_reason == 'error':		# Canonical 'finish_reason' values first.
				return response

			if finish_reason != 'tool_calls':							# Try to guess other names
				if not finish_reason.lower().startswith('tool'):
					return response										# Non-canonical finish_reason, let the caller handle it.

			return self._response_loop(agentic, request, response)

		agentic = next(iter(self.agentic_by_capability.values()))

		response = agentic.run(request)

		finish_reason = response.get('finish_reason', None)

		if finish_reason is None:
			raise AgenticFailedToParseOutput

		if finish_reason == 'stop' or finish_reason == 'error':		# Canonical 'finish_reason' values first.
			return response

		if finish_reason != 'tool_calls':							# Try to guess other names
			if not finish_reason.lower().startswith('tool'):
				return response										# Non-canonical finish_reason, let the caller handle it.

		return self._response_loop(agentic, request, response)


	def _meta(self):
		""" Returns the metadata of the Endpoint.

			(See [`Agentic.meta()`][mercury.graph.evidence.Agentic.meta].)
		"""

		return {'state' : 0}	# Anything else is created in the different stages of pilot()


	def _dry_run(self, request):
		""" Runs a dry run of the Endpoint with the given request.

			(See [`Agentic.dry_run()`][mercury.graph.evidence.Agentic.dry_run].)
		"""

		if self.meta['state'] < self.states.ALL_READY.value:
			return {'status': 1, 'description': 'Not ready.'}

		issues = self._request_issues(request)

		if issues is None:
			return {'status': 0, 'description': 'Valid request.'}

		else:
			return {'status': 2, 'description': str(issues)}


	def pilot(self, intent, just_once = False):
		""" Pilots the Endpoint to a new state based on the given intent.

		(See [`Agentic.pilot()`][mercury.graph.evidence.Agentic.pilot].)
		"""

		if self.meta['state'] < 0:					# Irrecoverable error.
			return

		try:
			intent = int(intent)

		except Exception:
			intent = self.states[intent.upper()].value

		while self.meta['state'] < intent:
			if self.meta['state'] == self.states.INITIAL.value:
				if self._load_objects():
					self.meta['state'] = self.states.LOADED_OBJ.value
				else:
					self.meta['state'] = self.states.ERR_LOADING_OBJ.value
					break

				continue

			if self.meta['state'] == self.states.LOADED_OBJ.value:
				if self._link_objects():
					self.meta['state'] = self.states.LINKED_OBJ.value
				else:
					self.meta['state'] = self.states.ERR_LINKING.value
					break

				continue

			if self.meta['state'] == self.states.LINKED_OBJ.value:
				if self._expose_api():
					self.meta['state'] = self.states.EXPOSED_API.value
				else:
					self.meta['state'] = self.states.ERR_EXPOSING.value
					break

				continue

			next_agentic = self._next_agentic_below(intent)
			if next_agentic is not None:
				if next_agentic.meta['state'] < 0:
					self.meta['state'] = self.states.ERR_IN_OBJECT.value
					break

				next_agentic.pilot(intent, just_once = just_once)

				if self._next_agentic_below(intent) is None and intent == self.states.ALL_READY.value:
					self.meta['state'] = self.states.ALL_READY.value
				else:
					self.meta['state'] = self.states.PILOT_REQUIRED.value

			if just_once:
				break


	def _json_load(self, fn, recursion_depth = 0):
		""" Loads a JSONC file and returns the corresponding object. It also removes comments and recursively loads any referenced
		JSONC files. The recursion depth is limited to 8 to avoid infinite loops.

		Args:
			fn (str): the path to the JSONC file to load.
			recursion_depth (int): the current recursion depth used internally in recursive calls.

		Returns:
			(any): The object loaded from the JSONC file.
		"""

		if recursion_depth > 8:
			raise ValueError('Recursion depth exceeded while loading JSON file "%s".' % fn)

		base_path = os.path.dirname(os.path.abspath(fn))

		# Load it as a list of string to remove comments.
		with open(fn, 'r') as f:
			txt = f.readlines()

		txt = [s for s in txt if not self.rex_remark.match(s)]

		ret = json.loads(''.join(txt))

		# Parse the object (top level only) to search for dictionaries that have "$ref" as their only key. When found, load the referenced
		# file and replace the corresponding value with the object loaded recursively.

		if type(ret) == dict:
			for key in ret.keys():
				o = ret[key]

				if (type(o) == dict) and (len(o) == 1) and ('$ref' in o):
					r_fn  = os.path.abspath(os.path.join(base_path, o['$ref']))
					r_ret = self._json_load(r_fn, recursion_depth + 1)
					ret[key] = r_ret

		return ret


	def _request_issues(self, request):
		""" Matches the request against the Endpoint's capabilities following the formats described in:
		[`Agentic.run()`][mercury.graph.evidence.Agentic.run]

		Args:
			request (dict): the request to check.

		Returns:
			(None or str): None if the request is valid, or a string describing the issues found.
		"""

		pure_function_call = (self.num_capabilities > 1) or (type(request) == dict and 'name' in request and 'arguments' in request)

		if pure_function_call:
			if type(request) != dict:
				return 'Request must be a dictionary with a "name" (of a capability) and "arguments".'

			name = request.get('name', None)

			if type(name) != str:
				return 'Request must have a "name" key with a string value.'

			cap = self.capabilities_by_name.get(name, None)
			if cap is None:
				return 'Capability "%s" not found in Endpoint.' % name

			args = request.get('arguments', None)
			if type(args) != dict:
				return 'Request must have an "arguments" key with a dictionary value.'

			if 'arguments' not in request:
				return 'Request must have an "arguments" key.'

			fun = cap.get('function', None)
			if type(fun) != dict:
				return 'Definition of capability "%s" is malformed. No function details given. Edit its configuration to fix it.' % name

			par = fun.get('parameters', None)
			if type(par) != dict:
				return 'Definition of capability "%s" is malformed. No parameters given. Edit its configuration to fix it.' % name

			for key in par.get('required', []):
				if key not in args:
					return 'Request is missing required argument "%s".' % key

			return None					# No issues found.

		# From here on, the request can only be a message or a list of messages.

		if type(request) != list:
			request = [request]

		for msg in request:
			if type(msg) != dict or ('content' not in msg and 'role' not in msg):
				return 'Request must be a dictionary with "content" and "role".'

		return None						# No issues found.


	def _load_objects(self):
		""" This method parses the self.conf dictionary, category by category: sources, ontologies, formalizers, evidence_graphs,
		agents and custom_agentics.

		It creates and instance of each, passing extra arguments to the constructor if they are present in the configuration.
		These instances are verified to have unique IDs and are stored in self.ids.

		The pilot() method calls this method when appropriate and sets the state according to the success.

		Returns:
			(bool): True if all objects were loaded successfully, False otherwise.
		"""

		def _resolve_conf_paths(arg):
			""" Resolve endpoint-relative paths inside configuration objects. """

			new_arg = {}

			for key, value in arg.items():
				if key == '$path':
					new_arg['path'] = os.path.abspath(os.path.join(self.home, value))
				elif type(value) == dict:
					new_arg[key] = _resolve_conf_paths(value)
				else:
					new_arg[key] = value

			return new_arg

		def _load_custom_agentic_class(class_name, file_path):
			""" Load a custom Agentic class from a Python source file. """

			module_name = os.path.splitext(os.path.basename(file_path))[0]

			spec = importlib.util.spec_from_file_location(module_name, file_path)

			if spec is None or spec.loader is None:
				return None

			module = importlib.util.module_from_spec(spec)
			spec.loader.exec_module(module)
			custom_class = getattr(module, class_name, None)

			if custom_class is None or not issubclass(custom_class, Agentic):
				return None

			return custom_class

		section_classes = {
			'sources': Source,
			'ontologies': AgenticGraph,
			'formalizers': Formalizer,
			'evidence_graphs': EvidenceGraph,
			'agents': Agent,
			'custom_agentics': None
		}
		for section in self.ids.keys():
			for value in self.conf[section].values():
				agentic_def = _resolve_conf_paths(value)

				name = agentic_def['name']
				extra_args = agentic_def.get('extra_args', {})
				tools = agentic_def.get('tools', [])

				agentic_class = section_classes[section]

				if agentic_class is None:
					agentic_class = _load_custom_agentic_class(agentic_def['class_name'], agentic_def['path'])

					if agentic_class is None:
						return False

				agentic = agentic_class(schema = name, extra_args = extra_args, endpoint = self, logger = self.logger)

				id = agentic.id

				if name in self.ids[section]:
					self.log_error('Duplicate name (%s) in section "%s"' % (name, section))
					return False

				self.ids[section][name] = id

				if id in self.tools:
					self.log_error('Duplicate ID (%s) in section "%s"' % (id, section))
					return False

				self.tools[id] = agentic

		return True


	def _link_objects(self):
		""" This method is called by pilot() when all the Agentic objects have been loaded.

		It just looks for what tools each one requires as defined in the configuration field 'tools'. It checks that every tool is
		found and the resulting graph does not have cycles.

		Once that is done, it calls the add_tool() method of each Agentic which required tools to make them available.

		The pilot() method calls this method when appropriate and sets the state according to the success.

		Returns:
			(bool): True if all objects were linked successfully, False otherwise.
		"""

		def _has_cycle(name, visiting, visited):
			if name in visited:
				return False

			if name in visiting:
				return True

			visiting.add(name)

			for tool_name in edges.get(name, []):
				if _has_cycle(tool_name, visiting, visited):
					return True

			visiting.remove(name)
			visited.add(name)

			return False

		self.name_to_agentic = {}
		for section in self.ids.keys():
			for name, id in self.ids[section].items():
				if name in self.name_to_agentic:
					self.log_error('Duplicate tool name (%s).' % name)
					return False

				self.name_to_agentic[name] = self.tools[id]

		edges = {}
		for section in self.ids.keys():
			for name in self.conf[section].keys():
				tool_names = self.conf[section][name].get('tools', [])
				edges[name] = []

				for tool_name in tool_names:
					tool = self.name_to_agentic.get(tool_name, None)

					if tool is None:
						self.log_error('Tool "%s" required by "%s" was not found.' % (tool_name, name))
						return False

					edges[name].append(tool_name)

		visited = set()
		for name in edges.keys():
			if _has_cycle(name, set(), visited):
				self.log_error('Cycle detected in tool dependencies involving "%s".' % name)
				return False

		for section in self.ids.keys():
			for name, id in self.ids[section].items():
				agentic = self.tools[id]

				for tool_name in edges.get(name, []):
					agentic.add_tool(self.name_to_agentic[tool_name])

		return True


	def _expose_api(self):
		""" This method called by pilot() builds the capabilities of the Endpoint by merging the capabilities of all the Agentics that
		in the 'expose' list of the Endpoint's configuration.

		It also checks that all the capabilities have unique names and builds two dictionaries one of capabilities by name and one of
		Agentic by capability name. These dictionaries `capabilities_by_name` and `agentic_by_capability` are used  by the run() and
		dry_run() methods.

		It also updates the Endpoint's meta with the capabilities.

		The pilot() method calls this method when appropriate and sets the state according to the success.

		Returns:
			(bool): True if no errors found exposing the capabilities, False otherwise.
		"""

		expose = self.conf.get('expose', None)

		if type(expose) != list or len(expose) == 0:
			self.log_error('The Endpoint configuration must define a non-empty "expose" list.')
			return False

		capabilities = []
		agentic_by_capability = {}
		capabilities_by_name  = {}

		for agentic_name in expose:
			agentic = self.name_to_agentic.get(agentic_name, None)
			if agentic is None:
				self.log_error('Agentic "%s" in "expose" was not found in Endpoint architecture.' % agentic_name)
				return False

			agentic_capabilities = agentic.meta.get('capabilities', None)
			if agentic_capabilities is None:
				self.log_error('Agentic "%s" does not expose any capabilities.' % agentic.id)
				return False

			for capability in agentic_capabilities:
				function = capability.get('function', None)
				if type(function) != dict:
					self.log_error('Agentic "%s" has a capability without a valid "function" object.' % agentic_name)
					return False

				capability_name = function.get('name', None)
				if type(capability_name) != str or capability_name != self._normalize_name(capability_name):
					self.log_error('Agentic "%s" has a capability without a valid function name.' % agentic_name)
					return False

				if capability_name in agentic_by_capability:
					self.log_error('Duplicate exposed capability "%s".' % (capability_name))
					return False

				capabilities.append(capability)
				agentic_by_capability[capability_name] = agentic
				capabilities_by_name[capability_name]  = capability

		self.meta['capabilities']  = capabilities
		self.agentic_by_capability = agentic_by_capability
		self.capabilities_by_name  = capabilities_by_name
		self.num_capabilities	   = len(capabilities)

		return self.num_capabilities > 0


	def _next_agentic_below(self, intent):
		""" This method is called by pilot() to find the first Agentic in the Endpoint whose state is below the desired intent.

		It may be and error state, in which case the Endpoint will set its state to ERR_IN_OBJECT and stop piloting.

		The pilot() method calls this method when appropriate and sets the state according to the success.

		Returns:
			(Agentic or None): The first Agentic whose state is below the desired intent, or None if all Agentics are at or above.
		"""

		for agentic in self.tools.values():
			if agentic.meta['state'] < intent:
				return agentic

		return None
