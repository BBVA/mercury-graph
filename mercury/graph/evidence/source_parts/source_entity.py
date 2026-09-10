from .source_node import SourceNode, SourceState
from .source_entity_type import SourceEntityType


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
			return self._parent.lines(self._line)

		return self._parent.line_slice(self._line, self._span)


	@property
	def entity_type(self):
		""" Returns the type of this SourceEntity. It is one of the values in the SourceEntityType enumeration. """

		return SourceEntityType(self._type)


	def get_children_idx(self, index = None):
		""" Returns the children indices of this SourceEntity. Only SourceEntity with children have children indices.

		(See [`SourceNode.get_children_idx()`][mercury.graph.evidence.source_parts.SourceNode.get_children_idx].)
		"""

		if self._children is not None:
			return list(self._children.keys())


	def child(self, index):
		""" Returns the child of this SourceEntity with the given index.

		The child can only be a deeper SourceEntity or None.

		(See [`SourceNode.child()`][mercury.graph.evidence.source_parts.SourceNode.child].)
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
