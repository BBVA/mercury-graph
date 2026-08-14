import importlib, os, re, pickle

from abc import ABC, abstractmethod
from collections import OrderedDict
from enum import Enum
from pathlib import Path

import chromadb as chroma
from lxml import etree

from .agentic import Agentic
from .formats import WikiMarkdownWriter, PdfToMarkdown, MDbyPDFoxide


class SourceEntityType(Enum):
	""" The `SourceEntityType` enumeration defines the types of entities that can be represented in a SourceFile. """

	TEXT			=  1	# A text fragment within another entity.
	PARAGRAPH		=  2	# A paragraph of text.
	LINK			=  3	# A link.
	IMAGE			=  4	# An image.

	HEADER_1		=  10	# A level 1 Markdown header and its contents.
	HEADER_2		=  11	# A level 2 Markdown header and its contents.
	HEADER_3		=  12	# A level 3 Markdown header and its contents.
	HEADER_4		=  13	# A level 4 Markdown header and its contents.
	HEADER_5		=  14	# A level 5 Markdown header and its contents.
	HEADER_6		=  15	# A level 6 Markdown header and its contents.

	LIST			=  20	# An ordered or unordered list.
	LIST_ITEM		=  21	# An item in a list.

	TABLE			=  30	# A table.
	TABLE_HEADER	=  31	# The header row of a table.
	TABLE_ROW		=  32	# A row of a table.
	TABLE_CELL		=  33	# A cell in a table.

	CODE_BLOCK		=  40	# A fenced or indented block of code.
	BLOCKQUOTE		=  41	# A Markdown blockquote.
	HORIZONTAL_RULE	=  42	# A Markdown thematic break.

	FOOTNOTE		=  50	# A footnote definition.


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
		pdf_to_md (dict): If given, it is a dictionary with the configuration to load a custom PdfToMarkdown descendant.
	"""

	def __init__(self, index, typ, src_path, dst_path, cluster_size, extensions, pdf_to_md):
		super().__init__(index)

		if typ not in ['pdf_mirror', 'xml_stream', 'markdown_tree']:
			raise ValueError('Invalid type: %s' % typ)

		if typ == 'pdf_mirror':
			if pdf_to_md is None:
				self._pdf_to_md = MDbyPDFoxide
				self._pdf_extra = None
			else:
				class_name	= pdf_to_md['class_name']
				module_path	= pdf_to_md['path']
				extra_args	= pdf_to_md.get('extra_args', None)

				module_name = os.path.splitext(os.path.basename(module_path))[0]

				spec = importlib.util.spec_from_file_location(module_name, module_path)

				if spec is None or spec.loader is None:
					raise ValueError('Could not load module from path: %s' % module_path)

				module = importlib.util.module_from_spec(spec)
				spec.loader.exec_module(module)
				custom_conv = getattr(module, class_name, None)

				if custom_conv is None or not issubclass(custom_conv, PdfToMarkdown):
					raise ValueError('Invalid class: %s in module: %s' % (class_name, module_path))

				self._pdf_to_md = custom_conv
				self._pdf_extra = extra_args

		self._type = typ

		if src_path is not None:
			self._src = src_path.rstrip('/')

		self._dst	  = dst_path.rstrip('/')
		self._cl_size = cluster_size

		self._descr	= 'SourceMaker: %s, type: %s, output: %s' % (self._index, self._type, self._dst)

		# Note the ':' is %-encoded in file names by _safe_filename(), therefore it is used in cluster indices to make collisions with
		self.rex_kwap = re.compile('(^ |[<>:"/\\\\|?*\\x00-\\x1f])')	# actual file names impossible.

		self._ext = extensions
		if self._ext is None:
			return

		if type(extensions) is str:
			extensions = [extensions]

		if len(extensions) == 0:
			self._ext = None

			return

		self._ext = set()

		for e in extensions:
			e = e.lstrip('.').lower()
			self._ext.add(e)


	def build_indices(self):
		""" Builds the indices of the SourceMaker. It builds a dictionary with all the indices of the SourceFile objects, but without
		creating the object. (That is done on demand by child().)

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

			if type(self._children) is not dict:
				return False

		elif self._type == 'pdf_mirror':
			if not os.path.isdir(self._src):
				return False

			if not os.path.isdir(self._dst):
				os.makedirs(self._dst, exist_ok = True)

			self._children = self._recurse_tree(self._src)

			if type(self._children) is not dict:
				return False

		else:	# self._type == 'xml_stream'
			if not os.path.isfile(self._src):
				return False

			src_time = int(os.path.getmtime(self._src))

			if os.path.isdir(self._dst):
				self._children = self._recurse_tree(abort_if_before = src_time)

			if type(self._children) is not dict:	# The destination files are not up to date and need to be created again.
				if not self._create_markdown_from_xml():
					return False

				self._children = self._recurse_tree()

				if type(self._children) is not dict:
					return False

		depth = 0
		while len(self._children) > self._cl_size:
			depth += 1

			old_keys = list(self._children.keys())

			clust_num = None
			clust_items = 0
			for o_key in old_keys:
				if clust_num is None or clust_items >= self._cl_size:
					clust_num = 1 if clust_num is None else clust_num + 1
					clust_key = '%d:%d' % (depth, clust_num)

					self._children[clust_key] = {}
					clust_items = 0

				# Move the old key to the new cluster.
				self._children[clust_key][o_key] = self._children[o_key]
				del self._children[o_key]

				clust_items += 1

		self.state = SourceState.MAKER_READY_OK.value

		return True


	def get_children_idx(self, index = None):
		""" Returns the children indices following the SourceNode interface.

		(See [`SourceNode.get_children_idx()`][mercury.graph.evidence.source.SourceNode.get_children_idx].)
		"""

		if index is None:	# The index is mandatory for the SourceMaker.
			return None

		idx_stack = index.split('|')

		if idx_stack.pop(0) != self._index:
			return None

		keys = self._children
		for ky in idx_stack:
			if ky not in keys:
				return None

			keys = keys[ky]

		return list(keys.keys())


	def child(self, index):
		""" Returns the corresponding SourceFile object following the SourceNode interface.

		(See [`SourceNode.child()`][mercury.graph.evidence.source.SourceNode.child].)
		"""

		idx_stack = index.split('|')

		if idx_stack.pop(0) != self._index:
			return None

		ret = self._children
		for ky in idx_stack:
			if ky not in ret:
				return None

			dic = ret
			ret = ret[ky]

		if type(ret) is dict:
			return self				# Index returns the SourceMaker itself, calling get_children_idx() will explore further down the tree.

		if type(ret) is SourceFile:
			return ret

		ret = self._build_child_at(index)

		if type(ret) is not SourceFile:
			self.state = SourceState.ERR_MAKER_ACCESS.value

		dic[ky] = ret

		return ret


	def _safe_filename(self, path, name):
		""" This %-encodes the characters that are not allowed in file names (defined by self.rex_kwap). It also %-encodes leading spaces
		and removes trailing spaces. It has been tested to avoid collisions in wikipedia dumps using titles and page file names.

		Args:
			path (str): The absolute path some storage tree. (Typically self.src or self.dst, but any name without a trailing / is valid.)
			name (str): The relative name of the file within path. Only the last part of the path is encoded, path is assumed to be valid.

		Returns:
			(str): Absolute path to the file with a safe name.
		"""

		return '%s/%s.md' % (path, self.rex_kwap.sub(lambda m: '%%%02X' % ord(m.group()), name).rstrip(' '))


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

				children[file_idx] = SourceState.FILE_NEEDS_UPDATE.value

			return True

		if recurse(root, None) is None:
			return None

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

		PAGE_TAG = '%shttp://www.mediawiki.org/xml/export-0.11/}page' % '{'
		NS		 = {'mw': 'http://www.mediawiki.org/xml/export-0.11/'}

		for event, elem in etree.iterparse(self._src, events = ('end',), tag = PAGE_TAG):
			title = elem.findtext('mw:title', namespaces = NS)

			idx = self._write_xml_page_as_md(title, elem)

			elem.clear()	# Clear the element to free memory.

			while elem.getprevious() is not None:	# Also clear the previous siblings of the element to free memory.
				del elem.getparent()[0]

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

		fn = self._safe_filename(self._dst, title)

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

		fn_dst = '%s/%s' % (self._dst, index.split('|')[-1])

		if self._type == 'pdf_mirror':	# The file must exist in self._dst
			if os.path.isfile(fn_dst):
				return SourceFile(index, self, fn_dst)

			return SourceState.FILE_NEEDS_UPDATE.value

		fn_src = '%s/%s' % (self._src, index.split('|')[-1])
		if not os.path.isfile(fn_src):
			return SourceState.FILE_NEEDS_UPDATE.value

		if os.path.isfile(fn_dst):
			tim_src = int(os.path.getmtime(fn_src))
			tim_dst = int(os.path.getmtime(fn_dst))

			if tim_dst >= tim_src:
				return SourceFile(index, self, fn_dst)

		cnv = self._pdf_to_md(fn_src, fn_dst, self._pdf_extra)

		if cnv.ready():
			cnv.run()

			if os.path.isfile(fn_dst):
				return SourceFile(index, self, fn_dst)

		return SourceState.FILE_NEEDS_UPDATE.value


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

		self._content = None

		self.path = path


	def get_children_idx(self, index = None):
		""" Returns the children indices following the SourceNode interface.

		(See [`SourceNode.get_children_idx()`][mercury.graph.evidence.source.SourceNode.get_children_idx].)
		"""

		if self.state != SourceState.READY.value:
			self._load_and_parse()

			if self.state != SourceState.READY.value:
				return None

		return list(self._children.keys())


	def child(self, index):
		""" Returns the corresponding SourceEntity object following the SourceNode interface.

		(See [`SourceNode.child()`][mercury.graph.evidence.source.SourceNode.child].)
		"""

		if self.state != SourceState.READY.value:
			self._load_and_parse()

			if self.state != SourceState.READY.value:
				return None

		return self._children.get(index, None)


	def lines(self, span):
		""" This is how every SourceEntity gets access to the text.

		The SourceNode objects in a SourceFile keep only ranges, never text and call this lines() or line_slice() to get the text.

		Args:
			span (slice): A slice object that defines the range of lines to return.

		Returns:
			(list of str): The lines of text in the given range, or None if the range is invalid.
		"""

		try:
			ret = self._content[span]

		except IndexError:
			return None

		return ret


	def line_slice(self, line, span):
		""" This is how every SourceEntity gets access to the text.

		The SourceNode objects in a SourceFile keep only ranges, never text and call this lines() or line_slice() to get the text.

		Args:
			line (int): The line number to return.
			span (slice): A slice object that defines the range of characters to return from the line.

		Returns:
			(str): The characters in the given range from the specified line, or None if the range is invalid.
		"""

		try:
			ret = self._content[line][span]

		except IndexError:
			return None

		return ret


	def _load_and_parse(self):
		""" This method has all the internal logic of the class. It starts by loading the file into memory (self._content, which is a
		list of str). The coordinates in terms of lines and character ranges cannot be modified. Markdown parsing is very line-oriented,
		so even if pathological paragraphs are found, they will live in one line and be broken by characters. Every division is either
		multiline with no character range or single-line with a character range. This is enforced by this method.

		This method uses numpy (as np) to build integer indices to define header levels, table rows, etc. The Markdown interpretation
		is done by the class MarkdownParser to keep this class simple.

		## Hierarchy Example

		```text
		HEADER_1 Title_1
		    └── HEADER_2 Subtitle_1_1
		        └── PARAGRAPH
		            └── Chunk_1, Chunk_2, Chunk_3
		```

		Markdown has an inherent hierarchy, like in the example above. In that case, Header 1 becomes an entity with two children:
		Header 2 and the Title. The Title has content (the title itself) and no children. Header 2 has two children: the Subtitle and
		the Paragraph. This becomes:

		| entity       | content             | description                | children                  |
		| ------------ | ------------------- | -------------------------- | ------------------------- |
		| HEADER_1     |                     | "Title: The life of birds" | Title_1, HEADER_2         |
		| Title_1      | "The life of birds" |                            |                           |
		| HEADER_2     |                     | "Section 1: Overview"      | Subtitle_1_1, PARAGRAPH   |
		| Subtitle_1_1 | "Overview"          |                            |                           |
		| PARAGRAPH    |                     | "Content of 1.1"           | Chunk_1, Chunk_2, Chunk_3 |
		| Chunk_1      | "Bla, bla, bla"     |                            |                           |
		| Chunk_2      | "Pio, pio, pio"     |                            |                           |
		| Chunk_3      | "Trust me."         |                            |                           |

		Note that, range-wise, HEADER_1 covers all the lines in the file from itself to the line before the next HEADER_1 (possibly the
		whole file), but Title_1 is only the slice of the line that contains the title. The same applies to HEADER_2, etc.

		Note that all the text content in the file becomes the content of some SourceEntity, so when the Source/EvidenceGraph/etc. use it,
		everything is there. The descriptions are as informative as possible, using the titles of the sections to make a smaller database
		of descriptions possible. The numbering is created automatically by the parser.
		"""

		self._children = {}

		with open(self.path, 'r', encoding = 'utf-8') as f:
			self._content = f.read().splitlines()


		# TODO implement this!

		self.state = SourceState.READY.value


class SourceEntity(SourceNode):
	""" The SourceEntity is a SourceNode that represents a single section, subsection, paragraph, chunk, table, cell, figure, etc. in a
	file. It does not contain the text itself, just its span in the SourceFile. SourceEntity objects are created by the SourceFile and
	live inside it

	The class SourceEntityType is an Enum that defines all possible types of SourceEntity objects.

	Args:
		index (str): the index of this SourceEntity in the tree.
		parent (SourceFile): The parent SourceFile that contains created this SourceEntity and has the content.
		ent_type (SourceEntityType): The type of this SourceEntity.
		line (slice or int): The line range to pass to it's parent's lines() if multiline or the only line (combined with span) for single
			line entities..
		span (slice): The range of characters in the only line (line must be an int when this is used) that this SourceEntity covers.
		description (str): An optional description of this SourceEntity. It is used for titles, sub-titles, given to it by the SourceFile.
	"""

	def __init__(self, index, parent, ent_type, line, span = None, description = None):
		super().__init__(index, parent)

		self._type	= ent_type
		self._line	= line
		self._span	= span
		self._descr = description if description is not None else ''

		self._children = None

		self.state = SourceState.READY.value


	@property
	def content(self):
		""" Returns the content of this SourceEntity. Only SourceEntity without children have content. """

		if self._children is not None:
			return ''

		if self._span is None:
			return self.parent.lines(self._line)

		return self.parent.line_slice(self._line, self._span)


	@property
	def description(self):
		""" Returns the description of this SourceEntity. It is used for titles, sub-titles, given to it by the SourceFile. """

		return self._descr


	@property
	def entity_type(self):
		""" Returns the type of this SourceEntity. It is one of the values in the SourceEntityType enumeration. """

		return SourceEntityType(self._type)


	def get_children_idx(self, index = None):
		""" Returns the children indices of this SourceEntity. Only SourceEntity with children have children indices.

		(See [`SourceNode.get_children_idx()`][mercury.graph.evidence.source.SourceNode.get_children_idx].)
		"""

		if self._children is not None:
			return list(self._children.keys())


	def child(self, index):
		""" Returns the child of this SourceEntity with the given index.

		The child can only be a deeper SourceEntity or None.

		(See [`SourceNode.child()`][mercury.graph.evidence.source.SourceNode.child].)
		"""

		if self._children is None:
			return None

		return self._children.get(index, None)


	def add_child(self, child):
		""" Adds a child SourceEntity to this SourceEntity.

		This is called by the SourceFile when parsing the markdown file and creating the SourceEntity tree.

		Args:
			child (SourceEntity): The child SourceEntity to add.
		"""

		if self._children is None:
			self._children = {}

		self._children[child.index] = child


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

	- [`SourceNode`][mercury.graph.evidence.SourceNode]: The base class to manage the index logic of all components.
	- [`SourceMaker`][mercury.graph.evidence.SourceMaker]: The root SourceNode responsible for managing a tree of markdown files.
	- [`SourceFile`][mercury.graph.evidence.SourceFile]: Each individual file as a SourceNode.
	- [`SourceEntity`][mercury.graph.evidence.SourceEntity]: Each section, subsection, paragraph, table, figure, text, table cell or link
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
