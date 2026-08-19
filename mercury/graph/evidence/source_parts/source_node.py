from abc import ABC, abstractmethod
from enum import Enum


class SourceState(Enum):
	""" The `SourceState` is an enumeration that defines all possible states of any SourceNode or the Source. """

	ERR_DB_SETUP		= -20	# The Source failed to setup the vector database for descriptions or chunks.

	ERR_MAKER_ACCESS	= -3	# The SourceMaker failed with the creation of some output file.
	ERR_MAKER_INDEX		= -2	# The SourceMaker could not index every file.
	ERR_MAKER_INIT		= -1	# The SourceMaker could not be created and initialized.

	INITIAL				=  0	# The initial state of the source.
	MAKER_INIT_OK		=  1	# The SourceMaker could be created and initialized.
	MAKER_READY_OK		=  2	# The SourceMaker either created every output file or is ready to create any on demand.

	CACHE_READY_OK		=  10	# The Source has initialized (possibly loaded, possibly created) a cache for SourceNode objects.

	READY				=  100	# The source is ready to be processed.

	FILE_NEEDS_UPDATE	=  404	# The file needs to be updated because the source file is more recent than the output file.


class SourceNode(ABC):
	""" Everything in the Source is a tree of SourceNodes: A SourceMaker, SourceFile or SourceEntity.

	## Overview

	This class has the common interface to manage indices in the tree. It provides:

	- Attributes: type, index, description and state
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
		self._descr	 = None

		self.state = SourceState.INITIAL


	@property
	def type(self):
		""" Returns the type of this SourceNode. A type is more specific than the class name. E.g. A SourceMaker can have 'pdf_mirror',
			'xml_stream', 'markdown_tree'. A SourceEntity can be anything in SourceEntityType.
		"""

		return self._type


	@property
	def index(self):
		""" Returns the index of this SourceNode in the tree. Indices are separated by | and can include relative paths and
			sections, sub-sections, sub-sub-sections as different SourceNodes. E.g., `"maker|a/b/file.md|sec3|sec3.1|sec3.1.2|para5"`

			This allows, on top of any other caching mechanisms (the Source has both a cache and a vector database with a key/value store),
			any SourceNode can be retrieved from its index by just parsing it left to right, starting from the SourceMaker, then the
			SourceFile, ... This is implemented in the Source. The SourceNode can retrieve any valid SourceNode by its index via its
			Agentic interface.
		"""

		return self._index


	@property
	def description(self):
		""" Returns the description of the SourceNode. It is a string that describes each SourceNode. If there is a title or
			section title, it will the title with some numbering. The final SourceEntityType with no children does not have a description,
			The description is mechanism to provide titles, sub-titles, table names, figure names, etc. to make them searchable
			independently of the text.
		"""

		return self._descr


	@abstractmethod
	def get_children_idx(self, index = None):
		""" Returns the children of a SourceNode.

		All SourceNodes are in a large tree of SourceNodes. Each node owns at least the node in the tree whose index is its own.
		Since some nodes can have a large number of children, they can divide the index tree into clusters, returning themselves
		as the SourceNode pointed to by the "cluster part" of the index (see example below).

		## Example:

		A SourceMaker with id 'corpus' can hold millions of files and divide them into clusters, of say 100 files per cluster.
		So the final index to a file can be 'corpus|2:41|1:84|file_39.md'

		Calling this method with index == 'corpus' will return [.., 'corpus|2:41', ..], calling it with index == 'corpus|2:41'
		will return [.., 'corpus|2:41|1:84', ..]. The next depth will return list of files in that cluster.

		In the same example, calling `child('corpus|2:41')` will return the same SourceMaker object issuing the call. Calling
		`child('corpus|2:41|1:84')` will again return the same SourceMaker object, but calling `child('corpus|2:41|1:84|file_39.md')`
		will return the SourceFile object for that file.

		## About the index argument:

		Not all SourceNodes should support this complexity. It makes sense for a SourceMaker since it can hold millions of files.
		It is used in a SourceEntity for efficiency, to avoid making copies of parts of itself that make copies of parts of themselves.
		The rest just ignore the index argument and return all their children in just one list.

		Args:
			index (str): An optional index to clarify which part of the SourceNode tree should be returned. (See the example above.)

		Returns:
			(list): A list of children indices.
		"""

		pass


	@abstractmethod
	def child(self, index):
		""" Returns the child of the SourceNode with the given index.

		Args:
			index (str): the index of the child to return.

		Returns:
			(SourceNode): The child SourceNode with the given index.
		"""

		pass
