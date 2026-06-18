from abc import ABC, abstractmethod

import datetime


class Agentic(ABC):
	""" This is the parent of any class that is called by an Agent.

	## Overview

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
	interface. The root of the tree is an Endpoint. Endpoints are Agentic too simplifying composing trees with other trees.

	## Validation

	The descendants are responsible for validating the input and returning/logging any error. Additionally, they can use the method
	`log_error()` to provide further details via de logger.

	## State

	State is managed internally and returned as part of the output. There are no separate methods for state checking but descendants can
	provide this information via `run`.

	## Logger

	The class can log events, errors, and other function calls and responses. The logger is optional can be used for debugging and
	can be as simple as a python list. I must provide an `append()` method to add new events. A custom method can filter events or add
	extra fields to the event.

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


	@abstractmethod
	def _dry_run(self, request):
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


	def dry_run(self, request):
		return self._dry_run(request)

