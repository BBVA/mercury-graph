import importlib, os, threading

from collections import OrderedDict

from .source_node import SourceNode, SourceState
from .source_file import SourceFile
from .xml_build import build_xml_markdown, open_xml_catalogue

from mercury.graph.evidence.formats import MDbyPDFoxide, PdfToMarkdown


XML_FILE_CACHE = 64	# The number of SourceFile objects of an "xml_stream" SourceMaker that are kept in memory.


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

		self._xml = None
		self._files = OrderedDict()
		self._files_lock = threading.Lock()

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
		  * **xml_stream**: Opens the output index of the XML export. When there is no complete and current build, the export is
		  	converted first, and this waits until the conversion has finished. The Markdown files are only converted again when the
		  	source XML file is updated. (See mercury.graph.evidence.source_parts.xml_build.)

		Returns:
			(bool): True if the indices were successfully built, False otherwise.
		"""

		if self._type == 'xml_stream':
			return self._build_xml_indices()

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

		(See [`SourceNode.get_children_idx()`][mercury.graph.evidence.source_parts.SourceNode.get_children_idx].)
		"""

		if index is None:	# The index is mandatory for the SourceMaker.
			return None

		if self._type == 'xml_stream':
			return self._xml_children_idx(index)

		idx_stack = index.split('|')

		if idx_stack.pop(0) != self._index:
			return None

		ret = self._children
		while len(idx_stack) > 0:
			ky = idx_stack.pop(0)
			if ky not in ret:
				return None

			ret = ret[ky]

			if type(ret) is not dict:
				if len(idx_stack) > 0:		# The index is longer than the tree depth, we return the part that exists in this SourceNode.
					return '|'.join(index.split('|')[0:-len(idx_stack)])
				else:
					return index

		return ['%s|%s' % (index, k) for k in ret.keys()]


	def child(self, index):
		""" Returns the corresponding SourceFile object following the SourceNode interface.

		(See [`SourceNode.child()`][mercury.graph.evidence.source_parts.SourceNode.child].)
		"""

		if self._type == 'xml_stream':
			return self._xml_child(index)

		idx_stack = index.split('|')

		if idx_stack.pop(0) != self._index:
			return None

		ret = self._children
		while len(idx_stack) > 0:
			ky = idx_stack.pop(0)

			if ky not in ret:
				return None

			dic = ret
			ret = ret[ky]

			if type(ret) is not dict:
				break

		if type(ret) is dict:
			return self				# Index returns the SourceMaker itself, calling get_children_idx() will explore further down the tree.

		if len(idx_stack) > 0:		# The index is longer than the tree depth, we return the part that exists in this SourceNode.
			return '|'.join(index.split('|')[0:-len(idx_stack)])

		if type(ret) is SourceFile:
			return ret

		ret = self._build_child_at(index)

		if type(ret) is not SourceFile:
			self.state = SourceState.ERR_MAKER_ACCESS.value

		dic[ky] = ret

		return ret


	def _recurse_tree(self, root = None):
		""" Recursively builds a dictionary of indices for the SourceMaker. It is used by build_indices() to build the indices of the
		SourceFile objects.

		Args:
			root (str): the path to the source files. If None, it uses self._dst.

		Returns:
			(dict): A dictionary with the indices of the SourceFile objects. The keys are the indices and the values None.
		"""

		if root is None:
			root = self._dst

		if not os.path.isdir(root):
			return None

		children = {}

		def recurse(root, folder_file_idx):
			""" Adds file indices from a directory and its subdirectories to the children dictionary. """

			for name in os.listdir(root):
				fn		 = '%s/%s' % (root, name)
				file_idx = '%s/%s' % (folder_file_idx, name) if folder_file_idx is not None else name

				if os.path.isdir(fn):
					recurse(fn, file_idx)

					continue

				if not os.path.isfile(fn):
					continue

				if self._ext is not None:
					ext = str(name).lower().split('.')[-1]
					if ext not in self._ext:
						continue

				children[file_idx] = SourceState.FILE_NEEDS_UPDATE.value

		recurse(root, None)

		return children


	def _build_xml_indices(self):
		""" Opens the output index of an "xml_stream" SourceMaker. When there is no complete and current build of the XML source, the
		conversion runs first, and this waits until it has finished.

		Returns:
			(bool): True if the output index is ready, False otherwise.
		"""

		if not os.path.isfile(self._src):
			return False

		self._xml = open_xml_catalogue(self._src, self._dst, self._cl_size)

		if self._xml is None:
			if not build_xml_markdown(self._src, self._dst, self._cl_size):
				return False

			self._xml = open_xml_catalogue(self._src, self._dst, self._cl_size)

			if self._xml is None:
				return False

		self.state = SourceState.MAKER_READY_OK.value

		return True


	def _xml_parts(self, index):
		""" Returns the parts of an index below this SourceMaker. Only used by "xml_stream" SourceMakers.

		Args:
			index (str): An index of this SourceMaker.

		Returns:
			(list of str): The parts after the SourceMaker index. None when the index does not belong to this SourceMaker, or when the
				output index is not built.
		"""

		parts = index.split('|')

		if parts.pop(0) != self._index or self._xml is None:
			return None

		return parts


	def _xml_children_idx(self, index):
		""" Returns the children indices of an index of an "xml_stream" SourceMaker. Only the cluster that the index names is queried.

		(See [`SourceNode.get_children_idx()`][mercury.graph.evidence.source_parts.SourceNode.get_children_idx].)
		"""

		parts = self._xml_parts(index)
		located = None if parts is None else self._xml.locate(parts)

		if located is None:
			return None

		numbers, name, consumed = located
		if name is None:
			return ['%s|%s' % (index, key) for key in self._xml.children(numbers)]

		return self._xml_file_index(parts, consumed)


	def _xml_child(self, index):
		""" Returns the child of an index of an "xml_stream" SourceMaker. A SourceFile is only created when it is requested.

		(See [`SourceNode.child()`][mercury.graph.evidence.source_parts.SourceNode.child].)
		"""

		parts = self._xml_parts(index)
		located = None if parts is None else self._xml.locate(parts)

		if located is None:
			return None

		numbers, name, consumed = located
		if name is None:
			return self

		file_index = self._xml_file_index(parts, consumed)
		if consumed < len(parts):	# The index is longer than the tree depth, we return the part that exists in this SourceNode.
			return file_index

		return self._xml_file(file_index, '%s/%s' % (self._dst, name))


	def _xml_file_index(self, parts, consumed):
		""" Returns the index of a file of an "xml_stream" SourceMaker.

		Args:
			parts (list of str): The parts of an index after the SourceMaker index.
			consumed (int): The number of parts that belong to the file: its cluster keys and its name.

		Returns:
			(str): The index of the file.
		"""

		return '|'.join([self._index] + parts[0:consumed])


	def _xml_file(self, index, path):
		""" Returns the SourceFile of an output file of an "xml_stream" SourceMaker. The most recently used SourceFile objects are kept
		in memory, so their number does not grow with the corpus.

		Args:
			index (str): The index of the file.
			path (str): The path of the markdown file.

		Returns:
			(SourceFile): The SourceFile, or FILE_NEEDS_UPDATE when the file does not exist.
		"""

		if not os.path.isfile(path):
			self.state = SourceState.ERR_MAKER_ACCESS.value
			return SourceState.FILE_NEEDS_UPDATE.value

		with self._files_lock:
			if index in self._files:
				self._files.move_to_end(index)
				return self._files[index]

			file = SourceFile(index, self, path)
			self._files[index] = file

			if len(self._files) > XML_FILE_CACHE:
				self._files.popitem(last = False)

			return file


	def _build_child_at(self, index):
		""" Builds a SourceFile object for the given index. It is used by child() to create the SourceFile objects on demand.

		Args:
			index (str): the index of the SourceFile to create.

		Returns:
			(SourceFile): The SourceFile object for the given index.
		"""

		fn_dst = '%s/%s' % (self._dst, index.split('|')[-1])

		if self._type != 'pdf_mirror':	# The file must exist in self._dst
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

		if cnv.ready:
			cnv.run()

			if os.path.isfile(fn_dst):
				return SourceFile(index, self, fn_dst)

		return SourceState.FILE_NEEDS_UPDATE.value
