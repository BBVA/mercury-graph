import sys

import pytest

from mercury.graph.evidence.formats import PdfToMarkdown, MDbyPDFoxide, WikiMarkdownWriter
from mercury.graph.evidence.source_parts import MarkdownParser, SourceEntityType


def test_markdown_parser():
	""" Builds line-based entity descriptions for the supported Markdown constructs. """

	content = [
		'# Title', '', 'Text [link](https://example.com) ![image](image.png).', '', '## Section', '- first', '- second', '',
		'| Left | Right |', '| --- | --- |', '| one | two |', '', '> quoted', '', '```text', 'code', '```', '', '---', '[^one]: note'
	]
	parts = MarkdownParser(content).parse()
	types = [part['ent_type'] for part in parts]

	for ent_type in [
		SourceEntityType.TEXT, SourceEntityType.PARAGRAPH, SourceEntityType.LINK, SourceEntityType.IMAGE, SourceEntityType.HEADER_1,
		SourceEntityType.HEADER_2, SourceEntityType.LIST, SourceEntityType.LIST_ITEM, SourceEntityType.TABLE,
		SourceEntityType.TABLE_HEADER, SourceEntityType.TABLE_ROW, SourceEntityType.TABLE_CELL, SourceEntityType.CODE_BLOCK,
		SourceEntityType.BLOCKQUOTE, SourceEntityType.HORIZONTAL_RULE, SourceEntityType.FOOTNOTE
	]:
		assert ent_type.value in types

	header = parts[0]
	assert header['line'] == slice(0, len(content))
	assert header['description'] == 'Title: Title'
	assert next(part for part in parts if part['index'] == 'header_2_1')['description'] == 'Section 1.1: Section'
	assert next(part for part in parts if part['index'] == 'link_1')['span'] == slice(5, 32)


def test_markdown_parser_header_stack_and_block_transition():
	""" Maintains header parents across siblings and ends paragraphs before list blocks. """

	content = ['# First', 'Introduction', '- Item', '## Nested', 'Nested text', '## Sibling', 'Sibling text', '# Second']
	parts = MarkdownParser(content).parse()

	first = next(part for part in parts if part['index'] == 'header_1_1')
	nested = next(part for part in parts if part['index'] == 'header_2_1')
	sibling = next(part for part in parts if part['index'] == 'header_2_2')
	second = next(part for part in parts if part['index'] == 'header_1_2')

	assert first['line'] == slice(0, 7)
	assert nested['parent'] == first['index']
	assert sibling['parent'] == first['index']
	assert second['line'] == slice(7, 8)
	assert next(part for part in parts if part['index'] == 'paragraph_1')['line'] == slice(1, 2)


def test_wiki_markdown_writer():
	""" Renders basic blocks and tolerates the supported wikitext constructs. """

	text = '== Heading ==\r\nPlain text.\r\n\r\n\r\n'
	markdown = WikiMarkdownWriter(text).render()
	writer = WikiMarkdownWriter(None)
	table = ['{| class="wikitable"', '|+ Caption', '! Left !! Right', 'ignored', '|-', '| style="color:red" | First || Second', '|-', '| Last', '|}']
	inline = '<br> <code>code</code> <span>text</span> [[File:image.png]] [[Page]] [https://example.com label] \'\'\'bold\'\'\' \'\'italic\'\''

	assert markdown.startswith('## Heading\n')
	assert 'Plain text.' in markdown
	assert markdown.endswith('\n')
	assert writer.render() == ''
	assert writer._remove_templates('Before {{outer|{{inner}}}} after }}') == 'Before  after }}'
	assert writer._render_tables(['{|', '| unfinished']) == ['{|', '| unfinished']
	assert writer._render_table([]) == []
	assert len(writer._render_tables(table)) == 4
	assert writer._table_cell('note|value') == 'note\\|value'
	assert writer._render_line('** item').endswith('- item')
	assert writer._render_line('# item').startswith('1.')
	assert writer._render_line('; term : definition').startswith('**term:**')
	assert writer._render_inline(inline)


def test_pdf_to_markdown(tmp_path):
	""" Stores absolute source and destination paths for descendant converters. """

	class TestConverter(PdfToMarkdown):

		def run(self):
			return True

		def _ready(self):
			return True

	converter = TestConverter(tmp_path / 'source.pdf', tmp_path / 'result.md', {'language': 'en'})

	assert converter.src == str(tmp_path / 'source.pdf')
	assert converter.dst == str(tmp_path / 'result.md')
	assert converter.extra == {'language': 'en'}
	assert converter.ready
	assert converter.run()
	assert PdfToMarkdown.run(converter) is None
	assert PdfToMarkdown._ready(converter) is None


def test_md_by_pdfoxide(tmp_path, monkeypatch):
	""" Converts with pdf-oxide when its optional dependency is available. """

	class TestDocument:

		def __init__(self, path):
			self.path = path

		def to_markdown_all(self, detect_headings):
			assert detect_headings
			return '# Converted\n'

	module = type('PdfOxide', (), {'PdfDocument': TestDocument})
	source = tmp_path / 'source.pdf'
	destination = tmp_path / 'result.md'
	missing = MDbyPDFoxide(source, destination)

	assert not missing.ready

	source.write_text('PDF content')
	monkeypatch.setitem(sys.modules, 'pdf_oxide', None)

	assert not missing.ready

	monkeypatch.setitem(sys.modules, 'pdf_oxide', module)
	converter = MDbyPDFoxide(source, destination)

	assert converter.ready
	assert converter.run()
	assert destination.read_text() == '# Converted\n'


# if __name__ == "__main__":
# 	pytest.main([__file__])
