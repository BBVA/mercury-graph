from enum import Enum


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
