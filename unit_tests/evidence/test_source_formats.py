import sys

import pytest

from mercury.graph.evidence.formats import PdfToMarkdown, MDbyPDFoxide, WikiMarkdownWriter


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
