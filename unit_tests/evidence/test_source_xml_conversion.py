import os

import pytest

from lxml import etree

from mercury.graph.evidence.formats import WikiMarkdownWriter
from mercury.graph.evidence.source_parts.xml_conversion import collision_key, convert_batch, page_file_name, write_page_as_md


NS = 'http://www.mediawiki.org/xml/export-0.11/'
ROOT = '<mediawiki xmlns="%s">' % NS
PAGE = '<page><title>%s</title><revision><text>%s</text></revision></page>'


def test_page_file_name():
	""" Encodes the characters that cannot appear in file names, leading spaces, and removes trailing spaces. """

	assert page_file_name('Riverside Robotics Club') == 'Riverside Robotics Club.md'
	assert page_file_name(' Lead') == '%20Lead.md'
	assert page_file_name('Trailing  ') == 'Trailing.md'
	assert page_file_name('a/b:c|d') == 'a%2Fb%3Ac%7Cd.md'


def test_collision_key():
	""" Names that differ only in case, or only in Unicode normalization, share the same key. """

	assert collision_key(page_file_name('IPhone')) == collision_key(page_file_name('Iphone'))
	assert collision_key('Caf\u00e9.md') == collision_key('Cafe\u0301.md')
	assert collision_key('Cafe.md') != collision_key('Caf\u00e9.md')


def test_write_page_as_md(tmp_path):
	""" Writes the title as the level-one heading, followed by the rendered wikitext of the page. """

	elem = etree.fromstring('<page xmlns="%s"><title>Title</title><revision><text>%s</text></revision></page>' % (NS, "'''Bold''' text."))
	fn = write_page_as_md(str(tmp_path), 'Title', elem)

	assert fn == '%s/Title.md' % str(tmp_path)
	assert (tmp_path / 'Title.md').read_text(encoding = 'utf-8') == '# Title\n\n**Bold** text.\n'
	assert WikiMarkdownWriter("'''Bold''' text.").render() == '**Bold** text.\n'


def test_convert_batch(tmp_path):
	""" Converts exactly the pages of the byte range. A range that does not hold the expected pages is an error. """

	src = tmp_path / 'source.xml'
	src.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<!-- head -->\n%s\n%s\n%s\n</mediawiki>\n' % (
		ROOT, PAGE % ('One', 'First'), PAGE % ('Two', 'Second')), encoding = 'utf-8')
	data = src.read_bytes()
	dst = tmp_path / 'out'
	dst.mkdir()

	first = data.index(b'<page>')
	second = data.index(b'<page>', first + 1)
	end = data.index(b'</mediawiki>')

	assert convert_batch(str(src), str(dst), ROOT, {'id': 0, 'start': first, 'end': second, 'pages': 1}) == 1
	assert os.listdir(str(dst)) == ['One.md']
	assert convert_batch(str(src), str(dst), ROOT, {'id': 1, 'start': second, 'end': end, 'pages': 1}) == 1
	assert sorted(os.listdir(str(dst))) == ['One.md', 'Two.md']

	with pytest.raises(ValueError):
		convert_batch(str(src), str(dst), ROOT, {'id': 2, 'start': first, 'end': second, 'pages': 2})

	with pytest.raises(ValueError):
		convert_batch(str(src), str(dst), ROOT, {'id': 3, 'start': len(data), 'end': len(data) + 10, 'pages': 1})
