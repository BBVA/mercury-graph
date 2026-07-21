import json, os, re

from enum import Enum

from .agent   import Agent
from .agentic import Agentic
from .agentic_graph import AgenticGraph
from .evidence_graph import EvidenceGraph
from .formalizer import Formalizer
from .source import Source


class LockState(Enum):
	""" The `LockState` is an enumeration that defines the possible states of the Endpoint lock.
	"""
	FORCE_FREE	 = -2	# Special command to force the mutex to be free. This is a dangerous operation that should be used with caution.
	INIT_IF_NONE = -1	# Special command create the mutex if it does not exist. Just returns the state if it does.
	FREE		 =  0	# The command to free the mutex and the state when free.
	LOCK		 =  1	# The command to lock the mutex and the state when locked.
	LOCK_FAILED	 =  2	# The state when a LOCK failed. Maybe locked by another process or not available.
	FREE_FAILED	 =  3	# The state when a FREE failed. Only if the mutex is not available.


class EndPointState(Enum):
	""" The `EndPointState` is an enumeration that defines the possible states of the Endpoint.
	"""
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

	For any "outside" Agentic user, an `Endpoint` is just another Agentic service. It is a graph of Agentic objects.

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
		using the Endpoint's Agentic interface. Piloting is a process typically done using the `mge` cli.
	* The mutex providing exclusive write access to the objects. The Endpoint is locked when the cli either serves or pilots the Endpoint.
		It can also be done programmatically by calling the `lock()` method. This is mandatory when the metadata is modified.
	* It's own Agentic API. This exposes a set of functions merged from the Agentics that are marked as "exposed" in the Endpoint's conf.
	* The interdependencies within the Agentic objects.

	### Http interface

	The cli provides a simple http interface to the Endpoint. The Endpoint exposes its Agentic API like any other Agentic object.

	### Self configuration

	Endpoints can use Agents to complete and verify their configuration with or without human intervention.

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


	def __str__(self):
		""" Returns a console friendly summary of the Endpoint state. """

		bold	 = '\033[1m'
		italic	 = '\033[3m'
		reset	 = '\033[0m'
		labels	 = ['name', 'creation_date', 'mge_version', 'description']
		sections = ['sources', 'ontologies', 'formalizers', 'evidence_graphs', 'agents', 'custom_agentics']
		unknown	 = '%sunknown%s' % (italic, reset)
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
			name = 'no name'

		txt.append('   %-14s: %s %s(%s)%s' % ('state', state, italic, name, reset))

		for section_name in sections:
			items = self.conf.get(section_name, {})
			txt.append('')
			txt.append('  %s%s %s%s (%d total)' % (bold, icons[section_name], section_name, reset, len(items)))

			if len(items) == 0:
				txt.append('     %sempty%s' % (italic, reset))
				continue

			for item_name in sorted(items.keys()):
# TODO: Get the state of each item.
				txt.append('     - %s: %s' % (item_name, unknown))

		return '\n'.join(txt)


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
		return {'state' : 0}


	def _dry_run(self, request):
		return {'status': 'ok', 'message': 'Endpoint is running.'}


	def pilot(self, intent, just_once = False):
		pass


	def _json_load(self, fn, recursion_depth = 0):

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
