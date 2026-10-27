import json, logging, os, sqlite3
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from itertools import islice
from xml.parsers import expat
from xml.sax.saxutils import quoteattr

from .xml_catalogue import XmlCatalogue
from .xml_conversion import MEDIAWIKI_NS, collision_key, convert_batch, page_file_name


logger = logging.getLogger(__name__)

DEFAULT_CLUSTER_SIZE = 256
DEFAULT_PAGES_PER_BATCH = 10000

MANIFEST_FILE = 'manifest.json'
CATALOGUE_FILE = 'catalogue.sqlite'

PAGE_NAME = '%s}page' % MEDIAWIKI_NS	# Expat reports a namespaced element as 'namespace}name'.
TITLE_NAME = '%s}title' % MEDIAWIKI_NS

CHUNK_SIZE = 16 * 1024 * 1024


class XmlBuildError(Exception):
	""" Raised when the XML export cannot be indexed or converted. The message says why. """


def default_workers():
	""" Returns the default number of worker processes, one per CPU.

	Returns:
		(int): The number of worker processes.
	"""

	return os.cpu_count() or 1


def build_directory(dst):
	""" Returns the directory with the index and the state of the build of a destination. It is a sibling of the destination, so the
	destination only holds Markdown files.

	Args:
		dst (str): The destination directory of the Markdown files.

	Returns:
		(str): The build directory.
	"""

	return '%s.xml_build' % dst.rstrip('/')


def open_xml_catalogue(src, dst, cluster_size = DEFAULT_CLUSTER_SIZE):
	""" Opens the output index of a build that is complete and current for the XML source. Nothing is converted.

	Args:
		src (str): Path to the uncompressed MediaWiki XML export.
		dst (str): The destination directory of the Markdown files.
		cluster_size (int): The maximum number of files per cluster. The clusters are regrouped when the build used another size.

	Returns:
		(XmlCatalogue): The output index, or None when there is no ready build of the current source.
	"""

	folder = build_directory(dst)
	path = '%s/%s' % (folder, CATALOGUE_FILE)
	manifest = _read_manifest('%s/%s' % (folder, MANIFEST_FILE))

	if cluster_size < 2 or not os.path.isfile(path) or not _is_current(manifest, src):
		return None

	catalogue = XmlCatalogue(path)
	if not catalogue.is_ready():
		catalogue.close()
		return None

	if catalogue.size != cluster_size:
		catalogue.recluster(cluster_size)

	return catalogue


def build_xml_markdown(src, dst, cluster_size = DEFAULT_CLUSTER_SIZE, pages_per_batch = DEFAULT_PAGES_PER_BATCH, workers = None):
	""" Converts a MediaWiki XML export into Markdown files, and records the output index that open_xml_catalogue() opens.

	The export is indexed in one streaming pass. Its pages are then converted in batches, by worker processes when there are several.
	Batches recorded as done are not converted again, so an interrupted build resumes where it stopped. The build is marked as ready
	only when every batch succeeded and the page count matches the index. Any failure is logged, and the build is not ready. A build
	that is already complete keeps its batches, so pages_per_batch only matters when the export is indexed.

	Worker processes use the default start method of the platform (spawn on macOS). A plain script that calls this function must
	therefore be guarded by if __name__ == '__main__'.

	Args:
		src (str): Path to the uncompressed MediaWiki XML export. It is opened read-only.
		dst (str): The destination directory of the Markdown files. It is created when missing.
		cluster_size (int): The maximum number of files per cluster. It must be at least 2.
		pages_per_batch (int): The number of pages per batch. It must be at least 1.
		workers (int): The number of worker processes. None uses one per CPU. One worker converts in the calling process.

	Returns:
		(bool): True if the build is ready, False otherwise.
	"""

	if cluster_size < 2 or pages_per_batch < 1:
		logger.error('XML conversion needs a cluster size of at least 2 and at least one page per batch.')
		return False

	if workers is None:
		workers = default_workers()

	dst = dst.rstrip('/')
	folder = build_directory(dst)

	try:
		os.makedirs(folder, exist_ok = True)
		os.makedirs(dst, exist_ok = True)

		catalogue = XmlCatalogue('%s/%s' % (folder, CATALOGUE_FILE))
		try:
			manifest = _read_manifest('%s/%s' % (folder, MANIFEST_FILE))

			if not catalogue.index_complete() or not _is_current(manifest, src):
				manifest = _index_source(src, folder, catalogue, cluster_size, pages_per_batch)

			if not catalogue.is_ready():
				_convert_batches(src, dst, manifest, catalogue, workers)
				_publish(src, manifest, catalogue)

		finally:
			catalogue.close()

	except Exception as error:
		logger.error('XML conversion of "%s" failed: %s' % (src, error))
		return False

	return True


def _index_source(src, folder, catalogue, cluster_size, pages_per_batch):
	""" Indexes the XML export in one pass. The byte ranges of the batches go to the manifest, and the output file names of the pages go
	to the catalogue. Two pages that would be written to the same file are an error, and they are found before any page is converted.

	Args:
		src (str): Path to the uncompressed MediaWiki XML export.
		folder (str): The build directory.
		catalogue (XmlCatalogue): The catalogue, which is reset.
		cluster_size (int): The maximum number of files per cluster.
		pages_per_batch (int): The number of pages per batch.

	Returns:
		(dict): The manifest of the batches.
	"""

	manifest_path = '%s/%s' % (folder, MANIFEST_FILE)
	if os.path.isfile(manifest_path):
		os.remove(manifest_path)

	stamp = _stamp(src)

	catalogue.reset()
	indexer = _PageIndexer(catalogue, cluster_size, pages_per_batch)

	with open(src, 'rb') as f:
		chunk = f.read(CHUNK_SIZE)
		while len(chunk) > 0:
			indexer.feed(chunk, False)
			chunk = f.read(CHUNK_SIZE)

	indexer.feed(b'', True)

	if indexer.total == 0:
		raise XmlBuildError('No page elements found in "%s".' % src)

	manifest = {'source': stamp, 'root': indexer.root, 'pages_per_batch': pages_per_batch}
	manifest['total_pages'] = indexer.total
	manifest['batches'] = indexer.batches
	_write_manifest(manifest_path, manifest)

	catalogue.set_meta('cluster_size', cluster_size)
	catalogue.set_meta('total_pages', indexer.total)
	catalogue.set_meta('index_complete', 1)

	logger.info('Indexed %d pages in %d batches.' % (indexer.total, len(indexer.batches)))

	return manifest


def _convert_batches(src, dst, manifest, catalogue, workers):
	""" Converts the batches that are not recorded as done. With several workers, the batches run in worker processes, a bounded number
	of them at a time. Each completed batch is recorded before the build goes on.

	Args:
		src (str): Path to the uncompressed MediaWiki XML export.
		dst (str): The destination directory of the Markdown files.
		manifest (dict): The manifest of the batches.
		catalogue (XmlCatalogue): The catalogue that records the completed batches.
		workers (int): The number of worker processes. One converts in the calling process.

	Raises:
		XmlBuildError: When a batch converts an unexpected number of pages.
	"""

	done = catalogue.done_batches()
	pending = [batch for batch in manifest['batches'] if batch['id'] not in done]
	workers = min(workers, len(pending))

	logger.info('Converting %d of %d batches with %d workers.' % (len(pending), len(manifest['batches']), max(workers, 1)))

	if workers <= 1:
		for batch in pending:
			_record(catalogue, batch, convert_batch(src, dst, manifest['root'], batch))

		return

	with ProcessPoolExecutor(max_workers = workers) as pool:
		batches = iter(pending)
		running = {}
		try:
			for batch in islice(batches, 2 * workers):
				running[pool.submit(convert_batch, src, dst, manifest['root'], batch)] = batch

			while len(running) > 0:
				finished, _ = wait(list(running), return_when = FIRST_COMPLETED)

				for future in finished:
					_record(catalogue, running.pop(future), future.result())

					batch = next(batches, None)
					if batch is not None:
						running[pool.submit(convert_batch, src, dst, manifest['root'], batch)] = batch

		finally:
			for future in running:
				future.cancel()


def _record(catalogue, batch, pages):
	""" Records a completed batch in the catalogue.

	Args:
		catalogue (XmlCatalogue): The catalogue.
		batch (dict): The batch from the manifest.
		pages (int): The number of pages that the worker converted.

	Raises:
		XmlBuildError: When the number of pages differs from the manifest.
	"""

	if pages != batch['pages']:
		raise XmlBuildError('Batch %d converted %d pages, expected %d.' % (batch['id'], pages, batch['pages']))

	catalogue.mark_done(batch['id'], pages)

	logger.info('Batch %d done: %d pages.' % (batch['id'], pages))


def _publish(src, manifest, catalogue):
	""" Marks the build as ready, when every batch succeeded, the page count matches the index, and the source did not change.

	Args:
		src (str): Path to the uncompressed MediaWiki XML export.
		manifest (dict): The manifest of the batches.
		catalogue (XmlCatalogue): The catalogue to publish.

	Raises:
		XmlBuildError: When the build is incomplete, or when the source changed while it was built.
	"""

	batches, pages = catalogue.done_summary()
	total = manifest['total_pages']

	if batches != len(manifest['batches']) or pages != total:
		message = 'Only %d of %d batches are complete, with %d of %d pages.'
		raise XmlBuildError(message % (batches, len(manifest['batches']), pages, total))

	stored = catalogue.count_pages()
	if stored != total:
		raise XmlBuildError('The index holds %d pages, expected %d.' % (stored, total))

	if not _is_current(manifest, src):
		raise XmlBuildError('The XML source changed while it was converted.')

	catalogue.set_meta('ready', 1)

	logger.info('Build ready: %d pages in %d batches.' % (total, batches))


def _stamp(src):
	""" Returns the identity of the XML source file: its absolute path, size and modification time.

	Args:
		src (str): Path to the XML source file.

	Returns:
		(dict): The 'path', 'size' and 'mtime_ns' of the file.
	"""

	stat = os.stat(src)

	return {'path': os.path.abspath(src), 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}


def _is_current(manifest, src):
	""" Tells whether a manifest was made from the XML source file as it is now.

	Args:
		manifest (dict): The manifest, or None.
		src (str): Path to the XML source file.

	Returns:
		(bool): True if the size and the modification time of the file are the recorded ones.
	"""

	try:
		recorded = manifest['source']
		stamp = _stamp(src)

		return recorded['size'] == stamp['size'] and recorded['mtime_ns'] == stamp['mtime_ns']

	except (OSError, KeyError, TypeError):
		return False


def _read_manifest(path):
	""" Reads a manifest of batches.

	Args:
		path (str): The path of the manifest file.

	Returns:
		(dict): The manifest, or None when it is missing or unreadable.
	"""

	try:
		with open(path, 'r', encoding = 'utf-8') as f:
			return json.load(f)

	except (OSError, ValueError):
		return None


def _write_manifest(path, manifest):
	""" Writes a manifest atomically, so that a reader never sees a partial file.

	Args:
		path (str): The path of the manifest file.
		manifest (dict): The manifest to write.
	"""

	tmp = '%s.tmp' % path
	with open(tmp, 'w', encoding = 'utf-8') as f:
		json.dump(manifest, f)

	os.replace(tmp, path)


class _PageIndexer:
	""" Indexes a MediaWiki XML export in one streaming pass, using the events of the expat parser.

	A batch is a run of consecutive page elements. It starts at the byte position of its first page, and it ends where the next batch
	starts, or at the end of the root element. The title of each page gives its output file name, which goes to the catalogue.

	Args:
		catalogue (XmlCatalogue): The catalogue that receives the output file names.
		cluster_size (int): The maximum number of files per cluster.
		pages_per_batch (int): The number of pages per batch.
	"""

	def __init__(self, catalogue, cluster_size, pages_per_batch):
		""" Creates the expat parser, with the handlers that index the export. """

		self._catalogue = catalogue
		self._size = cluster_size
		self._per_batch = pages_per_batch

		self._parser = expat.ParserCreate(namespace_separator = '}')
		self._parser.StartNamespaceDeclHandler = self._on_namespace
		self._parser.StartElementHandler = self._on_start
		self._parser.EndElementHandler = self._on_end

		self.root = None		# The opening tag of the root element, with its namespace declarations.
		self.batches = []
		self.total = 0

		self._decls = []
		self._depth = 0
		self._in_page = False
		self._title = None
		self._text = None
		self._batch_start = None
		self._batch_pages = 0
		self._rows = []
		self._titles = []


	def feed(self, data, final):
		""" Feeds the next bytes of the XML export to the parser.

		Args:
			data (bytes): The bytes to parse.
			final (bool): True for the last call.
		"""

		self._parser.Parse(data, final)


	def _on_namespace(self, prefix, uri):
		""" Collects the namespace declarations of the root element. (See expat StartNamespaceDeclHandler.)

		Args:
			prefix (str): The prefix, or None for the default namespace.
			uri (str): The namespace URI.
		"""

		if self._depth == 0:
			self._decls.append((prefix, uri))


	def _on_start(self, name, attrs):
		""" Handles the start of an element: the root, a page, or the title of a page. (See expat StartElementHandler.)

		Args:
			name (str): The element name, as 'namespace}local' inside a namespace.
			attrs (dict): The attributes of the element. They are not needed.
		"""

		self._depth += 1

		if self._depth == 1:
			self._open_root()

		elif self._depth == 2 and name == PAGE_NAME:
			self._begin_page(self._parser.CurrentByteIndex)

		elif self._depth == 3 and self._in_page and self._title is None and name == TITLE_NAME:
			self._text = []
			self._parser.CharacterDataHandler = self._on_text


	def _on_text(self, data):
		""" Collects the text of a page title. (See expat CharacterDataHandler.)

		Args:
			data (str): A piece of the title text.
		"""

		self._text.append(data)


	def _on_end(self, name):
		""" Handles the end of an element: the title of a page, a page, or the root. (See expat EndElementHandler.)

		Args:
			name (str): The element name.
		"""

		if self._depth == 3 and self._text is not None:
			self._parser.CharacterDataHandler = None
			self._title = ''.join(self._text)
			self._text = None

		elif self._depth == 2 and name == PAGE_NAME:
			self._finish_page()

		elif self._depth == 1 and self._batch_pages > 0:
			self._close_batch(self._parser.CurrentByteIndex)

		self._depth -= 1


	def _open_root(self):
		""" Keeps the opening tag of the root element, with the namespace declarations that the ranges of pages need. """

		declarations = ''
		for prefix, uri in self._decls:
			attribute = 'xmlns' if prefix is None else 'xmlns:%s' % prefix
			declarations += ' %s=%s' % (attribute, quoteattr(uri))

		self.root = '<mediawiki%s>' % declarations


	def _begin_page(self, position):
		""" Starts a page at a byte position. The open batch is closed first when it is full, at this same position.

		Args:
			position (int): The byte position of the start tag of the page.
		"""

		if self._batch_pages == self._per_batch:
			self._close_batch(position)

		if self._batch_pages == 0:
			self._batch_start = position

		self._in_page = True
		self._title = None


	def _finish_page(self):
		""" Records the output file name of the page that ends.

		Raises:
			XmlBuildError: When the page has no title.
		"""

		if self._title is None:
			raise XmlBuildError('Page %d has no title.' % self.total)

		name = page_file_name(self._title)
		self._rows.append((self.total, self.total // self._size + 1, name, collision_key(name)))
		self._titles.append(self._title)

		self.total += 1
		self._batch_pages += 1
		self._in_page = False


	def _close_batch(self, end):
		""" Closes the open batch at a byte position, and stores the output file names of its pages.

		Args:
			end (int): The byte position where the batch ends.
		"""

		self._flush()

		batch = {'id': len(self.batches), 'start': self._batch_start, 'end': end, 'pages': self._batch_pages}
		batch['first'] = self.total - self._batch_pages
		self.batches.append(batch)

		self._batch_pages = 0


	def _flush(self):
		""" Stores the output file names of the open batch in the catalogue.

		Raises:
			XmlBuildError: When two pages would be written to the same file.
		"""

		if len(self._rows) == 0:
			return

		try:
			self._catalogue.add_pages(self._rows)

		except sqlite3.IntegrityError:
			raise XmlBuildError(self._collision())

		self._rows = []
		self._titles = []


	def _collision(self):
		""" Describes the first file name collision of the open batch, or with a page that is already stored.

		Returns:
			(str): The message of the error.
		"""

		seen = {}
		for row, title in zip(self._rows, self._titles):
			if row[3] in seen:
				return 'Pages "%s" and "%s" would both be written as "%s".' % (seen[row[3]], title, row[2])

			seen[row[3]] = title

		for row, title in zip(self._rows, self._titles):
			earlier = self._catalogue.name_for(row[3])
			if earlier is not None:
				return 'Page "%s" would be written as "%s", which an earlier page already uses.' % (title, earlier)

		return 'Two pages would be written to the same file.'
