from enum import Enum

try:
	from litellm import completion

except ImportError:
	completion = None

from .agentic import Agentic, AgenticRunInvalidState, AgenticRunInvalidRequest, AgenticRunFailed


class AgentState(Enum):
	""" The `AgentState` is an enumeration that defines the possible states of the Agent. """

	ERR_BUILDING_TOOLS	= -3	# The Agent encountered an error finding the capabilities of the tools.
	ERR_COMPLETION		= -2	# The Agent encountered an error finding or calling completion.
	ERR_SETUP			= -1	# The Agent encountered an error during setup.

	INITIAL				=  0	# The initial state of the Agent.
	SETUP_OK			=  1	# The Agent was setup from its configuration.
	COMPLETION_OK		=  2	# The Agent can call completion.

	READY				=  100	# The Agent is ready to be called.


class Agent(Agentic):
	""" Agent is a class that connects to an external LLM using `litellm` and exposes it in the Agentic tree.

	## Overview

	This connects the LLM model in two ways:

	1. **Upstream**: It exposes the Agent's capabilities (defined in the Agents configuration) via an Agentic interface to any Agentic in
	its Endpoint that can use it as a tool.

	2. **Downstream**: Making the Agent aware of what tools it has access to, and how they work so it can create proper arguments.

	## Focus and Scope

	Agents solve minimal problems, ideally they would be simpler models than LLMs if such models could produce correct output from inputs.

	Agents are not aware of the Endpoint architecture, they only "see" what tools have been provided to them via `add_tool()`.

	Agents do not validate, prepare, plan their own tasks. The Endpoint is responsible for the "higher-level" orchestration.

	These agents do not always communicate through natural language. They use instructions and metadata in natural language but
	produce structured output that may or may not include natural language.

	## Interfacing with Agents

	Unlike other Agentic, each Agent has only one capability, but you can create as many Agents as needed.

	Agents do not directly call a tool. Instead, they produce a litellm (OpenAI-style) answer with `finish_reason='tool_calls'` and
	`tool_calls=[ChatCompletionMessageToolCall(function=Function(arguments='{"input": 16}', name='my_tool_for_sqrt')`. The Endpoint
	calls the tools if the "accounting" of resources is valid and calls the Agent back with result properly appended to the Agent's
	conversation. Any accounting of resources for answering a query belongs to the Endpoint.

	## Defining an Agent

	Agents are defined entirely by their configuration (model, capability and tools). Agents are intentionally "narrow" in scope.
	You can use as many as you want, either exposing them in the Endpoint or letting another Agent use them as a tool.

	### Configuration of an Agent

	(See the file `agents.jsonc` of an Endpoint newly created using the `mge` CLI for a working example.)

	To connect to any external LLM, possibly providing credentials, note that anything inside the "completion" dictionary will be
	passed as arguments to the litellm `completion()` method in addition to `messages` and `tools` (if applicable).

	## Known Limitations

	- For now, calls to Agents to not use parallel execution.
	- The management of tool calls is super-simplistic, just a counter to prevent infinite usage.
	- There is no safe management of credentials. (You can restrict access to the configuration manually.)

	Args:
		schema (str): a schema (a unique name) to use for the Agent's ID.
		extra_args (dict): the configuration for the Agent.
		endpoint (Agentic): an optional Endpoint. It becomes part of the Agent's ID and is available via `self.endpoint`. If not
			provided, the Agent becomes its own Endpoint.
		logger (list): an optional logger to use for logging events. It must provide an `append()` method to add new events.
	"""

	def __init__(self, schema, extra_args, endpoint = None, logger = None):
		super().__init__(my_class = 'agent', schema = schema, endpoint = endpoint, logger = logger)

		self.states = AgentState

		self.conf = extra_args

		self._meta_ = self._meta()	# Just to make .meta reflect the initial state.


	def _run(self, request):
		""" Runs the Agent with the given request.

			(See [`Agentic.run()`][mercury.graph.evidence.Agentic.run].)
		"""

		if self._meta_['state'] != self.states.READY.value:
			self.log_error('Agent %s is not ready for ._run.' % self.id)

			raise AgenticRunInvalidState

		if request['name'] != self.name:
			self.log_error('Agent does not have a function named "%s".' % request['name'])

			raise AgenticRunInvalidRequest

		args = request['arguments']

		messages = args.get('messages', None)
		if messages is None:
			if type(args) is dict and len(args) == 1:
				args = next(iter(args.values()))

			if type(args) is str:
				messages = []

				if self.you_are is not None:
					messages.append(self.you_are)

				if self.you_must is not None:
					messages.append(self.you_must)

				messages.append({'role': 'user', 'content': args})

			else:
				self.log_error('Agent _run received invalid arguments.')
				raise AgenticRunInvalidRequest

		try:
			ret = completion(messages = messages, **self.completion)

		except Exception as e:
			self.log_error('Agent encountered an error during completion: %s' % str(e))
			self._meta_['state'] = AgentState.ERR_COMPLETION.value
			raise AgenticRunFailed

		return ret


	def _meta(self):
		""" Returns the metadata of the Agent.

			(See [`Agentic.meta()`][mercury.graph.evidence.Agentic.meta].)
		"""

		meta = {}
		meta['state'] = AgentState.INITIAL.value

		meta['description'] = self.conf.get('description', '')
		if type(meta['description']) is list:
			meta['description'] = '\n'.join(meta['description'])

		meta['capabilities'] = []

		return meta


	def _dry_run(self, request):
		""" Simulates running the Agent with the given request.

			(See [`Agentic.dry_run()`][mercury.graph.evidence.Agentic.dry_run].)
		## NOTE:

		The Endpoint takes care of validating the request according to the capabilities exposed by the Agent. It is not necessary to
		validate again here and the Endpoint does not forward the dry_run() request to the Agent. This method is provided as a
		requirement of the Agentic interface, but it is only used when you use Formalizers directly outside of an Endpoint.
		"""

		return {'status': 0, 'description': 'Valid request.'}


	def pilot(self, intent, just_once = False):
		""" Pilots the Agent to a new state based on the given intent.

		(See [`Agentic.pilot()`][mercury.graph.evidence.Agentic.pilot].)
		"""

		if self.meta['state'] < 0:
			self.log_error('Agent is in error state %d' % self._meta_['state'])

			return

		while self._meta_['state'] < intent:
			if self._meta_['state'] == self.states.INITIAL.value:
				self.completion = self.conf.get('completion', None)
				if self.completion is None:
					self.log_error('Completion configuration is missing for Agent %s' % self.id)
					self._meta_['state'] = self.states.ERR_SETUP.value

					break

				upstream = self.conf.get('upstream', None)
				if upstream is None or 'name' not in upstream or 'description' not in upstream:
					self.log_error('Upstream configuration is missing or incomplete for Agent %s' % self.id)
					self._meta_['state'] = self.states.ERR_SETUP.value

					break

				self.name = upstream['name']
				self._meta_['capabilities'].append(self._capability(self.name, upstream['description']))

				you_are = self.conf.get('you_are', None)
				if you_are is not None:
					if type(you_are) is list:
						you_are = '\n'.join(you_are)

					if you_are == '':
						you_are = None
					else:
						you_are = {'role': 'system', 'content': you_are}

				self.you_are = you_are

				you_must = self.conf.get('you_must', None)
				if you_must is not None:
					if type(you_must) is list:
						you_must = '\n'.join(you_must)

					if you_must == '':
						you_must = None
					else:
						you_must = {'role': 'developer', 'content': you_must}

				self.you_must = you_must

				self._meta_['state'] = self.states.SETUP_OK.value

				if just_once:
					break

			if self._meta_['state'] == self.states.SETUP_OK.value:
				if completion is None:
					self.log_error('Error importing completion from litellm')
					self._meta_['state'] = self.states.ERR_COMPLETION.value

					break

				self._meta_['state'] = self.states.COMPLETION_OK.value

				if just_once:
					break

			if self._meta_['state'] == self.states.COMPLETION_OK.value:
				tools = []
				for agentic in self.tools:
					capabilities = agentic.meta.get('capabilities', None)
					if capabilities is None:
						self.log_error('Error piloting Agent %s: capabilities missing for tool %s' % (self.id, agentic.id))
						self._meta_['state'] = self.states.ERR_BUILDING_TOOLS.value

						return

					for capability in capabilities:
						if 'type' in capability and capability['type'] == 'function' and 'function' in capability:
							tools.append(capability)

						else:
							self.log_error('Error piloting Agent %s: invalid capability format for tool %s' % (self.id, agentic.id))
							self._meta_['state'] = self.states.ERR_BUILDING_TOOLS.value

							return

				if len(tools) > 0:
					self.completion['tools'] = tools

				self._meta_['state'] = self.states.READY.value

				if just_once:
					break


	def _capability(self, name, description):
		""" Defines a capability for the agent with the given name and description.

		Args:
			name (str): The name of the capability.
			description (str): A brief description of what the capability does.

		Returns:
			(dict): A dictionary representing the capability in the required format.
		"""

		return {
			'type': 'function',
			'function': {
				'name': name,
				'description': description,
				'parameters': {
					'type': 'object',
					'properties': {
						'content': {
							'type': 'string',
							'description': 'The content to the user prompt.'
						}
					},
					'required': ['content']
				},
				'returns': {
					'type': 'dict'
				}
			}
		}
