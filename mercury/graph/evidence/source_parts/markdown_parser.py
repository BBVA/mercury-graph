import re

from .source_entity_type import SourceEntityType


class MarkdownParser:
	""" Builds a small, line-oriented representation of the Markdown entities in a file.

	The parser deliberately recognizes the common Markdown blocks without attempting to
	fully implement CommonMark.  Each returned item has either a line slice for a
	multiline entity or a character slice for a single line entity.  SourceFile owns
	the construction of SourceEntity objects from these items.

	Args:
		content (list of str): Markdown lines without their newline characters.
	"""

	HEADER	 = re.compile('^[ \\t]{0,3}(#{1,6})[ \\t]+(.*?)[ \\t]*$')
	FENCE	 = re.compile('^[ \\t]*(`{3,}|~{3,})')
	LIST	 = re.compile('^[ \\t]*(?:[-+*]|\\d+[.)])[ \\t]+')
	QUOTE	 = re.compile('^[ \\t]*>[ \\t]?')
	FOOTNOTE = re.compile('^[ \\t]*\\[\\^[^]]+\\]:[ \\t]*')
	RULE	 = re.compile('^[ \\t]{0,3}(?:[-*_][ \\t]*){3,}$')
	LINK	 = re.compile('!?(?:\\[[^]]*\\]\\([^)]*\\)|\\[[^]]+\\]\\[[^]]*\\])')

	def __init__(self, content):
		""" Stores the source lines to parse.

		Args:
			content (list of str): Markdown lines without newline characters.
		"""

		self._content = content
		self._parts = []
		self._counts = {}
		self._header_counts = {}


	def parse(self):
		""" Returns ordered entity descriptions for the complete Markdown document.

		Returns:
			(list of dict): Entity construction data, ordered so parents precede children.
		"""

		headers = self._headers()
		header_stack = []
		line = 0

		while line < len(self._content):
			header = headers.get(line)
			if header is not None:
				level, title, end = header
				while header_stack and header_stack[-1][0] >= level:
					header_stack.pop()

				parent = header_stack[-1][1] if header_stack else None
				number = self._header_number(level)

				if level == 1:
					descr = 'Title: %s' % title
				else:
					descr = 'Section %s: %s' % (number, title)

				part = self._add('header_%d' % level, parent, SourceEntityType.HEADER_1.value + level - 1, slice(line, end), None, descr)
				title_start = self._content[line].find(title)

				if title_start >= 0 and title:
					self._add('text', part, SourceEntityType.TEXT.value, line, slice(title_start, title_start + len(title)), None)

				header_stack.append((level, part, number))
				line += 1

				continue

			parent	= header_stack[-1][1] if header_stack else None
			section	= header_stack[-1][2] if header_stack else 'document'
			line	= self._block(line, parent, section, headers)

		return self._parts


	def _headers(self):
		""" Finds headings and calculates each heading's complete line range. """

		found = []
		in_fence = None

		for line, text in enumerate(self._content):
			fence = self.FENCE.match(text)

			if fence:
				marker = fence.group(1)[0]

				if in_fence is None:
					in_fence = marker
				elif marker == in_fence:
					in_fence = None

				continue

			if in_fence is None:
				match = self.HEADER.match(text)

				if match:
					title = match.group(2).rstrip('#').rstrip()
					found.append((line, len(match.group(1)), title))

		ret = {}
		for pos, (line, level, title) in enumerate(found):
			end = len(self._content)
			for next_line, next_level, unused_title in found[pos + 1:]:
				if next_level <= level:
					end = next_line
					break

			ret[line] = (level, title, end)

		return ret


	def _header_number(self, level):
		""" Advances and returns the dotted number for a heading level.

		Args:
			level (int): Markdown heading level from one through six.

		Returns:
			(str): The heading number, such as '2.3'.
		"""

		for item in range(level + 1, 7):
			self._header_counts['header_%d' % item] = 0

		key = 'header_%d' % level
		self._header_counts[key] = self._header_counts.get(key, 0) + 1

		return '.'.join(str(self._header_counts.get('header_%d' % item, 0)) for item in range(1, level + 1))


	def _block(self, line, parent, section, headers):
		""" Parses one non-heading block and returns the first unconsumed line. """

		text = self._content[line]

		if not text.strip():
			return line + 1

		if self.FENCE.match(text):
			return self._fenced_code(line, parent)

		if self.RULE.match(text):
			self._add('horizontal_rule', parent, SourceEntityType.HORIZONTAL_RULE.value, line, slice(0, len(text)), None)
			return line + 1

		if self.FOOTNOTE.match(text):
			self._add('footnote', parent, SourceEntityType.FOOTNOTE.value, line, slice(0, len(text)), None)
			return line + 1

		if self.QUOTE.match(text):
			return self._quote(line, parent, headers)

		if self.LIST.match(text):
			return self._list(line, parent, headers)

		if self._is_table_start(line):
			return self._table(line, parent)

		return self._paragraph(line, parent, section, headers)


	def _fenced_code(self, line, parent):
		""" Adds a fenced code block and line text children. """

		marker = self.FENCE.match(self._content[line]).group(1)[0]
		end = line + 1
		while end < len(self._content):
			if self.FENCE.match(self._content[end]) and self.FENCE.match(self._content[end]).group(1)[0] == marker:
				end += 1

				break

			end += 1

		part = self._add('code_block', parent, SourceEntityType.CODE_BLOCK.value, slice(line, end), None, None)

		for item in range(line, end):
			self._add('text', part, SourceEntityType.TEXT.value, item, slice(0, len(self._content[item])), None)

		return end


	def _quote(self, line, parent, headers):
		""" Adds one blockquote for adjacent quoted lines. """

		end = line
		while end < len(self._content) and end not in headers and self.QUOTE.match(self._content[end]):
			end += 1

		part = self._add('blockquote', parent, SourceEntityType.BLOCKQUOTE.value, slice(line, end), None, None)

		for item in range(line, end):
			match = self.QUOTE.match(self._content[item])
			self._inline(part, item, match.end(), len(self._content[item]))

		return end


	def _list(self, line, parent, headers):
		""" Adds a list with one item per adjacent Markdown list line. """

		end = line
		while end < len(self._content) and end not in headers and self.LIST.match(self._content[end]):
			end += 1

		part = self._add('list', parent, SourceEntityType.LIST.value, slice(line, end), None, None)
		for item in range(line, end):
			match = self.LIST.match(self._content[item])
			child = self._add('list_item', part, SourceEntityType.LIST_ITEM.value, item, slice(match.end(), len(self._content[item])), None)
			self._inline(child, item, match.end(), len(self._content[item]))

		return end


	def _is_table_start(self, line):
		""" Returns whether a pipe row is followed by a Markdown table separator. """

		return line + 1 < len(self._content) and '|' in self._content[line] and bool(re.match('^[ |:\\-]+$', self._content[line + 1]))


	def _table(self, line, parent):
		""" Adds a table, rows, and cells from a simple pipe table. """

		end = line + 2
		while end < len(self._content) and '|' in self._content[end] and self._content[end].strip():
			end += 1

		part = self._add('table', parent, SourceEntityType.TABLE.value, slice(line, end), None, None)

		for item in [line] + list(range(line + 2, end)):
			typ = SourceEntityType.TABLE_HEADER.value if item == line else SourceEntityType.TABLE_ROW.value
			row = self._add('table_header' if item == line else 'table_row', part, typ, item, slice(0, len(self._content[item])), None)

			for start, stop in self._cells(self._content[item]):
				self._add('table_cell', row, SourceEntityType.TABLE_CELL.value, item, slice(start, stop), None)

		return end


	def _cells(self, text):
		""" Returns trimmed character ranges for the simple pipe-separated cells. """

		ret = []
		for match in re.finditer('(?:^|(?<!\\\\)\\|)([^|]*)', text):
			value = match.group(1)
			start = match.start(1) + len(value) - len(value.lstrip())
			stop  = match.start(1) + len(value.rstrip())

			if start < stop:
				ret.append((start, stop))

		return ret


	def _paragraph(self, line, parent, section, headers):
		""" Adds adjacent ordinary lines as a paragraph with inline children. """

		end = line
		while end < len(self._content) and end not in headers and self._content[end].strip():
			if end != line and (self.FENCE.match(self._content[end]) or self.RULE.match(self._content[end])
				or self.FOOTNOTE.match(self._content[end])
				or self.QUOTE.match(self._content[end]) or self.LIST.match(self._content[end]) or self._is_table_start(end)):

				break

			end += 1

		part = self._add('paragraph', parent, SourceEntityType.PARAGRAPH.value, slice(line, end), None, 'Content of %s' % section)

		for item in range(line, end):
			self._inline(part, item, 0, len(self._content[item]))

		return end


	def _inline(self, parent, line, start, stop):
		""" Adds TEXT, LINK, and IMAGE leaves which partition a range in one line. """

		cursor = start
		for match in self.LINK.finditer(self._content[line], start, stop):
			if match.start() > cursor:
				self._add('text', parent, SourceEntityType.TEXT.value, line, slice(cursor, match.start()), None)

			typ = SourceEntityType.IMAGE.value if match.group(0).startswith('!') else SourceEntityType.LINK.value
			etp = 'image' if typ == SourceEntityType.IMAGE.value else 'link'
			self._add(etp, parent, typ, line, slice(match.start(), match.end()), None)
			cursor = match.end()

		if cursor < stop:
			self._add('text', parent, SourceEntityType.TEXT.value, line, slice(cursor, stop), None)


	def _add(self, name, parent, ent_type, line, span, descr):
		""" Appends one entity description and returns its local index. """

		self._counts[name] = self._counts.get(name, 0) + 1
		index = '%s_%d' % (name, self._counts[name])
		self._parts.append({'index': index, 'parent': parent, 'ent_type': ent_type, 'line': line, 'span': span, 'description': descr})

		return index
