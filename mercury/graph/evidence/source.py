import os, pickle

from collections import OrderedDict
from pathlib import Path

import chromadb as chroma

from .agentic import Agentic, AgenticRunInvalidRequest
from .source_parts import SourceState, SourceMaker, SourceFile, SourceEntity


class Source(Agentic):
	""" The Source is an Agentic interface to a corpus of documents.

	## Overview

	The Source can contain different types of documents and possibly call format conversion tools.
	Documents can be text or code.

	The Source provides:

	- A "chunking" interface to break documents into smaller pieces for easier processing.
	- A hierarchy that divides a corpus into: a collection (that manages many files), a document (a file) a section (which can be nested).
	- An indexing system that provides unique identifiers for each component.
	- A persistence backend that possibly includes vectorization and embedding of the chunks for later retrieval.
	- An Agentic interface to everything above.

	## Source Components

	The Source uses the following components to manage file conversion, chunking, indexing and to represent the parts of a document:

	- [`SourceNode`][mercury.graph.evidence.source_parts.SourceNode]: The base class to manage the index logic of all components.
	- [`SourceMaker`][mercury.graph.evidence.source_parts.SourceMaker]: The root SourceNode responsible for managing a tree of markdown files.
	- [`SourceFile`][mercury.graph.evidence.source_parts.SourceFile]: Each individual file as a SourceNode.
	- [`SourceEntity`][mercury.graph.evidence.source_parts.SourceEntity]: Each section, subsection, paragraph, table, figure, text, table cell or link
		in a markdown file as a SourceNode.

	## Known Limitations

	See:
		- [Warning](evidence_formats.md#warning)
		- [Limitations](evidence_source.md#known-limitations)

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
		self.name = schema

		self._maker	 = None
		self._cache	 = None
		self._chroma = None

		self._meta_	 = self._meta()	# Just to make .meta reflect the initial state.


	def _run(self, request):
		""" Runs the Source with the given request.

		(See [`Agentic.run()`][mercury.graph.evidence.Agentic.run].)
		"""

		call = self.call.get(request['name'], None)

		if call is None:
			self.log_error('Source does not have a function named "%s".' % request['function'])
			raise AgenticRunInvalidRequest

		index = request['arguments'].get('index', None)

		if index is None:
			self.log_error('Source function "%s" requires an "index" argument.' % request['function'])
			raise AgenticRunInvalidRequest

		ret = {'finish_reason': 'stop', 'message': call(index)}

		return ret


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
		# TODO: Implement the logic to simulate running the Source with the given request.


	def pilot(self, intent, just_once = False):
		""" Pilots the Source to a new state based on the given intent.

		(See [`Agentic.pilot()`][mercury.graph.evidence.Agentic.pilot].)
		"""

		if self.meta['state'] < 0:
			self.log_error('Source is in error state %d' % self.meta['state'])
			return

		while self.meta['state'] < intent:
			if self.meta['state'] == self.states.INITIAL.value:
				try:
					typ = self.conf['type']
					src = self.conf['src_path']
					dst = self.conf['dst_path']
					siz = self.conf.get('cluster_size', 256)
					ext = self.conf.get('extensions', None)
					pdf = self.conf.get('pdf_to_markdown', None)
					self._maker = SourceMaker(self.name, typ, src, dst, siz, ext, pdf)

				except:
					self.log_error('SourceMaker could not be created and initialized for Source "%s".' % self.name)
					self.meta['state'] = self.states.ERR_MAKER_INIT.value
					break

				self.meta['state'] = self.states.MAKER_INIT_OK.value

				if just_once:
					break

			if self.meta['state'] == self.states.MAKER_INIT_OK.value:
				if self._maker.build_indices():
					self.meta['state'] = self.states.MAKER_READY_OK.value
				else:
					self.log_error('SourceMaker could not build indices for Source "%s".' % self.name)
					self.meta['state'] = self.states.ERR_MAKER_INDEX.value
					break

				if just_once:
					break

			if self.meta['state'] == self.states.MAKER_READY_OK.value:
				self._setup_cache()		# No error condition. Worst case is no cache.
				self.meta['state'] = self.states.CACHE_READY_OK.value

				if just_once:
					break

			if self.meta['state'] == self.states.CACHE_READY_OK.value:
				if self._setup_chroma_db():
					self.meta['state'] = self.states.READY.value

				else:
					self.log_error('Source could not setup the vector database for Source "%s".' % self.name)
					self.meta['state'] = self.states.ERR_DB_SETUP.value

				break


	def get_children_idx(self, index = None):
		""" Returns the children indices following the SourceNode interface.

		(See [`SourceNode.get_children_idx()`][mercury.graph.evidence.source_parts.SourceNode.get_children_idx].)
		"""

		if (   self._maker is None
			or self._maker.state != self.states.MAKER_READY_OK.value
			or self.meta['state'] < self.states.READY.value):

			self.log_error('Source is not ready for get_children_idx("%s").' % index)

			return None

		if index is None or index == '':
			index = self._maker.index

		return self._maker.get_children_idx(index)


	def child(self, index):
		""" Returns the corresponding SourceNode object following the SourceNode interface and serializes it to a dictionary.

		(See [`SourceNode.child()`][mercury.graph.evidence.source_parts.SourceNode.child].)
		"""

		if (   self._maker is None
			or self._maker.state != self.states.MAKER_READY_OK.value
			or self.meta['state'] < self.states.READY.value):

			self.log_error('Source is not ready for child("%s").' % index)

			return None

		child = self._maker.child(index)

		if child is None:
			return None

		if type(child) is not SourceEntity:
			return {'type': 'object', 'class': str(type(child)), 'description': child.description}

		if child._children is None:
			return {'type': str(child.entity_type), 'content': child.content}

		return {'type': 'SourceEntity: %s' % child.entity_type, 'description': child.description}


	def close(self, endpoint_locked):
		""" Closes the Source and releases any resources it holds.

		(See [`Agentic.close()`][mercury.graph.evidence.Agentic.close].)
		"""

		if endpoint_locked:
			if self._cache is not None and self._cache_path is not None:
				fn = os.path.abspath(self._cache_path)

				pat = Path(fn).parent
				pat.mkdir(parents = True, exist_ok = True)

				with open(fn, 'wb') as f:
					pickle.dump(self._cache, f)

		self._cache	 = None
		self._chroma = None		# There is no need to explicitly .close(), .flush() ... That persists changes.
		self._maker	 = None


	def _setup_cache(self):
		""" Sets up the cache for the Source.

		The cache keeps an LRU (Least Recently Used) dictionary of SourceNode objects by index. Optionally, it can be persisted to disk
		as a pickle file. The cache size and path are configured in the Source's configuration.

		Returns:
			(bool): True if the cache was set up successfully, False if the Source does not have a cache.
		"""

		self._cache = None

		self._cache_path = self.conf.get('cache_path', '')
		if not self._cache_path.endswith('.pickle'):
			self._cache_path = None

		self._cache_size = self.conf.get('cache_size', 0)

		if self._cache_size > 0:
			if self._cache_path is not None and os.path.isfile(self._cache_path):
				try:
					with open(self._cache_path, 'rb') as f:
						self._cache = pickle.load(f)

				except:
					self.log_error('Source could not load cache from "%s".' % (self._cache_path))
					self._cache = OrderedDict()

			else:
				self._cache = OrderedDict()

			while len(self._cache) > self._cache_size:
				self._cache.popitem(last = False)

		return self._cache is not None


	def _setup_chroma_db(self):
		""" Sets up the Chroma vector database for the Source.

		The Chroma vector database is used to store embeddings of chunks for later retrieval. It is configured in the Source's
		configuration.

		Returns:
			(bool): True if the Chroma vector database was set up successfully or is not used, False if setup failed.
		"""

		self._chroma = None

		chroma_path = self.conf.get('chroma_path', None)

		if chroma_path is None:
			return True			# This is the neat way to disable ChromaDB.

		try:
			self._chroma = chroma.PersistentClient(path = chroma_path)

		except:
			self.log_error('Source failed to create Chroma client at path: "%s".' % (chroma_path))

			return False

		try:
			name = self.conf['chroma_descriptions_collection_name']

			self._chroma_descr = self._chroma.get_or_create_collection(name)

			name = self.conf['chroma_chunks_collection_name']

			self._chroma_chunks = self._chroma.get_or_create_collection(name)

		except:
			self.log_error('Source failed to create Chroma collections at path: "%s".' % (chroma_path))

			return False

		return True


	def _capabilities(self):
		""" Returns the capabilities of the Source.

		Returns:
			(list): A list of capabilities, each represented as a dictionary with the following keys:

				- 'type': The type of capability (e.g., 'function').
				- 'function': A dictionary containing details about the function

				The value of 'function' is:

				* 'name': The name of the function.
				* 'description': A brief description of what the function does.
				* 'parameters': A dictionary with 'type', 'properties', and 'required'
				* 'returns': A dictionary with 'type' and 'items'
		"""

		return [
			{
				'type': 'function',
				'function': {
					'name': 'get_items_by_index_%s' % self.name,
					'description': 'Get indices of the children of an index. Indices are either folders, files, sections or chunks.',
					'parameters': {
						'type': 'object',
						'properties': {
							'index': {
								'type': 'string',
								'description': 'Index whose children indices are required.'
							}
						},
						'required': ['index']
					},
					'returns': {
						'type': 'array',
						'items': {
							'type': 'string'
						}
					}
				}
			},
			{
				'type': 'function',
				'function': {
					'name': 'get_text_by_index_%s' % self.name,
					'description': 'Get the text at a given index.',
					'parameters': {
						'type': 'object',
						'properties': {
							'index': {
								'type': 'string',
								'description': 'Index of the text component.'
							}
						},
						'required': ['index']
					},
					'returns': {
						'type': 'string'
					}
				}
			}
		]
