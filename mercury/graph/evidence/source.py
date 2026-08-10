import os, re, pickle

from abc import ABC, abstractmethod
from collections import OrderedDict
from enum import Enum
from pathlib import Path

import chromadb as chroma
from lxml import etree

from .agentic import Agentic
from .formats import WikiMarkdownWriter, PdfToMarkdown


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
	""" Everything in the Source is a tree of SourceNodes: A Maker, a File, an Entity, even a Chunk (a node with no children).

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
			'xml_stream', 'markdown_tree'. A SourceEntity can be a paragraph, a table, a figure, etc. A Chunk can be a text, a link or
			a table cell.
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
			section title, it will the title with some numbering. The text in the descriptions can be searched independently of
			the text in the chunks.
		"""

		return self._descr


	@abstractmethod
	def get_children_idx(self, index = None):
		""" Returns the children of a SourceNode.

		All SourceNodes are in a large tree of SourceNodes. Each node owns at least the node in the tree whose index is its own.
		Since some nodes can have a large number of children, they can divide the index tree into clusters, returning themselves
		as the SourceNode pointed to by the "chunk part" of the index.

		## Example:

		A SourceMaker with id 'corpus' can hold millions of files and chunk them into clusters, of say 100 files per cluster.
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


class SourceMaker(SourceNode):
	""" The SourceMaker is the root SourceNode that is responsible for creating a tree of SourceFile objects.

	A Source only has one SourceMaker. An Endpoint can have as many Sources as required.

	It may do nothing, when the Source is already a tree markdown files on disk, or it can mirror a tree of PDF files as their
	corresponding markdown files, or it may dump large XML files into a tree of markdown files.

	Since it may potentially manage a large number of files, it will not provide the full list via `get_children_idx()`, but it will
	cluster them. A cluster defines a section in the index tree that is managed by the same SourceMaker. So, instead of having an index
	'maker|file25000000.md', pointing to some SourceFile, it will have an index 'maker|@023|@19|file17.md', where '@023' and '@19'
	are handled by the SourceMaker. Meaning: maker.child('maker|@023') will return the same SourceMaker, maker.child('maker|@023|@19') too,
	but maker.child('maker|@023|@19|file17.md') will return a SourceFile.

	Args:
		index (str): the index of this SourceMaker in the tree.
		typ (str): the type of this SourceMaker. It can be one of: "pdf_mirror", "xml_stream" or "markdown_tree".
		src_path (str): the path to the source files. (None for "markdown_tree" type.)
		dst_path (str): the path to the destination markdown files.
		cluster_size (int): the maximum number of files per cluster. It is used to create clusters as explained above.
		extensions (list of str): If given, only files with these extensions will be indexed. (A filtering mechanism for "markdown_tree".)
	"""

	def __init__(self, index, typ, src_path, dst_path, cluster_size, extensions = None):
		super().__init__(index)

		if typ not in ['pdf_mirror', 'xml_stream', 'markdown_tree']:
			raise ValueError('Invalid type: %s' % typ)

		self._type	  = typ
		self._src	  = src_path.rstrip('/')
		self._dst	  = dst_path.rstrip('/')
		self._cl_size = cluster_size

		ext = extensions
		if type(ext) is not list:
			ext = [ext]

		if len(ext) == 0:
			self._ext = None
		else:
			self._ext = set()

			for e in ext:
				e = e.replace('.', '').lower()
				self._ext.add(e)

		self._descr	= 'SourceMaker: %s, type: %s, output: %s' % (self._index, self._type, self._dst)

		self.rex_kwap = re.compile('(^ |[<>:"/\\\\|?*\\x00-\\x1f])')


	def build_indices(self):
		""" Builds the indices of the SourceMaker. It builds a dictionary with all the indices of the SourceFile objects, but without
		creating the object (that is done by build_output())

		There is different behavior depending on the type of the SourceMaker:

		  * **markdown_tree**: Does nothing, just exposes the files with appropriate extensions in the destination.
		  * **pdf_mirror**: Mirrors the source tree of PDF files into the destination tree of markdown files, creating the directories.
		  	It returns the indices of (non existing) markdown files via get_children_idx(). When the files is requested via child(), it
			is created on demand by calling the PDF to markdown conversion tool.
		  * **xml_stream**: Creates the destination tree of markdown files from the source XML file. Since it doesn't have an efficient
		  	way to access the XML file randomly, it creates all the markdown files in the destination. Those files will not be created
			again unless the source XML file is updated.

		Returns:
			(bool): True if the indices were successfully built, False otherwise.
		"""

		if self._type == 'markdown_tree':
			if not os.path.isdir(self._dst):
				return False

			self._children = self._recurse_tree()

			return type(self._children) is dict

		if self._type == 'pdf_mirror':
			if not os.path.isdir(self._src):
				return False

			if not os.path.isdir(self._dst):
				os.makedirs(self._dst, exist_ok = True)

			self._children = self._recurse_tree(self._src)

			return type(self._children) is dict

		if not os.path.isfile(self._src):
			return False

		src_time = int(os.path.getmtime(self._src))

		if os.path.isdir(self._dst):
			self._children = self._recurse_tree(abort_if_before = src_time)

			if type(self._children) is dict:
				return True

		if not self._create_markdown_from_xml():
			return False

		self._children = self._recurse_tree()

		return type(self._children) is dict


	def build_output(self):
		""" Creates the SourceFile objects for each index in the self._children dictionary. This is efficient since the constructor of
		SourceFile does not read the file. The file is read when its content is requested via the SourceFile's get_children_idx() method.

		There is different behavior depending on the type of the SourceMaker:

		* **markdown_tree**: Create a SourceFile object for each file in the index (the index was built by parsing the destination).
		* **pdf_mirror**: Check if the markdown file exists and it more recent than the source PDF file. In that case, create a SourceFile
			object for it, if not it just sets the value to 404 (SourceState.FILE_NEEDS_UPDATE.value) and if the file is requested via
			child() it will be created on demand by calling the PDF to markdown conversion tool.
		* **xml_stream**: Create a SourceFile object for each file in the index. In that case, either the files already existed and were
			more recent than the source XML file, or they were created by the build_indices() method.

		Returns:
			(bool): True if the output files were successfully built, False otherwise.
		"""

		if self._type != 'pdf_mirror':
			# Just create the SourceFile objects for each dst file.
			return True
			# TODO: Implement the logic to build output files for the SourceMaker.

		# Mirror the PDF files (the relative paths are identical, the extension are .md instead of whatever the source file extension is).
		# If the file exists and is more recent than the source file, just create the SourceFile object for it. If not, erase the
		# destination file and set the value to 404.

		return True


	def get_children_idx(self):
		""" Returns the children indices following the SourceNode interface.

		(See [`SourceNode.get_children_idx()`][mercury.graph.evidence.source.SourceNode.get_children_idx].)

		"""

		return list(self._children.keys())


	def child(self, index):
		""" Returns the corresponding SourceFile object following the SourceNode interface.

		(See [`SourceNode.child()`][mercury.graph.evidence.source.SourceNode.child].)
		"""

		if not index in self._children:
			return None

		ret = self._children[index]
		if type(ret) is SourceFile:
			return ret

		self._children[index] = self._build_child_at(index)

		return self._children[index]


	def _recurse_tree(self, root = None, abort_if_before = None):
		""" Recursively builds a dictionary of indices for the SourceMaker. It is used by build_indices() to build the indices of the
		SourceFile objects.

		Args:
			root (str): the path to the source files. If None, it uses self._dst.
			abort_if_before (int): If given, it will abort the recursion returning None if it finds a file with a modification time
				older than this value. This is used to check if the source XML file is more recent than the output files.

		Returns:
			(dict): A dictionary with the indices of the SourceFile objects. The keys are the indices and the values None.
		"""

		if root is None:
			root = self._dst

		if not os.path.isdir(root):
			return None

		children = {}

		def recurse(root, folder_file_idx):
			for name in os.listdir(root):
				fn		 = '%s/%s' % (root, name)
				file_idx = '%s/%s' % (folder_file_idx, name) if folder_file_idx is not None else name

				if os.path.isdir(fn):
					if recurse(fn, file_idx) is None:
						return None

					continue

				if not os.path.isfile(fn):
					continue

				if self._ext is not None:
					ext = str(name).lower().split('.')[-1]
					if ext not in self._ext:
						continue

				if abort_if_before is not None:
					tim = os.path.getmtime(fn)
					if tim < abort_if_before:
						return None

				children[self._index + '|' + file_idx] = 404

		recurse(root, None)

		return children


	def _create_markdown_from_xml(self):
		""" Creates the markdown files from the source XML file. It is used by build_indices() to create the output files for the
		SourceMaker.

		Returns:
			(bool): True if the markdown files were successfully created, False otherwise.
		"""

		if not os.path.isdir(self._dst):
			os.makedirs(self._dst, exist_ok = True)

		# The file has 25,275,933 pages.

		top_n = 25276	# For testing, write only the first 25276 pages.	(Roughly 1/1000 of the total pages.)
		# TODO: Remove the top_n limit!

		PAGE_TAG = '%shttp://www.mediawiki.org/xml/export-0.11/}page' % '{'
		NS		 = {'mw': 'http://www.mediawiki.org/xml/export-0.11/'}

		for event, elem in etree.iterparse(self._src, events = ('end',), tag = PAGE_TAG):
			title = elem.findtext('mw:title', namespaces = NS)

			idx = self._write_xml_page_as_md(title, elem)

			elem.clear()	# Clear the element to free memory.

			while elem.getprevious() is not None:	# Also clear the previous siblings of the element to free memory.
				del elem.getparent()[0]

			top_n -= 1
			if top_n == 0:
				break

		return True


	def _write_xml_page_as_md(self, title, elem):
		""" Writes a Wikipedia XML page as a Markdown file.

		The XML export keeps the article contents as MediaWiki wikitext in the
		``revision/text`` element. This method extracts that text, renders the
		common document structures to Markdown, and adds the article title as the
		level-one heading.

		Args:
			title (str): Article title from the XML page element.
			elem (lxml.etree._Element): Completed MediaWiki ``page`` element.

		Returns:
			(str): Path of the written Markdown file.
		"""

		fn = '%s/%s.md' % (self._dst, self.rex_kwap.sub(lambda m: '%%%02X' % ord(m.group()), title).rstrip(' '))

		page_text = ''
		for child in elem.iter():
			if type(child.tag) is str and etree.QName(child).localname == 'text':
				page_text = child.text or ''
				break

		body = WikiMarkdownWriter(page_text).render()

		with open(fn, 'w', encoding = 'utf-8') as f:
			f.write('# %s\n\n' % title)
			f.write(body)

		return fn


	def _build_child_at(self, index):
		""" Builds a SourceFile object for the given index. It is used by child() to create the SourceFile objects on demand.

		Args:
			index (str): the index of the SourceFile to create.

		Returns:
			(SourceFile): The SourceFile object for the given index.
		"""

		return None
		# TODO: Implement the logic to build a SourceFile object for the given index for the SourceMaker.


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
		self._descr	= 'SourceFile: %s' % self._index

		self.path = path


	def get_children_idx(self, index = None):
		""" Returns the children indices following the SourceNode interface.

		(See [`SourceNode.get_children_idx()`][mercury.graph.evidence.source.SourceNode.get_children_idx].)

		"""

		pass
		# TODO: Implement the logic to return the children indices of the SourceFile.


	def child(self, index):
		""" Returns the corresponding SourceEntity object following the SourceNode interface.

		(See [`SourceNode.child()`][mercury.graph.evidence.source.SourceNode.child].)
		"""

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

		self.get_children_idx()		# This identifies the type, index and description from the content. Runs just one time.


	def get_children_idx(self, index = None):
		""" This parses the content to identify the children of this SourceEntity.

		While parsing, it also sets the type, index and description of this SourceEntity. E.g., the description of a title is the title
		itself. It builds a dictionary with the children of the next level in the tree. The children are either deeper SourceEntity objects
		or chunks containing text, a link or a cell in a table.

		(See [`SourceNode.get_children_idx()`][mercury.graph.evidence.source.SourceNode.get_children_idx].)
		"""

		if self.children is not None:
			return list(self.children.keys())

		# TODO: Implement the logic to return the children indices of the SourceEntity.


	def child(self, index):
		""" Returns the child of this SourceEntity with the given index.

		The child can be either a deeper SourceEntity or a Chunk.

		(See [`SourceNode.child()`][mercury.graph.evidence.source.SourceNode.child].)
		"""

		if self.children is None:
			return None

		return self.children.get(index, None)


class Chunk(SourceNode):
	""" The Chunk is a SourceNode that represents a single chunk of text or a link in a markdown file. It is a node with no children.

	It is the text of a paragraph, delimited by end of paragraph, a link, or a cell in a table.

	Args:
		index (str): the index of this Chunk in the tree.
		parent (SourceEntity): The SourceEntity that contains this Chunk.
		content (str): The text of the chunk, table cell or link.
		is_link (bool): True if the chunk is a link, False if it is a text or table cell.
		label (str): The label of the table column if this is a table cell or the label of the link. None for text chunks.
		row_name (str): The name of the table row if this is a table cell. The row number if the row has no name.
	"""

	def __init__(self, index, parent, content, is_link = False, label = None, row_name = None):
		super().__init__(index, parent)

		self.content = content

		if is_link:
			self._type	= 'link'
			self._name	= label
			self._descr	= content

		else:
			self._name = index.split('/')[-1]

			if label is None:
				self._type	= 'text'
				self._descr	= 'Paragraph: %s' % self._name

			else:
				self._type	= 'table_cell'
				self._descr	= 'row: "%s" column: "%s"' % (label, row_name)


	def get_children_idx(self, index = None):
		""" Following the SourceNode interface, returns an empty list as Chunks have no children.

		(See [`SourceNode.get_children_idx()`][mercury.graph.evidence.source.SourceNode.get_children_idx].)
		"""

		return []


	def child(self, index):
		""" Following the SourceNode interface, returns None as Chunks have no children.

		(See [`SourceNode.child()`][mercury.graph.evidence.source.SourceNode.child].)
		"""

		return None


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

	## Source Components

	The Source uses the following components to manage file conversion, chunking, indexing and to represent the parts of a document:

	- [`SourceNode`][mercury.graph.evidence.SourceNode]: The base class to manage the index logic of all components.
	- [`SourceMaker`][mercury.graph.evidence.SourceMaker]: The root SourceNode responsible for managing a tree of markdown files.
	- [`SourceFile`][mercury.graph.evidence.SourceFile]: Each individual file as a SourceNode.
	- [`SourceEntity`][mercury.graph.evidence.SourceEntity]: Each section, subsection, paragraph, table, figure, etc. in a markdown
		file as a SourceNode.
	- [`Chunk`][mercury.graph.evidence.Chunk]: Each chunk of text, table cell or link in a markdown file as a SourceNode.

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

		return {'status': 'ok'}
		# TODO: Implement the logic to run the Source with the given request.


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
					self._maker = SourceMaker(self.name, typ, src, dst, siz, self.conf.get('extensions', None))

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
					'description': 'Get the text at a given chunk index.',
					'parameters': {
						'type': 'object',
						'properties': {
							'index': {
								'type': 'string',
								'description': 'Index of the text chunk.'
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
