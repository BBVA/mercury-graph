from enum import Enum

from .agentic import Agentic


class SourceState(Enum):
	""" The `SourceState` is an enumeration that defines the possible states of the Source.
	"""
	CHUNKS_EMBED_ERR	= -6	# The chunks could not be embedded.
	CHUNKS_STORE_ERR	= -5	# The chunks could not be stored.
	CHUNKS_IDX_ERR		= -4	# The chunks could not be indexed.
	SECTIONS_IDX_ERR	= -3	# The sections could not be indexed.
	FILES_IDX_ERR		= -2	# The file names could not be indexed.
	ERR_FS_404			= -1	# The file system path does not exist.
	INITIAL				=  0	# The initial state of the source.
	FS_FOUND			=  1	# The file system has been found.
	FILES_IDX_OK		=  2	# The file names are indexed.
	SECTIONS_IDX_OK		=  3	# The sections (chapter, section, subsection, paragraph, ...) are indexed.
	CHUNKS_IDX_OK		=  4	# The chunks are indexed and ready to be processed.
	CHUNKS_STORED_OK	=  5	# The chunks are stored and ready to be processed.
	CHUNKS_EMBEDDED_OK	=  6	# The chunks are embedded and ready to be processed.
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

	"""

	def __init__(self, schema = None, endpoint = None, logger = None, extra_args = None):
		super().__init__(my_class = 'source', schema = schema, endpoint = endpoint, logger = logger)

		self.states = SourceState

		if extra_args is not None:
			self.conf = extra_args
		else:
			self.conf = {}

		self.pilot(0)	# Just to make .meta reflect the initial state.


	def _run(self, request):
		return {'status': 'ok'}


	def _meta(self):
		meta = {}
		meta['state'] = 0
		meta['conf'] = self.conf
		meta['capabilities'] = self._capabilities()

		return meta


	def _dry_run(self, request):
		return {'status': 'ok'}


	def pilot(self, intent, just_once = False):
		state = self.meta['state']

		if state < 0:
			self.log_error('Source is in error state %d' % state)
			return

		self.meta['state'] = self.states.READY.value


	def _capabilities(self):
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
