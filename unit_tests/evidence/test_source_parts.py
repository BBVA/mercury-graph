import os

import pytest

from lxml import etree

from mercury.graph.evidence import SourceNode, SourceMaker, SourceFile, SourceEntity


class DummySourceNode(SourceNode):
	""" Minimal SourceNode implementation used to exercise the abstract base class. """

	def get_children_idx(self, index = None):
		return []

	def child(self, index):
		return None


class ReadyConverter:
	""" Minimal converter that writes a Markdown destination. """

	def __init__(self, source, destination, extra):
		self.destination = destination

	def ready(self):
		return True

	def run(self):
		with open(self.destination, 'w') as f:
			f.write('# Converted\n')


class NotReadyConverter:
	""" Minimal converter that cannot run. """

	def __init__(self, source, destination, extra):
		pass

	def ready(self):
		return False


def test_source_node():

	node = DummySourceNode('source')

	node.type
	node.index
	node.description
	node.get_children_idx()
	node.child('source|child')

	SourceNode.get_children_idx(node)
	SourceNode.child(node, 'source|child')


def test_source_maker(tmp_path, monkeypatch):
	(tmp_path / 'source.md').write_text('# Source\n')
	(tmp_path / 'ignored.txt').write_text('Ignored\n')
	os.symlink('missing', tmp_path / 'broken')
	(tmp_path / 'folder').mkdir()
	(tmp_path / 'folder' / 'nested.md').write_text('# Nested\n')

	maker = SourceMaker('source', 'markdown_tree', None, str(tmp_path), 10, '.md', None)

	maker.build_indices()
	maker.get_children_idx()
	maker.get_children_idx('other')
	maker.get_children_idx('source|missing')
	maker.get_children_idx('source')
	maker.child('other')
	maker.child('source|missing')
	maker.child('source')
	maker._safe_filename(str(tmp_path), ' invalid ')
	maker._recurse_tree(str(tmp_path / 'missing'))

	tim = int(os.path.getmtime(str(tmp_path / 'folder' / 'nested.md')))

	# Touch the file to update its modification time
	os.utime(str(tmp_path / 'folder' / 'nested.md'), (tim - 60, tim - 60))

	assert maker._recurse_tree(str(tmp_path), abort_if_before = tim - 2) is None

	missing_tree = SourceMaker('missing_tree', 'markdown_tree', None, str(tmp_path / 'missing'), 10, None, None)
	missing_tree.build_indices()

	cluster_path = tmp_path / 'cluster'
	cluster_path.mkdir()
	(cluster_path / 'one.md').write_text('One\n')
	(cluster_path / 'two.md').write_text('Two\n')
	(cluster_path / 'three.md').write_text('Three\n')
	clustered = SourceMaker('clustered', 'markdown_tree', None, str(cluster_path), 2, None, None)
	clustered.build_indices()
	clustered.get_children_idx('clustered|1:1')
	clustered.child('clustered|1:1')

	src_path = tmp_path / 'pdf_source'
	dst_path = tmp_path / 'pdf_destination'
	src_path.mkdir()
	(src_path / 'source.md').write_text('# Source\n')
	pdf = SourceMaker('pdf', 'pdf_mirror', str(src_path), str(dst_path), 10, None, None)
	pdf.build_indices()
	pdf.child('pdf|source.md')
	(dst_path / 'source.md').write_text('# Source\n')
	pdf.child('pdf|source.md')
	pdf.child('pdf|source.md')

	missing = SourceMaker('missing', 'pdf_mirror', str(tmp_path / 'missing'), str(tmp_path / 'destination'), 10, None, None)
	missing.build_indices()

	xml = SourceMaker('xml', 'xml_stream', str(tmp_path / 'missing.xml'), str(tmp_path / 'xml_destination'), 10, None, None)
	xml.build_indices()

	xml_path = tmp_path / 'source.xml'
	xml_path.write_text('<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/"><page><title>One</title><revision><text>First</text></revision></page><page><title>Two</title><revision><text>Second</text></revision></page></mediawiki>')
	xml_destination = tmp_path / 'xml_destination'
	xml_destination.mkdir()
	old_file = xml_destination / 'old.md'
	old_file.write_text('Old\n')
	os.utime(old_file, (1, 1))
	xml = SourceMaker('xml', 'xml_stream', str(xml_path), str(xml_destination), 10, None, None)
	xml.build_indices()
	xml._create_markdown_from_xml()
	xml_without_destination = SourceMaker('xml_without_destination', 'xml_stream', str(xml_path), str(tmp_path / 'new_xml_destination'), 10, None, None)
	xml_without_destination._create_markdown_from_xml()

	failed_tree = SourceMaker('failed_tree', 'markdown_tree', None, str(tmp_path), 10, None, None)
	failed_tree._recurse_tree = lambda: None
	failed_tree.build_indices()

	failed_pdf = SourceMaker('failed_pdf', 'pdf_mirror', str(src_path), str(dst_path), 10, None, None)
	failed_pdf._recurse_tree = lambda root: None
	failed_pdf.build_indices()

	failed_xml = SourceMaker('failed_xml', 'xml_stream', str(xml_path), str(xml_destination), 10, None, None)
	failed_xml._recurse_tree = lambda abort_if_before = None: None
	failed_xml._create_markdown_from_xml = lambda: False
	failed_xml.build_indices()

	def recurse_xml(abort_if_before = None):
		if abort_if_before is not None:
			return None

		return {}

	ready_xml = SourceMaker('ready_xml', 'xml_stream', str(xml_path), str(xml_destination), 10, None, None)
	ready_xml._recurse_tree = recurse_xml
	ready_xml._create_markdown_from_xml = lambda: True
	ready_xml.build_indices()

	failed_ready_xml = SourceMaker('failed_ready_xml', 'xml_stream', str(xml_path), str(xml_destination), 10, None, None)
	failed_ready_xml._recurse_tree = lambda abort_if_before = None: None
	failed_ready_xml._create_markdown_from_xml = lambda: True
	failed_ready_xml.build_indices()

	element = etree.Element('page')
	monkeypatch.setattr(etree, 'iterparse', lambda source, events, tag: iter([('end', element)] * 25276))
	xml_limit = SourceMaker('xml_limit', 'xml_stream', str(xml_path), str(tmp_path / 'xml_limit'), 10, None, None)
	xml_limit._write_xml_page_as_md = lambda title, page: None
	xml_limit._create_markdown_from_xml()

	conversion_source = tmp_path / 'conversion_source'
	conversion_destination = tmp_path / 'conversion_destination'
	conversion_source.mkdir()
	conversion_destination.mkdir()
	(conversion_source / 'source.md').write_text('Source\n')
	conversion = SourceMaker('conversion', 'xml_stream', str(conversion_source), str(conversion_destination), 10, None, None)
	conversion._pdf_to_md = ReadyConverter
	conversion._pdf_extra = None
	conversion._build_child_at('conversion|source.md')
	conversion._build_child_at('conversion|source.md')
	(conversion_source / 'unavailable.md').write_text('Unavailable\n')
	conversion._pdf_to_md = NotReadyConverter
	conversion._build_child_at('conversion|unavailable.md')
	conversion._build_child_at('conversion|missing.md')

	with pytest.raises(ValueError):
		SourceMaker('invalid', 'invalid', None, str(tmp_path), 10, None, None)

	with pytest.raises(ValueError):
		SourceMaker('converter', 'pdf_mirror', str(src_path), str(dst_path), 10, None,
			{'class_name': 'Converter', 'path': str(tmp_path), 'extra_args': None})

	converter_path = tmp_path / 'invalid_converter.py'
	converter_path.write_text('class Converter:\n\tpass\n')
	with pytest.raises(ValueError):
		SourceMaker('converter', 'pdf_mirror', str(src_path), str(dst_path), 10, None,
			{'class_name': 'Converter', 'path': str(converter_path), 'extra_args': None})

	converter_path = tmp_path / 'converter.py'
	converter_path.write_text('from mercury.graph.evidence.formats import PdfToMarkdown\n\nclass Converter(PdfToMarkdown):\n\tdef run(self):\n\t\treturn True\n\n\tdef _ready(self):\n\t\treturn True\n')
	SourceMaker('converter', 'pdf_mirror', str(src_path), str(dst_path), 10, None,
		{'class_name': 'Converter', 'path': str(converter_path), 'extra_args': None})


def test_source_file(tmp_path):
	path = tmp_path / 'source.md'
	path.write_text('# Source\n')
	maker = SourceMaker('source', 'markdown_tree', None, str(tmp_path), 10, [], None)
	file = SourceFile('source|source.md', maker, str(path))

	with pytest.raises(ValueError):
		SourceFile('source|missing.md', maker, str(tmp_path / 'missing.md'))


def test_source_entity(tmp_path):
	""" Exercise SourceEntity delegation, metadata, and child management. """

	class InvalidContent:
		""" Content container that reports an invalid slice. """

		def __getitem__(self, span):
			""" Raise IndexError for every requested slice. """

			raise IndexError

	path = tmp_path / 'source.md'
	path.write_text('# Source\nBody\n')
	maker = SourceMaker('source', 'markdown_tree', None, str(tmp_path), 10, [], None)
	file = SourceFile('source|source.md', maker, str(path))

	assert file.lines(slice(0, 1)) is None
	assert file.line_slice(0, slice(0, 1)) is None
	file._content = ['# Source\n', 'Body\n']
	assert file.lines(slice(0, 1)) == ['# Source\n']
	assert file.line_slice(0, slice(0, 1)) == '#'
	assert file.line_slice(2, slice(0, 1)) is None
	file._content = InvalidContent()
	assert file.lines(slice(0, 1)) is None
	file._content = ['# Source\n', 'Body\n']

	entity = SourceEntity('source|source.md|header', file, 10, slice(0, 1), description = 'Source')
	entity.parent = file
	assert entity.content == ['# Source\n']
	assert entity.description == 'Source'
	assert entity.entity_type.value == 10
	assert entity.get_children_idx() is None
	assert entity.child('source|source.md|header|body') is None

	text = SourceEntity('source|source.md|text', file, 1, 1, slice(0, 4))
	text.parent = file
	assert text.content == 'Body'
	entity.add_child(text)
	assert entity.content == ''
	assert entity.get_children_idx() == ['source|source.md|text']
	assert entity.child('source|source.md|text') is text
	assert entity.child('source|source.md|header|missing') is None


# if __name__ == "__main__":
# 	pytest.main([__file__])
