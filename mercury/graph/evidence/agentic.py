from abc import ABC, abstractmethod

import datetime


class Agentic(ABC):
	""" This is the parent of any class that is called by an Agent.

	It provides a simple interface with two main methods:

		- `meta` for anything that is constant and can be cached: what the class can an cannot do, what input it expects and what
		output it produces.
		- `run` for the actual execution of a "query", i.e., the request is a valid dictionary created according to the meta.

	Validation: The descendants are responsible for validating the input and returning/logging any error. Additionally, they can
	use the method `log_error()` to provide further details.

	Architecture: All the Agentic descendants constitute an architecture. That architecture is a tree. Each Agentic has an ID that is
	composed of the IDs of its ancestors, and of its own name. Its name has the format: class_schema (schema is optional if there is only
	one instance of the class). Each of them can find each other, but can only run its descendants. Agents are Agentics.

	State: State is managed internally and returned as part of the output. The class does not expose its state otherwise.

	Logger: The class can log events, errors, and other function calls and responses.

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
		pass


	@abstractmethod
	def _meta(self):
		pass


	@property
	def meta(self):
		if self._meta_ is None:
			self._meta_ = self._meta()

		return self._meta_


	def add_child(self, child):
		self.children[child.id] = child


	def log_error(self, message):
		if self.logger is not None:
			event = {'type': 'error', 'timestamp': datetime.datetime.now(), 'id': self.id, 'seq_num': self.seq_num, 'error': message}

			self.logger.append(event)


	def run(self, request):
		if self.logger is not None:
			event = {'type': 'request', 'timestamp': datetime.datetime.now(), 'id': self.id, 'seq_num': self.seq_num, 'request': request}

			self.logger.append(event)

		ret = self._run(request)

		if self.logger is not None:
			event = {'type': 'response', 'timestamp': datetime.datetime.now(), 'id': self.id, 'seq_num': self.seq_num, 'response': ret}

			self.logger.append(event)
			self.seq_num += 1

		return ret
