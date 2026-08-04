import os

from abc import ABC, abstractmethod
from enum import Enum

from .agentic import Agentic


class SourceState(Enum):
	""" The `SourceState` is an enumeration that defines all possible states of any SourceNode or the Source. """

	ERR_DB_SETUP		= -30	# The Source failed to setup the vector database for descriptions or chunks.

	ERR_INDICES_LOAD	= -10	# The Source failed to load indices from persistence.

	ERR_MAKER_ACCESS	= -3	# The SourceMaker failed with the creation of some output file.
	ERR_MAKER_INDEX		= -2	# The SourceMaker could not index every file.
	ERR_MAKER_INIT		= -1	# The SourceMaker could not be created and initialized.

	INITIAL				=  0	# The initial state of the source.
	MAKER_INIT_OK		=  1	# The SourceMaker could be created and initialized.
	MAKER_INDEX_OK		=  2	# The SourceMaker could index every file.
	MAKER_READY_OK		=  3	# The SourceMaker either created every output file or is ready to create any on demand.

	INDICES_LOADED_OK	=  10	# The Source has loaded all known indices from persistence.

	CACHE_READY_OK		=  20	# The Source has initialized (possibly loaded, possibly created) a cache for SourceNode objects.

	DESCRIPTIONS_DB_OK	=  30	# The Source has opened a vector database all known descriptions, titles, section titles, etc.
	CHUNKS_DB_OK		=  31	# The Source has opened a vector database all known chunks.

	READY				=  100	# The source is ready to be processed.


class Source(Agentic):
	""" The Source is an Agentic interface to a corpus of documents.

	## Overview

	The Source can contain different types of documents and possibly call format conversion tools.
	Documents can be text or code.

	The Source provides:

	- A "chunking" interface to break documents into smaller pieces for easier processing.
	- A hierarchy that divides a corpus into: collection (a folder), document (a file), section (which is itself nested) and a chunk.
	- An indexing system that provides unique identifiers for each chunk.
	- A persistence backend that possibly includes vectorization and embedding of the chunks for later retrieval.
	- An Agentic interface to everything above.

	Args:
		schema (str): a schema (a unique name) to use for the Source's ID.
		endpoint (Agentic): an optional Endpoint. It becomes part of the Source's ID and is available via `self.endpoint`. If not
			provided, the Source becomes its own Endpoint.
		logger (list): an optional logger to use for logging events. It must provide an `append()` method to add new events.
		extra_args (dict): the configuration for the Source.
	"""

	def __init__(self, schema, extra_args, endpoint = None, logger = None):
		super().__init__(my_class = 'source', schema = schema, endpoint = endpoint, logger = logger)

		self.states = SourceState

		self.conf = extra_args

		self.pilot(0)	# Just to make .meta reflect the initial state.


	def _run(self, request):
		""" Runs the Source with the given request.

			(See [`Agentic.run()`][mercury.graph.evidence.Agentic.run].)
		"""
		return {'status': 'ok'}


	def _meta(self):
		""" Returns the metadata of the Source.

			(See [`Agentic.meta()`][mercury.graph.evidence.Agentic.meta].)
		"""
		meta = {}
		meta['state'] = 0
		meta['conf'] = self.conf
		meta['capabilities'] = self._capabilities()

		return meta


	def _dry_run(self, request):
		""" Simulates running the Source with the given request.

			(See [`Agentic.dry_run()`][mercury.graph.evidence.Agentic.dry_run].)
		"""
		return {'status': 'ok'}


	def pilot(self, intent, just_once = False):
		""" Pilots the Source to a new state based on the given intent.

			(See [`Agentic.pilot()`][mercury.graph.evidence.Agentic.pilot].)
		"""
		state = self.meta['state']

		if state < 0:
			self.log_error('Source is in error state %d' % state)
			return

		self.meta['state'] = self.states.READY.value


	def _capabilities(self):
		""" Returns the capabilities of the Source.

		Returns:
			(list): A list of capabilities, each represented as a dictionary with the following keys:

				- "type": The type of capability (e.g., "function").
				- "function": A dictionary containing details about the function

				The value of "function" is:

				* "name": The name of the function.
				* "description": A brief description of what the function does.
				* "parameters": A dictionary with "type", "properties", and "required"
				* "returns": A dictionary with "type" and "items"
		"""
		return [
			{
				"type": "function",
				"function": {
					"name": "get_items_by_index",
					"description": "Get indices of the children of an index. Indices are either folders, files, sections or chunks.",
					"parameters": {
						"type": "object",
						"properties": {
							"index": {
								"type": "string",
								"description": "Index whose children indices are required."
							}
						},
						"required": ["index"]
					},
					"returns": {
						"type": "array",
						"items": {
							"type": "string"
						}
					}
				}
			},
			{
				"type": "function",
				"function": {
					"name": "get_text_chunk_by_index",
					"description": "Get the text at a given chunk index.",
					"parameters": {
						"type": "object",
						"properties": {
							"index": {
								"type": "string",
								"description": "Index of the text chunk."
							}
						},
						"required": ["index"]
					},
					"returns": {
						"type": "string"
					}
				}
			}
		]
