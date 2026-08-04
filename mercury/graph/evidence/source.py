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


class SourceNode(ABC):
	""" Everything in the Source is a tree of SourceNodes: A Maker, a File, an Entity, even a Chunk (a node with no children).

	## Overview

	This class has the common interface to manage indices in the tree. It provides:

	- Attributes: type, name, description and state
	- A mechanism to locate the SourceNodes higher in the tree via the `parent` attribute.
	- A mechanism to index its children in the tree via the `get_children_idx()` method.
	- A mechanism to access its children in the tree via the `child()` method.

	## API:

	Args:
		index (str): the index of this SourceNode in the tree.
		parent (SourceNode): the parent of this SourceNode in the tree.
	"""

	def __init__(self, index, parent = None):
		self._index  = index
		self._parent = parent
		self._type	 = None
		self._name	 = None
		self._descr	 = None

		self.state = SourceState.INITIAL


	@property
	def type(self):
		return self._type


	@property
	def index(self):
		return self._index


	@property
	def name(self):
		return self._name


	@property
	def description(self):
		return self._descr


	@abstractmethod
	def get_children_idx(self):
		""" Returns the children of this SourceNode.

		Returns:
			(list): A list of children indices.
		"""
		pass


	@abstractmethod
	def child(self, index):
		""" Returns the child of this SourceNode with the given index.

		Args:
			index (str): the index of the child to return.

		Returns:
			(SourceNode): The child SourceNode with the given index.
		"""
		pass


class SourceMaker(SourceNode):
	""" The SourceMaker is the root SourceNode that is responsible for creating a tree of SourceFile objects.

	A Source only has one SourceMaker. An Endpoint can have as many Sources as required.

	It may do nothing, when the Source is already a tree markdown files on disk, or it can mirror a tree of PDF files as their
	corresponding markdown files, or it may dump large XML files into a tree of markdown files.

	Args:
		index (str): the index of this SourceMaker in the tree.
		type (str): the type of this SourceMaker. It can be one of: "pdf_mirror", "xml_stream" or "markdown_tree".
		name (str): the name of this SourceMaker.
		src_path (str): the path to the source files. (None for "markdown_tree" type.)
		dst_path (str): the path to the destination markdown files.
	"""

	def __init__(self, index, type, name, src_path, dst_path):
		super().__init__(index)

		if type not in ['pdf_mirror', 'xml_stream', 'markdown_tree']:
			raise ValueError('Invalid type: %s' % type)

		self._type	= type
		self._name	= name
		self._src	= src_path
		self._dst	= dst_path
		self._descr	= 'SourceMaker: %s, type: %s, output: %s' % (self._name, self._type, self._dst)


	def build_indices(self):
		pass
	# TODO: Implement the logic to build indices for the SourceMaker.


	def build_output(self):
		pass
	# TODO: Implement the logic to build output files for the SourceMaker.


	def get_children_idx(self):
		pass
	# TODO: Implement the logic to return the children indices of the SourceMaker.


	def child(self, index):
		pass
	# TODO: Implement the logic to return the child of the SourceMaker with the given index.



class SourceFile(SourceNode):
	""" The SourceFile is a SourceNode represents a single markdown file in the Source. It serves the file as a tree of SourceEntity
	objects, one for each section, subsection, paragraph, table, figure, etc. in the markdown file.

	Args:
		index (str): the index of this SourceFile in the tree.
		parent (SourceMaker): The SourceMaker that owns this SourceFile.
		path (str): the path to the markdown file.
	"""

	def __init__(self, index, parent, path):
		super().__init__(index, parent)

		if not os.path.isfile(path):
			raise ValueError('Invalid file path: %s' % path)

		self._type	= 'file'
		self._name	= path.split('/')[-1]
		self._descr	= 'SourceFile: %s' % self._name

		self.path = path


	def get_children_idx(self):
		pass
	# TODO: Implement the logic to return the children indices of the SourceFile.


	def child(self, index):
		pass
	# TODO: Implement the logic to return the child of the SourceFile with the given index.


class SourceEntity(SourceNode):
	""" The SourceEntity is a SourceNode that represents a single section, subsection, paragraph, table, figure, etc. in a markdown
	file. It serves either smaller SourceEntity objects nested within it, or a single Chunk object (a node with no children).

	## Types of SourceEntity

	  * **Header1 .. Header6**: A section starting with a markdown header, until the next header of the same or lower level. It includes
		all the content in between, including nested headers of higher levels.
	  * **Enum1 .. EnumN**: A section starting with a markdown enumeration, possibly nested, until the enumeration ends.
	  * **Table**: A complete markdown table, including the header and all rows.

	Args:
		index (str): the index of this SourceEntity in the tree.
		parent (SourceFile or SourceEntity): The parent SourceNode that contains this SourceEntity.
		content (list of str): The lines of the original SourceFile that contain this SourceEntity. The content is always a subset of
			complete lines of the SourceFile. This may change in the future to prevent giant objects stored in a single line. The
			SourceMaker should take care of splitting, but when the SourceMaker's type is "markdown_tree" markdown is just accepted as is.
	"""

	def __init__(self, index, parent, content):
		super().__init__(index, parent)

		self.content  = content
		self.children = None

		self.get_children_idx()		# This identifies the type, name and description from the content. Runs just one time.


	def get_children_idx(self):
		""" This parses the content to identify the children of this SourceEntity.

		While parsing, it also sets the type, name and description of this SourceEntity. E.g., the description of a title is the title
		itself. It builds a dictionary with the children of the next level in the tree. The children are either deeper SourceEntity objects
		or chunks containing text, a link or a cell in a table.
		"""

		if self.children is not None:
			return list(self.children.keys())

	# TODO: Implement the logic to return the children indices of the SourceEntity.


	def child(self, index):
		""" Returns the child of this SourceEntity with the given index.

		Args:
			index (str): the index of the child to return.

		Returns:
			(SourceEntity or Chunk): The child with the given index.
		"""
		if self.children is None:
			return None

		return self.children.get(index, None)



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
