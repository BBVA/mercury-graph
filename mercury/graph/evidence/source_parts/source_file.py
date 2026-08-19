import os

from .source_node import SourceNode, SourceState
from .source_entity import SourceEntity
from .markdown_parser import MarkdownParser


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

		parser = MarkdownParser(self._content)
		entities = {}

		for part in parser.parse():
			parent = self if part['parent'] is None else entities[part['parent']]
			entity = SourceEntity('%s|%s' % (self.index, part['index']), parent, part['ent_type'], part['line'], part['span'],
				part['description'])
			entities[part['index']] = entity

			if parent is self:
				self._children[entity.index] = entity
			else:
				parent.add_child(entity)

		self.state = SourceState.READY.value
