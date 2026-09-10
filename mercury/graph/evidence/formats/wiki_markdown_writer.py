import regex


class WikiMarkdownWriter:
	""" Converts the useful MediaWiki wikitext in a Wikipedia page to Markdown.

	(See [Warning](evidence_formats.md#warning) about the limitations of this conversion.)

	Args:
		text (str): Wikitext to convert. None is treated as an empty page.
	"""

	def __init__(self, text):
		self.text = text or ''


	def render(self):
		""" Returns the page wikitext as a clean Markdown document body.

		Returns:
			(str): Markdown without an article title heading.
		"""

		text = self.text.replace('\r\n', '\n').replace('\r', '\n')
		text = regex.sub('<!--[\\s\\S]*?-->', '', text)
		text = regex.sub('<ref(?:\\s[^>]*)?\\s*/\\s*>', '', text, flags = regex.IGNORECASE)
		text = regex.sub('<ref(?:\\s[^>]*)?>[\\s\\S]*?</ref\\s*>', '', text, flags = regex.IGNORECASE)
		text = self._remove_templates(text)

		lines = self._render_tables(text.split('\n'))
		lines = [self._render_line(line) for line in lines]

		return self._normalize_lines(lines)


	def _remove_templates(self, text):
		""" Removes nested templates and parser functions, which do not have Markdown equivalents.

		Args:
			text (str): Wikitext that may contain ``{{...}}`` fragments.

		Returns:
			(str): Wikitext with templates removed.
		"""

		result = []
		depth  = 0
		pos	   = 0
		while pos < len(text):
			pair = text[pos:pos + 2]

			if pair == '{{':
				depth += 1
				pos += 2
				continue

			if pair == '}}' and depth:
				depth -= 1
				pos += 2
				continue

			if not depth:
				result.append(text[pos])

			pos += 1

		return ''.join(result)


	def _render_tables(self, lines):
		""" Converts MediaWiki table blocks in lines to GitHub-flavored Markdown tables.

		Args:
			lines (list of str): Source lines.

		Returns:
			(list of str): Lines with each complete table replaced by Markdown lines.
		"""

		result = []
		pos	   = 0
		while pos < len(lines):
			if not lines[pos].lstrip().startswith('{|'):
				result.append(lines[pos])
				pos += 1
				continue

			end = pos + 1
			while end < len(lines) and not lines[end].lstrip().startswith('|}'):
				end += 1

			if end == len(lines):
				result.append(lines[pos])
				pos += 1
				continue

			result.extend(self._render_table(lines[pos + 1:end]))
			pos = end + 1

		return result


	def _render_table(self, lines):
		""" Renders the contents of one MediaWiki table block.

		Args:
			lines (list of str): Lines between ``{|`` and ``|}``.

		Returns:
			(list of str): A Markdown table, or readable fallback lines when no cells exist.
		"""

		rows	= []
		current	= []
		for line in lines:
			stripped = line.strip()
			if not stripped or stripped.startswith('|-'):
				if current:
					rows.append(current)
					current = []
				continue

			if stripped.startswith('|+'):
				continue

			if stripped.startswith('!'):
				cells = stripped[1:].split('!!')
			elif stripped.startswith('|'):
				cells = stripped[1:].split('||')
			else:
				continue

			for cell in cells:
				current.append(self._table_cell(cell))

		if current:
			rows.append(current)

		if not rows:
			return []

		width = max([len(row) for row in rows])
		for row in rows:
			row.extend([''] * (width - len(row)))

		header = rows[0]

		return ['| %s |' % ' | '.join(header), '| %s |' % ' | '.join(['---'] * width)] + ['| %s |' % ' | '.join(row) for row in rows[1:]]


	def _table_cell(self, cell):
		""" Removes MediaWiki cell attributes and renders one table cell.

		Args:
			cell (str): A source table cell, optionally prefixed by attributes and ``|``.

		Returns:
			(str): Escaped Markdown cell content.
		"""

		if '|' in cell:
			attributes, value = cell.split('|', 1)

			if '=' in attributes or attributes.strip().startswith(('style', 'class', 'colspan', 'rowspan')):
				cell = value

		return self._render_line(cell).strip().replace('|', '\\|').replace('\n', '<br>')


	def _render_line(self, line):
		""" Converts headings, lists, links, emphasis, and HTML-like markup in one line.

		Args:
			line (str): One wikitext line.

		Returns:
			(str): The corresponding Markdown line.
		"""

		match = regex.match('^\\s*(={2,6})\\s*(.*?)\\s*\\1\\s*$', line)
		if match:
			return '%s %s' % ('#' * len(match.group(1)), self._render_inline(match.group(2)))

		match = regex.match('^([*#]+)\\s*(.*)$', line)
		if match:
			marks = match.group(1)
			indent = '  ' * (len(marks) - 1)
			marker = '1.' if marks[-1] == '#' else '-'
			return '%s%s %s' % (indent, marker, self._render_inline(match.group(2)))

		match = regex.match('^;\\s*([^:]+)\\s*:\\s*(.*)$', line)
		if match:
			return '**%s:** %s' % (self._render_inline(match.group(1)), self._render_inline(match.group(2)))

		return self._render_inline(line)


	def _render_inline(self, text):
		""" Converts inline MediaWiki markup to Markdown.

		Args:
			text (str): Inline wikitext.

		Returns:
			(str): Markdown inline content.
		"""

		flags = regex.IGNORECASE

		text = regex.sub('<(?:br|br /|br/)\\s*>', '<br>', text, flags = flags)
		text = regex.sub('<(?:nowiki|pre|code)(?:\\s[^>]*)?>([\\s\\S]*?)</(?:nowiki|pre|code)\\s*>', '`\\1`', text, flags = flags)
		text = regex.sub('<[^>]+>', '', text)
		text = regex.sub('\\[\\[(?:File|Image|Category):[^\\]]+\\]\\]', '', text, flags = flags)
		text = regex.sub('\\[\\[([^\\]|]+)\\|([^\\]]+)\\]\\]', r'\\2', text)
		text = regex.sub('\\[\\[([^\\]]+)\\]\\]', r'\\1', text)
		text = regex.sub('\\[(https?://[^\\s\\]]+)\\s+([^\\]]+)\\]', r'[\\2](\\1)', text)
		text = regex.sub("'''(.*?)'''", r'**\\1**', text)
		text = regex.sub("''(.*?)''", r'*\\1*', text)

		return regex.sub('[ \\t]+', ' ', text).strip()


	def _normalize_lines(self, lines):
		""" Collapses excess blank lines while retaining Markdown block separation.

		Args:
			lines (list of str): Rendered Markdown lines.

		Returns:
			(str): Normalized Markdown ending in one newline, or an empty string.
		"""

		result = []
		for line in lines:
			if not line.strip() and (not result or not result[-1]):
				continue

			result.append(line.rstrip())

		while result and not result[-1]:
			result.pop()

		return '\n'.join(result) + ('\n' if result else '')
