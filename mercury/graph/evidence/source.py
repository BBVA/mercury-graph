from .agentic import Agentic


class Source(Agentic):
	""" The Source is an Agentic interface to a corpus of documents.

	## Overview

	The Source can contain different types of documents and possibly call format conversion tools.
	Documents can be text or code.

	The Source provides:

	- A "chunking" interface to break documents into smaller pieces for easier processing.
	- A hierarchy that divides a corpus into a collection, document, section, paragraph and chunk.
	- An indexing system that provides unique identifiers for each chunk.
	- A persistence backend that possibly includes vectorization and embedding of the chunks for later retrieval.
	- An Agentic interface to everything above.

	"""

	def __init__(self, schema = None, parent = None, logger = None, extra_args = None):
		super().__init__(my_class = 'source', schema = schema, parent = parent, logger = logger)

		if extra_args is not None:
			self.conf = extra_args
		else:
			self.conf = {}


	def _run(self, request):
		return {'status': 'ok'}


	def _meta(self):
		return {'status': 'ok'}


	def _dry_run(self, request):
		return {'status': 'ok'}
