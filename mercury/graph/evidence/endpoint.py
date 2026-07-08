import json, os

from enum import Enum

from .agentic import Agentic


class LockState(Enum):
	""" The `LockState` is an enumeration that defines the possible states of the Endpoint lock.
	"""
	FORCE_FREE	 = -2	# Special command to force the mutex to be free. This is a dangerous operation that should be used with caution.
	INIT_IF_NONE = -1	# Special command create the mutex if it does not exist. Just returns the state if it does.
	FREE		 =  0	# The command to free the mutex and the state when free.
	LOCK		 =  1	# The command to lock the mutex and the state when locked.
	LOCK_FAILED	 =  2	# The state when a LOCK failed. Maybe locked by another process or not available.
	FREE_FAILED	 =  3	# The state when a FREE failed. Only if the mutex is not available.


class Endpoint(Agentic):
	""" The `Endpoint` is the class that serves an entire Agentic tree to the outside world.

	## Overview

	An `Endpoint` is a full project that contains any number of Agentic objects. It's metadata lives in a folder that contains a
	`mge_endpoint.json` file and a file named either `mge_endpoint.free` or `mge_endpoint.locked` that acts as a write mutex.
	`Endpoint` is the only object that owns the architecture of the tree.

	For any "outside" Agentic user, an `Endpoint` is just another Agentic service. It is a tree of Agentic objects.
	So an Agentic ecosystem is a giant graph made of trees that use trees that use trees, etc.

	### What the Endpoint manages

	* The mutex providing exclusive write access to the tree. The Endpoint is locked when the cli either serves or pilots the Endpoint
		or it can also be programmatically by calling the `lock()` method. This is mandatory when the metadata is modified.
	* The definition of the architecture. The Agentics are defined here but may be located anywhere.
	* It's own Agentic API.
	* Internals like map of the names of its Agentics to provide valid id.

	### http interface

	The cli provides a simple http interface to the Endpoint. The Endpoint exposes its Agentic API like any other Agentic object.

	"""

	def __init__(self, path = None, logger = None):

		if not os.path.isdir(path):
			raise ValueError('The path "%s" is not a valid directory.' % path)

		self.home	 = os.path.abspath(path)
		schema		 = self._normalize_name(os.path.basename(self.home))
		self.conf_fn = os.path.join(self.home, 'mge_endpoint.json')
		self.lock_fn = os.path.join(self.home, 'mge_endpoint.locked')
		self.free_fn = os.path.join(self.home, 'mge_endpoint.free')

		if not os.path.isfile(self.conf_fn):
			raise ValueError('The path "%s" is not a valid Endpoint. The file "mge_endpoint.json" is missing.' % self.conf_fn)

		self.conf = json.load(open(self.conf_fn, 'r'))

		self.lock(LockState.INIT_IF_NONE)

		super().__init__(my_class = 'endpoint', schema = schema, parent = None, logger = logger)


	def lock(self, cmd):
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
		return {'status': 'ok', 'message': 'Endpoint is running.'}


	def _meta(self):
		return {'status': 'ok', 'state' : 'ready', 'message': 'Endpoint is running.'}


	def _dry_run(self, request):
		return {'status': 'ok', 'message': 'Endpoint is running.'}

