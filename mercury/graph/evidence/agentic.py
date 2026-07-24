import datetime, re

from abc import ABC, abstractmethod
from enum import Enum


class AgenticRunException(Exception):
	"""Base class for all Agentic.run() and .dry_run() exceptions."""
	pass


class AgenticRunInvalidRequest(AgenticRunException):
	"""The caller supplied an invalid request."""
	pass


class AgenticRunInvalidState(AgenticRunException):
	"""The Agentic is not in a state where the operation is allowed."""
	pass


class AgenticRunFailed(AgenticRunException):
	"""The Agentic attempted to execute the request but failed."""
	pass


class AlwaysReadyState(Enum):
	""" The `AlwaysReadyState` is valid for any Agentic that does not need piloting.
	"""
	INITIAL	=  0	# The initial state of the Agentic.
	READY	=  100	# The Agentic is ready. Calling the parent's pilot() method will set that state, doing nothing else.


class Agentic(ABC):
	""" This is the parent of any class that is called by an Agent including the Agent itself.

	## Overview

	This class provides the layer that connects tools with agents. It is not a protocol but a method to discover a protocol the class
	itself implements and validates. It takes inspiration from the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/docs)
	while being lighter, oriented towards classes that coexist within the same process although they can also represent remote services.

	It provides a simple interface with four main methods:

	* `meta` for the object's metadata: What the class can do, what input it expects and what output it produces, what state
		the object is in, ...
	* `run` for the actual execution of a "query", i.e., the request is a valid dictionary created according to the meta.
	* `dry_run` for simulating the execution of a query, without actually running it. This validates the input and returns fast and
		descriptive feedback on errors.
	* `pilot` for piloting the object to a desired state. Typically, an Agentic object must be in a READY state (after having set up
		services, loaded data, etc.) before it can accept queries. The pilot() method "drives" the object to a desired state.

	## Parts of a Agentic object

	### ID

	Architecturally, all Agentic descendants form a graph inside some Endpoint. Each Agentic has an ID that is composed of the IDs of
	its parents, and of its own name joined by a /. Its name has the format: class_schema (schema is optional if there is only one instance
	of the class). Agentics can use other Agentics within the same Endpoint, but they must require specific ids in the architecture.
	When that requirement can be satisfied, the Endpoint will provide the Agentic with the tool by calling its `add_tool` method.

	### Capabilities

	Think of capabilities as calling tools. Each tool has a unique function name, it expects input and returns output. That is specified
	in the object's `.meta`. There is a key called "capabilities" which is a list of dictionaries in the format:
	"name": {"description": ..., "parameters": ..., "returns": ...}. The "parameters" is a dictionary with the format: {"type": "object",
	"properties": ..., "required": [-- the names of the required properties --]}. Each property is a dictionary with the format:
	{"name": {"type": "...", "description": "..."}}. "returns" is a dictionary with the same format as "parameters" except it does not
	have a "required" key.

	### State

	State is managed internally and exposed in the `.meta` attribute as the key "state" containing an integer number. Additionally,
	the number can have text descriptions in the `.states` attribute which is an Enum class. The name of the state can be obtained using
	the method `state_name()`. By convention, negative numbers represent non recoverable errors, zero is the initial state, and positive
	are sorted up to 100 which is the READY state. The states 1..99 represent intermediate states that are specific to each class.

	### Intent and piloting

	Intent is a desired state for the object. Piloting is the process of taking the object to a desired state. This is done typically
	using the `mge` cli. An Agentic that is "always ready" does not need to define its own pilot() method. The `mge` will pilot a complete
	Endpoint and the Endpoint will pilot its Agentics. A class that overrides the `pilot()` method must set the state according to the
	success or failure of the piloting process.

	### Running queries

	This is done using the `run()` and `dry_run()` methods. Their arguments are identical, but their logic and return values are different.
	The `run()` method executes and raises exceptions on errors. The `dry_run()` checks the request and the state of the object and
	returns a dictionary with a status code and a description. (See the docstrings of the methods for details.)

	### Closing the Agentic

	The agentic has a method `close()` that is called just once when the Endpoint is closing. The Agentic can track its own state
	to know if it was modified and is informed by the Endpoint if it was locked for writing. The Endpoint is locked during the pilot
	and serve phases. It that case, if the Agentic was modified, it should persist its state to disk or a database. (see the docstring
	of close() for details.)

	## Validation and Debugging

	The descendants are responsible for validating the input and returning/logging errors. Additionally, they can use the method
	`log_error()` to provide further details via the logger.

	### Logger

	The class can log events, errors, and other function calls and responses. The logger is optional can be used for debugging and
	can be as simple as a python list. I must provide an `append()` method to add new events. A custom method can filter events or add
	extra fields to the event.

	## API:

	Attributes:

	* `id` (str): the ID of the Agentic, composed of the IDs of its endpoint, class, its own name and an optional schema.
	* `logger`: the logger to use for logging events. It must provide an `append()` method to add new events. It is optional.
	* `endpoint` (Agentic): the Endpoint at the root of the architecture.
	* `tools` (dict): a dictionary of the Agentics it can use as tools, keyed by their IDs.
	* `states` (Enum): an optional Enum class that defines names for the states of an Agentic. It is used to improve readability and cli
	argument parsing.

	Arguments:

	* `my_class`: the name of the class, used to build the ID. It must ba a string of letters, numbers, and underscores. Typically,
	it is the name of the class in lowercase.
	* `schema`: an optional string to distinguish different instances of the same class. It is a schema (like a database, a graph,
	ontology, etc.) that the class is serving.
	* `endpoint`: an optional endpoint Agentic. If not provided, the Agentic is the Endpoint itself.
	* `logger`: an optional logger. If not provided, no logging will be done.

	"""

	def __init__(self, my_class, schema = None, endpoint = None, logger = None):
		self.id		  = my_class
		self.logger	  = logger
		self.seq_num  = 0
		self.endpoint = self
		self.tools	  = {}
		self.states	  = AlwaysReadyState
		self._meta_	  = None

		if schema is not None:
			self.id += '_' + schema

		if endpoint is not None:
			self.id		  = endpoint.id + '/' + self.id
			self.endpoint = endpoint


	@abstractmethod
	def _run(self, request):
		""" This is the method that actually runs the query. It MUST be implemented by the descendants. """
		pass


	@abstractmethod
	def _meta(self):
		""" This is the method that returns the metadata of the class. It MUST be implemented by the descendants. """
		pass


	@abstractmethod
	def _dry_run(self, request):
		""" This is the method that simulates the execution of a query. It MUST be implemented by the descendants. """
		pass


	@property
	def meta(self):
		""" This the object's metadata as a dictionary.

		It is cached after the first call, but classes can modify the ._meta_ dictionary directly to change the metadata.
		"""
		if self._meta_ is None:
			self._meta_ = self._meta()

		return self._meta_


	def add_tool(self, agentic):
		""" Adds a tool (another Agentic this one can use) to the Agentic.

		Arguments:
		* `agentic` (Agentic): the tool to add. It must be an Agentic and its endpoint must be the same as the current Agentic's.
		"""
		self.tools[agentic.id] = agentic


	def log_error(self, message):
		""" Logs an error message.

		The class can use this to introduce events in the logger.

		Arguments:
		* `message` (str): the error message to log.
		"""
		if self.logger is not None:
			event = {'type': 'error', 'timestamp': self._now(), 'id': self.id, 'seq_num': self.seq_num, 'error': message}

			self.logger.append(event)
			self.seq_num += 1


	def run(self, request):
		""" Runs a query.

		The request is a valid (ChatGPT/litellm function call) dictionary. The argument evaluation can be done by the class or delegated
		to litellm in the case of agents. This method does not provide user feedback on errors, other than raising exceptions that
		are descendants of AgenticRunException (e.g., AgenticRunInvalidRequest, AgenticRunInvalidState, AgenticRunFailed).
		The returned value does not provide any status key, it just assumes the request was successful.
		The returned value is a dictionary similar to a response.choices[0] in the OpenAI API, something with a "message" key and a
		"finish_reason" key. The "message" can be a string or a dictionary with anything.

		Arguments:
		* `request` (dict): the request to run.
		"""
		if self.logger is not None:
			event = {'type': 'request', 'timestamp': self._now(), 'id': self.id, 'seq_num': self.seq_num, 'request': request}

			self.logger.append(event)

		ret = self._run(request)

		if self.logger is not None:
			event = {'type': 'response', 'timestamp': self._now(), 'id': self.id, 'seq_num': self.seq_num, 'response': ret}

			self.logger.append(event)
			self.seq_num += 1

		return ret


	def dry_run(self, request):
		""" Simulates the execution of a query.

		The request is a valid (ChatGPT/litellm function call) dictionary identical to the one that would be passed to `run()` if validated.
		This method does not raise exceptions, it provides feedback. It should not just validate the request, but also anticipate
		the readiness of the Agentic whenever possible to prevent an AgenticRunInvalidState on run().

		The return value is a {'status': 0, 'description': 'Ok.'} dictionary. The status is 0 for success. 1 for busy, 2 for invalid
		request with an appropriate description.

		Arguments:
		* `request` (dict): the request to simulate.
		"""
		return self._dry_run(request)


	def pilot(self, intent, just_once = False):
		""" Pilots the object to a desired state.

		In the parent class, this method returns the object as "always ready". The classes that need piloting must override it.

		Arguments:
		* `intent` (str): the desired state to pilot to. It must be a valid state name in the object's meta.
		* `just_once` (bool): An optional argument to break without necessarily reaching the desired state after completing one iteration.
			The iteration is Agentic specific and can be anything, (E.g., a complete file chunked and processed, ...) That parameter is
			intended for when piloting can take hours or days and the user wants a finer control of the process.
		"""
		if self._meta_ is None:
			self._meta_ = self._meta()

		self._meta_['state'] = AlwaysReadyState.READY.value


	def close(self, endpoint_locked):
		""" Closes the Agentic.

		This method is called just once when the Endpoint is closing. The Agentic can track its own state to know if it was modified and
		is informed by the Endpoint if it was locked for writing. The Endpoint is locked during the pilot and serve phases. It that case,
		if the Agentic was modified, it should persist its state to disk or a database.

		Arguments:
		* `endpoint_locked` (bool): True if the Endpoint is locked for writing, False otherwise.
		"""
		pass


	def state_name(self, state):
		""" Returns the name of a state given its integer value.

		Arguments:
		* `state` (int): the integer value of the state.
		"""
		if self.states is not None:
			try:
				ret = self.states(int(state)).name

			except ValueError:
				ret = None

			return ret


	@staticmethod
	def _normalize_name(name):
		""" Normalizes a name to be used as an ID.

		That replaces spaces with underscores and removes any character that is not a letter, number, or underscore.

		Arguments:
		* `name` (str): the name to normalize.
		"""
		name = name.replace(' ', '_')
		name = re.sub('[^a-zA-Z0-9_]', '', name)

		return name


	@staticmethod
	def _now():
		""" Returns the current time as a formatted string. """
		return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
