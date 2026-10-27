import re, sqlite3, threading


SCHEMA = [
	'CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)',
	'CREATE TABLE IF NOT EXISTS pages (seq INTEGER PRIMARY KEY, cluster INTEGER NOT NULL, name TEXT NOT NULL, fold TEXT NOT NULL UNIQUE)',
	'CREATE INDEX IF NOT EXISTS pages_cluster ON pages (cluster)',
	'CREATE TABLE IF NOT EXISTS done (batch INTEGER PRIMARY KEY, pages INTEGER NOT NULL)'
]

KEY_REX = re.compile('^([0-9]+):([0-9]+)$')	# A cluster key of an index, such as '2:17'.

MOVE_CHUNK = 100000	# Pages moved per transaction when the clusters change size.


def cluster_count(total, size, level):
	""" Returns how many nodes a level of the cluster tree has. Level 0 holds the pages, level 1 the clusters of pages, level 2 the
	clusters of level 1 clusters, and so on. Pages are assigned in sequence order, so every node is full except the last one.

	Args:
		total (int): The number of pages.
		size (int): The maximum number of children of a node.
		level (int): The level of the tree.

	Returns:
		(int): The number of nodes at that level.
	"""

	return -(-total // size ** level)


class XmlCatalogue:
	""" The disk-backed catalogue of the Markdown files of one XML export. It holds the output file name and the cluster of every page,
	the batches that are done, and the state of the build. No page is kept in memory.

	The clusters are numbered in page order. The leaf cluster of the page with sequence number `seq` is `seq // size + 1`, and the
	clusters above it group consecutive clusters. So the cluster tree is derived from the leaf numbers and it is not stored.

	Args:
		path (str): The path of the SQLite database. It is created when missing.
	"""

	def __init__(self, path):
		""" Opens the catalogue, creating its tables when they are missing. """

		self._lock = threading.Lock()
		self._db = sqlite3.connect(path, check_same_thread = False)
		self._db.execute('PRAGMA journal_mode = WAL').fetchall()
		self._db.execute('PRAGMA synchronous = NORMAL')
		self._create_schema()

		self._size = self._int_meta('cluster_size')
		self._total = self._int_meta('total_pages')


	@property
	def size(self):
		""" Returns the maximum number of children of a cluster. """

		return self._size


	@property
	def depth(self):
		""" Returns the number of cluster levels above the pages. It is the smallest depth whose top level has at most `size` nodes. """

		depth = 0
		while cluster_count(self._total, self._size, depth) > self._size:
			depth += 1

		return depth


	def close(self):
		""" Closes the database connection. """

		with self._lock:
			self._db.close()


	def reset(self):
		""" Drops the content of the catalogue, so that a new build starts from an empty one. """

		with self._lock, self._db:
			for table in ['meta', 'done', 'pages']:
				self._db.execute('DROP TABLE IF EXISTS %s' % table)

		self._create_schema()
		self._size = None
		self._total = None


	def get_meta(self, key):
		""" Returns a value of the build metadata.

		Args:
			key (str): The name of the value.

		Returns:
			(str): The value, or None when it is not stored.
		"""

		with self._lock:
			row = self._db.execute('SELECT value FROM meta WHERE key = ?', (key,)).fetchone()

		return None if row is None else row[0]


	def set_meta(self, key, value):
		""" Stores a value of the build metadata.

		Args:
			key (str): The name of the value.
			value (int or str): The value. It is stored as text.
		"""

		with self._lock, self._db:
			self._db.execute('INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)', (key, str(value)))


	def index_complete(self):
		""" Tells whether the pages of the XML export are indexed. """

		return self.get_meta('index_complete') == '1'


	def is_ready(self):
		""" Tells whether the build is published: every batch succeeded and the page count matches the index. """

		return self.get_meta('ready') == '1'


	def add_pages(self, rows):
		""" Stores the output file names of a batch of pages, as one transaction.

		Args:
			rows (list of tuple): Each row is (seq, cluster, name, fold). The fold must be unique, see collision_key().

		Raises:
			sqlite3.IntegrityError: When the fold of a row is already stored. Two pages would be written to the same file.
		"""

		with self._lock, self._db:
			self._db.executemany('INSERT INTO pages (seq, cluster, name, fold) VALUES (?, ?, ?, ?)', rows)


	def name_for(self, fold):
		""" Returns the file name stored under a fold key.

		Args:
			fold (str): The key, see collision_key().

		Returns:
			(str): The file name, or None when no page has that key.
		"""

		with self._lock:
			row = self._db.execute('SELECT name FROM pages WHERE fold = ?', (fold,)).fetchone()

		return None if row is None else row[0]


	def count_pages(self):
		""" Returns the number of pages stored in the catalogue. """

		with self._lock:
			return self._db.execute('SELECT COUNT(*) FROM pages').fetchone()[0]


	def mark_done(self, batch, pages):
		""" Records that a batch was converted completely.

		Args:
			batch (int): The id of the batch.
			pages (int): The number of pages converted.
		"""

		with self._lock, self._db:
			self._db.execute('INSERT OR REPLACE INTO done (batch, pages) VALUES (?, ?)', (batch, pages))


	def done_batches(self):
		""" Returns the ids of the batches recorded as done.

		Returns:
			(set of int): The ids.
		"""

		with self._lock:
			rows = self._db.execute('SELECT batch FROM done').fetchall()

		return {row[0] for row in rows}


	def done_summary(self):
		""" Returns how many batches are done and how many pages they converted.

		Returns:
			(tuple): (batches, pages), both integers.
		"""

		with self._lock:
			return self._db.execute('SELECT COUNT(*), COALESCE(SUM(pages), 0) FROM done').fetchone()


	def names(self, cluster):
		""" Returns the file names of the pages in a leaf cluster, in page order. It is a query of one cluster.

		Args:
			cluster (int): The number of the leaf cluster.

		Returns:
			(list of str): The file names.
		"""

		with self._lock:
			rows = self._db.execute('SELECT name FROM pages WHERE cluster = ? ORDER BY seq', (cluster,)).fetchall()

		return [row[0] for row in rows]


	def has_name(self, cluster, name):
		""" Tells whether a leaf cluster holds a page with the given file name.

		Args:
			cluster (int): The number of the leaf cluster.
			name (str): The file name.

		Returns:
			(bool): True if the page exists.
		"""

		with self._lock:
			row = self._db.execute('SELECT 1 FROM pages WHERE cluster = ? AND name = ? LIMIT 1', (cluster, name)).fetchone()

		return row is not None


	def recluster(self, size):
		""" Assigns the pages to the clusters of a new size. Only the cluster column changes, the Markdown files are not touched.

		Args:
			size (int): The new maximum number of children of a cluster.
		"""

		for first in range(0, self._total, MOVE_CHUNK):
			with self._lock, self._db:
				self._db.execute('UPDATE pages SET cluster = seq / ? + 1 WHERE seq >= ? AND seq < ?', (size, first, first + MOVE_CHUNK))

		self.set_meta('cluster_size', size)
		self._size = size


	def locate(self, parts):
		""" Resolves the parts of an index below the SourceMaker, such as ['2:1', '1:2', 'Title.md'].

		Args:
			parts (list of str): The parts of the index after the SourceMaker index.

		Returns:
			(tuple): (numbers, name, consumed). numbers is the list of cluster numbers from the top level down, name is the file name
				or None when the parts end at a cluster, and consumed is how many parts the node uses. None when the parts are not
				an existing node of the catalogue.
		"""

		count = 0
		while count < len(parts) and ':' in parts[count]:
			count += 1

		numbers = self._numbers(parts[0:count])
		if numbers is None:
			return None

		if count == len(parts):
			return (numbers, None, count)

		if count != self.depth or not self.has_name(self._leaf(numbers), parts[count]):
			return None

		return (numbers, parts[count], count + 1)


	def children(self, numbers):
		""" Returns the children of a cluster. The children of a leaf cluster are the file names of its pages. The children of the
		SourceMaker itself are its top level clusters, or the file names when the catalogue has no clusters.

		Args:
			numbers (list of int): The cluster numbers from the top level down. An empty list is the SourceMaker.

		Returns:
			(list of str): The keys of the child clusters, such as '1:4', or the file names of the pages.
		"""

		if len(numbers) == self.depth:
			return self.names(self._leaf(numbers))

		level = self.depth - len(numbers)
		if len(numbers) == 0:
			first, last = 1, cluster_count(self._total, self._size, level)
		else:
			first = (numbers[-1] - 1) * self._size + 1
			last = min(numbers[-1] * self._size, cluster_count(self._total, self._size, level))

		return ['%d:%d' % (level, number) for number in range(first, last + 1)]


	def _create_schema(self):
		""" Creates the tables of the catalogue when they do not exist yet. """

		with self._db:
			for statement in SCHEMA:
				self._db.execute(statement)


	def _int_meta(self, key):
		""" Returns a value of the build metadata as an integer.

		Args:
			key (str): The name of the value.

		Returns:
			(int): The value, or None when it is not stored.
		"""

		value = self.get_meta(key)

		return None if value is None else int(value)


	def _numbers(self, keys):
		""" Validates the cluster keys of an index against the cluster tree.

		Args:
			keys (list of str): The cluster keys from the top level down, such as ['2:1', '1:2'].

		Returns:
			(list of int): The cluster numbers, or None when the keys are not a path of existing clusters.
		"""

		numbers = []
		level = self.depth
		for key in keys:
			found = KEY_REX.match(key)
			if found is None or level < 1 or int(found.group(1)) != level:
				return None

			number = int(found.group(2))
			if number < 1 or number > cluster_count(self._total, self._size, level):
				return None

			if len(numbers) > 0 and (number - 1) // self._size + 1 != numbers[-1]:
				return None

			numbers.append(number)
			level -= 1

		return numbers


	def _leaf(self, numbers):
		""" Returns the number of the leaf cluster of a cluster path. Without clusters, all the pages are in the leaf 1.

		Args:
			numbers (list of int): The cluster numbers from the top level down.

		Returns:
			(int): The leaf cluster number.
		"""

		return numbers[-1] if len(numbers) > 0 else 1
