import importlib, os, re

from lxml import etree

from .source_node import SourceNode, SourceState
from .source_file import SourceFile

from mercury.graph.evidence.formats import MDbyPDFoxide, PdfToMarkdown, WikiMarkdownWriter


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

		(See [`SourceNode.get_children_idx()`][mercury.graph.evidence.source_parts.SourceNode.get_children_idx].)
		"""

		if index is None:	# The index is mandatory for the SourceMaker.
			return None

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
