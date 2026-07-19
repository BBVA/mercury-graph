import datetime, re

from abc import ABC, abstractmethod


class Agentic(ABC):
	""" This is the parent of any class that is called by an Agent including the Agent itself.

	## Overview

	This class provides the layer that connects tools with agents. It is not a protocol but a method to discover a protocol the class
	itself implements and validates. It takes inspiration from the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/docs)
	while being lighter, oriented towards classes that coexist within the same process although they can also represent remote services.

	It provides a simple interface with four main methods:

	* `meta` for the object's metadata: What the class can do, what input it expects and what output it produces, what state
		the object is in, ... That may be constant and can be cached, typically it is a dictionary and the object can provide some mix
		of constant and variable metadata.
	* `run` for the actual execution of a "query", i.e., the request is a valid dictionary created according to the meta.
	* `dry_run` for simulating the execution of a query, without actually running it. This validates the input and returns fast and
		descriptive feedback on errors.
	* `pilot` for piloting the object to a desired state. This is different from `run` which runs queries. Piloting is typically class
	specific and involves things like setting up services, loading data, etc.

	## Parts of a Agentic object

	### ID

	Architecturally, all Agentic descendants form a tree. Each Agentic has an ID that is composed of the IDs of its parents, and of its
	own name joined by a /. Its name has the format: class_schema (schema is optional if there is only one instance
	of the class). Each of them can find each other, but can only run its descendants. Agents are Agentics too and provide the same
	interface. The root of the tree is an Endpoint. Endpoints are Agentic too, simplifying composing trees with other trees.

	### Capabilities

	Think of capabilities as calling tools. Each tool has a unique function name, it expects input and returns output. That is specified
	in the object's `.meta`. There is a key called "capabilities" which is a list of dictionaries in the format:
	"name": {"description": ..., "parameters": ..., "returns": ...}. The "parameters" is a dictionary with the format: {"type": "object",
	"properties": ..., "required": [-- the names of the required properties --]}. Each property is a dictionary with the format:
	{"name": {"type": "...", "description": "..."}}. "returns" is a dictionary with the same format as "parameters" except it does not
	have a "required" key.

	### State

	State is managed internally and exposed in the `.meta` attribute as the key "state" containing an integer number. Additionally,
	meta can also contain a "state_names" dictionary like: `{"error_xxx": -9, "initial": 0, "loaded": 1, "ready": 100}` to improve
	readability and cli argument parsing. Additionally, state that reports errors specific to a query will be returned by the `run` method.

	### Intent and piloting

	Intent is a desired state for the object. Piloting is the process of taking the object to a desired state. This is done typically
	using the `mge` cli. An Agentic that is "always ready" does not need to define its own pilot() method. The `mge` will pilot a complete
	Endpoint and the Endpoint will pilot its Agentics. A class that overrides the `pilot()` method must set the state according to the
	success or failure of the piloting process.

	## Validation and Debugging

	The descendants are responsible for validating the input and returning/logging errors. Additionally, they can use the method
	`log_error()` to provide further details via the logger.

	### Logger

	The class can log events, errors, and other function calls and responses. The logger is optional can be used for debugging and
	can be as simple as a python list. I must provide an `append()` method to add new events. A custom method can filter events or add
	extra fields to the event.

	## API:

	Attributes:

	* `id` (str): the ID of the Agentic, composed of the IDs of its parents and its own name.
	* `logger`: the logger to use for logging events. It must provide an `append()` method to add new events. It is optional.
	* `root` (Agentic): the root of the tree. It is used to find other Agentics in the tree.
	* `children` (dict): a dictionary of child Agentics, keyed by their IDs.
	* `states` (Enum): an optional Enum class that defines names for the states of an Agentic. It is used to improve readability and cli
	argument parsing.

	Arguments:

	* `my_class`: the name of the class, used to build the ID. It must ba a string of letters, numbers, and underscores. Typically,
	it is the name of the class in lowercase.
	* `schema`: an optional string to distinguish different instances of the same class. It is a schema (like a database, a graph,
	ontology, etc.) that the class is serving.
	* `parent`: an optional parent Agentic. If not provided, the Agentic is the root of the tree.
	* `logger`: an optional logger. If not provided, no logging will be done.

	"""

	def __init__(self, my_class, schema = None, parent = None, logger = None):
		self.id		  = my_class
		self.logger	  = logger
		self.seq_num  = 0
		self.root	  = self
		self.children = {}
		self.states	  = None
		self._meta_	  = None

		if schema is not None:
			self.id += '_' + schema

		if parent is not None:
			self.id	  = parent.id + '/' + self.id
			self.root = parent.root

			parent.add_child(self)


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
		""" This the object's metadata as a dictionary. It is cached after the first call. """
		if self._meta_ is None:
			self._meta_ = self._meta()

		return self._meta_


	def add_child(self, child):
		""" Adds a child to the Agentic.

		Arguments:
		* `child` (Agentic): the child Agentic to add. It must be an instance of Agentic and its parent must be the current Agentic.
		"""

		self.children[child.id] = child


	def log_error(self, message):
		""" Logs an error message.

		Arguments:
		* `message` (str): the error message to log.
		"""
		if self.logger is not None:
			event = {'type': 'error', 'timestamp': datetime.datetime.now(), 'id': self.id, 'seq_num': self.seq_num, 'error': message}

			self.logger.append(event)


	def run(self, request):
		""" Runs a query.

		Arguments:
		* `request` (dict): the request to run.
		"""
		if self.logger is not None:
			event = {'type': 'request', 'timestamp': datetime.datetime.now(), 'id': self.id, 'seq_num': self.seq_num, 'request': request}

			self.logger.append(event)

		ret = self._run(request)

		if self.logger is not None:
			event = {'type': 'response', 'timestamp': datetime.datetime.now(), 'id': self.id, 'seq_num': self.seq_num, 'response': ret}

			self.logger.append(event)
			self.seq_num += 1

		return ret


	def dry_run(self, request):
		""" Simulates the execution of a query.

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

		self._meta_['state'] = 0x7fffFFFF	# This is higher than any state. That means the object is always "more than ready".


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
