from abc import ABC, abstractmethod

import datetime


class Agentic(ABC):
	""" This is the parent of any class that is called by an Agent including the Agent itself.

	## Overview

	This class provides the layer that connects tools with agents. It is not a protocol but a method to discover a protocol the class
	itself implements and validates. It takes inspiration from the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/docs)
	while being lighter, oriented towards classes that coexist within the same process although they can also represent remote services.

	It provides a simple interface with three main methods:

	* `meta` for anything that is constant and can be cached: what the class can an cannot do, what input it expects and what
		output it produces.
	* `run` for the actual execution of a "query", i.e., the request is a valid dictionary created according to the meta.
	* `dry_run` for simulating the execution of a query, without actually running it. This validates the input and returns fast and
		descriptive feedback on errors.

	## Architecture

	Architecturally, all Agentic descendants form a tree. Each Agentic has an ID that is composed of the IDs of its parents, and of its
	own name joined by a /. Its name has the format: class_schema (schema is optional if there is only one instance
	of the class). Each of them can find each other, but can only run its descendants. Agents are Agentics too and provide the same
	interface. The root of the tree is an Endpoint. Endpoints are Agentic too, simplifying composing trees with other trees.

	## Validation

	The descendants are responsible for validating the input and returning/logging errors. Additionally, they can use the method
	`log_error()` to provide further details via the logger.

	## State

	State is managed internally and returned as part of the output. There are no separate methods for state checking but descendants can
	provide this information via `run`.

	## Logger

	The class can log events, errors, and other function calls and responses. The logger is optional can be used for debugging and
	can be as simple as a python list. I must provide an `append()` method to add new events. A custom method can filter events or add
	extra fields to the event.

	Attributes:

	* `id` (str): the ID of the Agentic, composed of the IDs of its parents and its own name.
	* `logger`: the logger to use for logging events. It must provide an `append()` method to add new events. It is optional and can be None.
	* `root` (Agentic): the root of the tree. It is used to find other Agentics in the tree.
	* `children` (dict): a dictionary of child Agentics, keyed by their IDs.

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

