import json, os
from concurrent.futures import Future
from unittest.mock import MagicMock, Mock

import pytest

from mercury.graph.evidence.source_parts import xml_build
from mercury.graph.evidence.source_parts.xml_build import build_directory, build_xml_markdown, open_xml_catalogue


NS = 'http://www.mediawiki.org/xml/export-0.11/'


def _write_export(path, titles):
	""" Writes a MediaWiki export with one page per title, laid out like the real dumps. """

	page = '<page><title>%s</title><revision><text xml:space="preserve">Text of %s</text></revision></page>\n'
	pages = ''.join(page % (title, title) for title in titles)
	head = '<?xml version="1.0" encoding="UTF-8"?>\n<mediawiki xmlns="%s" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
	path.write_text(head % NS + '<siteinfo><sitename>Test</sitename></siteinfo>\n' + pages + '</mediawiki>\n', encoding = 'utf-8')


def _manifest(dst):
	""" Returns the manifest of the build of a destination. """

	with open('%s/manifest.json' % build_directory(str(dst)), encoding = 'utf-8') as f:
		return json.load(f)


def _forbid_conversion(monkeypatch):
	""" Makes any conversion of a batch fail, to show that a build is reused. """

	forbidden = Mock(side_effect = AssertionError('The XML export must not be converted again.'))
	monkeypatch.setattr(xml_build, 'convert_batch', forbidden)


def test_index_records_batches_that_tile_the_pages(tmp_path):
	""" The export is indexed once. Its batches are contiguous byte ranges with the expected pages, and the root namespaces are kept. """

	src = tmp_path / 'export.xml'
	_write_export(src, ['One', 'Two', 'Three', 'Four', 'Five'])
	data = src.read_bytes()

	assert build_xml_markdown(str(src), str(tmp_path / 'out'), 4, 2, 1)

	manifest = _manifest(tmp_path / 'out')
	batches = manifest['batches']

	assert manifest['total_pages'] == 5
	assert [batch['pages'] for batch in batches] == [2, 2, 1]
	assert [batch['first'] for batch in batches] == [0, 2, 4]
	assert batches[0]['start'] == data.index(b'<page>')
	assert batches[0]['end'] == batches[1]['start']
	assert batches[1]['end'] == batches[2]['start']
	assert batches[2]['end'] == data.index(b'</mediawiki>')
	assert 'xmlns="%s"' % NS in manifest['root']
	assert 'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"' in manifest['root']

	for batch in batches:
		section = data[batch['start']:batch['end']]
		assert section.lstrip().startswith(b'<page>')
		assert section.rstrip().endswith(b'</page>')


def test_single_and_parallel_workers_write_the_same_markdown(tmp_path):
	""" One worker and two worker processes write the same Markdown files, one file per page. """

	src = tmp_path / 'export.xml'
	_write_export(src, ['One', 'Two', 'Three', 'Four', 'Five'])

	assert build_xml_markdown(str(src), str(tmp_path / 'single'), 4, 1, 1)
	assert build_xml_markdown(str(src), str(tmp_path / 'parallel'), 4, 1, 2)

	names = sorted(os.listdir(str(tmp_path / 'single')))

	assert names == sorted(os.listdir(str(tmp_path / 'parallel')))
	assert len(names) == 5
	for name in names:
		assert (tmp_path / 'single' / name).read_bytes() == (tmp_path / 'parallel' / name).read_bytes()


def test_failed_batch_is_not_ready_and_the_next_run_resumes(tmp_path, monkeypatch):
	""" A failed batch leaves the build not ready. The next run converts only the batches that are not recorded as done. """

	src = tmp_path / 'export.xml'
	_write_export(src, ['One', 'Two', 'Three', 'Four', 'Five'])
	dst = str(tmp_path / 'out')
	real_convert = xml_build.convert_batch
	calls = []
	failing = {'id': 1}

	def tracked(source, destination, root, batch):
		calls.append(batch['id'])
		if batch['id'] == failing['id']:
			raise RuntimeError('Simulated failure.')

		return real_convert(source, destination, root, batch)

	monkeypatch.setattr(xml_build, 'convert_batch', tracked)

	assert not build_xml_markdown(str(src), dst, 4, 2, 1)
	assert calls == [0, 1]
	assert open_xml_catalogue(str(src), dst, 4) is None

	failing['id'] = None
	del calls[:]

	assert build_xml_markdown(str(src), dst, 4, 2, 1)
	assert calls == [1, 2]

	catalogue = open_xml_catalogue(str(src), dst, 4)
	assert catalogue.done_summary() == (3, 5)
	catalogue.close()
	assert len(os.listdir(dst)) == 5


@pytest.mark.parametrize('pages_per_batch', [2, 10])
@pytest.mark.parametrize('titles', [['Alpha', 'Alpha '], ['Iphone', 'IPhone'], ['a/b', 'a%2Fb']])
def test_colliding_file_names_stop_the_build_before_any_conversion(tmp_path, monkeypatch, titles, pages_per_batch):
	""" Titles that would be written to the same file are found while indexing. No page is converted and nothing is published. """

	src = tmp_path / 'export.xml'
	_write_export(src, ['One'] + titles)
	dst = str(tmp_path / 'out')
	calls = []
	monkeypatch.setattr(xml_build, 'convert_batch', lambda *args: calls.append(args))

	assert not build_xml_markdown(str(src), dst, 4, pages_per_batch, 1)
	assert calls == []
	assert os.listdir(dst) == []
	assert open_xml_catalogue(str(src), dst, 4) is None


def test_unusable_exports_are_not_built(tmp_path):
	""" An export without pages, without a title, that is not well formed, or that is missing, is not built. """

	empty = tmp_path / 'empty.xml'
	empty.write_text('<mediawiki xmlns="%s"></mediawiki>' % NS, encoding = 'utf-8')
	untitled = tmp_path / 'untitled.xml'
	untitled.write_text('<mediawiki xmlns="%s"><page><revision><text>Text</text></revision></page></mediawiki>' % NS, encoding = 'utf-8')
	broken = tmp_path / 'broken.xml'
	broken.write_text('<mediawiki xmlns="%s"><page>' % NS, encoding = 'utf-8')

	for index, src in enumerate([empty, untitled, broken, tmp_path / 'missing.xml']):
		dst = str(tmp_path / ('out%d' % index))

		assert not build_xml_markdown(str(src), dst, 4, 2, 1)
		assert open_xml_catalogue(str(src), dst, 4) is None


def test_changed_source_is_converted_again(tmp_path):
	""" A build is only reused while the XML source is the file it was built from. """

	src = tmp_path / 'export.xml'
	_write_export(src, ['One', 'Two'])
	dst = str(tmp_path / 'out')
	assert build_xml_markdown(str(src), dst, 4, 10, 1)

	catalogue = open_xml_catalogue(str(src), dst, 4)
	assert catalogue is not None
	catalogue.close()

	_write_export(src, ['One', 'Two', 'Three'])
	assert open_xml_catalogue(str(src), dst, 4) is None

	assert build_xml_markdown(str(src), dst, 4, 10, 1)
	assert len(os.listdir(dst)) == 3


def test_completed_build_is_reused_and_regrouped_without_conversion(tmp_path, monkeypatch):
	""" A complete build is opened without converting the export. Opening it with another cluster size only regroups the pages. """

	src = tmp_path / 'export.xml'
	_write_export(src, ['One', 'Two', 'Three'])
	dst = str(tmp_path / 'out')
	assert not build_xml_markdown(str(src), dst, 1, 2, 1)
	assert build_xml_markdown(str(src), dst, 2, 2, 1)

	_forbid_conversion(monkeypatch)

	catalogue = open_xml_catalogue(str(src), dst, 2)
	assert catalogue.depth == 1
	assert catalogue.children([]) == ['1:1', '1:2']
	assert catalogue.children([2]) == ['Three.md']
	catalogue.close()

	catalogue = open_xml_catalogue(str(src), dst, 3)
	assert catalogue.size == 3
	assert catalogue.depth == 0
	assert catalogue.children([]) == ['One.md', 'Two.md', 'Three.md']
	catalogue.close()

	assert open_xml_catalogue(str(src), dst, 1) is None


def test_parallel_worker_failure_cancels_pending_batches_and_can_resume(tmp_path, monkeypatch):
	""" A failed worker cancels queued work and leaves its batches available for a later successful build. """

	src = tmp_path / 'export.xml'
	_write_export(src, ['One', 'Two'])
	dst = str(tmp_path / 'out')
	failed = Future()
	failed.set_exception(RuntimeError('Simulated worker failure.'))
	pending = Future()
	pool = MagicMock()
	pool.__enter__.return_value = pool
	pool.submit.side_effect = [failed, pending]

	with monkeypatch.context() as patch:
		patch.setattr(xml_build, 'ProcessPoolExecutor', Mock(return_value = pool))
		patch.setattr(xml_build, 'wait', Mock(return_value = ({failed}, {pending})))
		assert not build_xml_markdown(str(src), dst, 4, 1, 2)

	assert pending.cancelled()
	assert open_xml_catalogue(str(src), dst, 4) is None
	assert build_xml_markdown(str(src), dst, 4, 1, 1)

	catalogue = open_xml_catalogue(str(src), dst, 4)
	assert catalogue.done_summary() == (2, 2)
	catalogue.close()
	assert sorted(os.listdir(dst)) == ['One.md', 'Two.md']


def test_incorrect_worker_page_count_does_not_complete_the_batch(tmp_path, monkeypatch, caplog):
	""" A worker reporting fewer pages than indexed cannot publish the build, and the next run retries that batch. """

	src = tmp_path / 'export.xml'
	_write_export(src, ['One'])
	dst = str(tmp_path / 'out')

	with monkeypatch.context() as patch:
		patch.setattr(xml_build, 'convert_batch', Mock(return_value = 0))
		assert not build_xml_markdown(str(src), dst, 4, 1, 1)

	assert 'Batch 0 converted 0 pages, expected 1.' in caplog.text
	assert open_xml_catalogue(str(src), dst, 4) is None
	assert build_xml_markdown(str(src), dst, 4, 1, 1)
	assert (tmp_path / 'out' / 'One.md').read_text(encoding = 'utf-8') == '# One\n\nText of One\n'


@pytest.mark.parametrize('completed, indexed, changed, message', [
	([], True, False, 'Only 0 of 1 batches are complete, with 0 of 1 pages.'),
	([(0, 0)], True, False, 'Only 1 of 1 batches are complete, with 0 of 1 pages.'),
	([(0, 1)], False, False, 'The index holds 0 pages, expected 1.'),
	([(0, 1)], True, True, 'The XML source changed while it was converted.')
])
def test_publication_rejects_inconsistent_or_changed_builds(tmp_path, completed, indexed, changed, message):
	""" Publication requires every batch and page, a matching catalogue count, and an unchanged XML source. """

	src = tmp_path / 'export.xml'
	_write_export(src, ['One'])
	manifest = {'source': xml_build._stamp(str(src)), 'total_pages': 1, 'batches': [{'id': 0, 'pages': 1}]}
	catalogue = xml_build.XmlCatalogue(str(tmp_path / 'catalogue.sqlite'))

	try:
		if indexed:
			catalogue.add_pages([(0, 1, 'One.md', 'one.md')])
		for batch, pages in completed:
			catalogue.mark_done(batch, pages)
		if changed:
			_write_export(src, ['One', 'Two'])

		with pytest.raises(xml_build.XmlBuildError) as error:
			xml_build._publish(str(src), manifest, catalogue)

		assert str(error.value) == message
		assert not catalogue.is_ready()
	finally:
		catalogue.close()


def test_indexer_flush_is_idempotent_without_pending_pages(tmp_path):
	""" Flushing before indexing or after the final batch leaves the stored page count unchanged. """

	src = tmp_path / 'export.xml'
	_write_export(src, ['One'])
	catalogue = xml_build.XmlCatalogue(str(tmp_path / 'catalogue.sqlite'))
	indexer = xml_build._PageIndexer(catalogue, 4, 1)

	try:
		indexer._flush()
		assert catalogue.count_pages() == 0
		indexer.feed(src.read_bytes(), True)
		indexer._flush()
		assert catalogue.count_pages() == 1
		assert catalogue.names(1) == ['One.md']
	finally:
		catalogue.close()


def test_indexer_reports_constraint_failure_without_a_matching_file_name(tmp_path):
	""" An index constraint violation still produces an XML build error when no filename collision explains it. """

	src = tmp_path / 'export.xml'
	_write_export(src, ['New'])
	catalogue = xml_build.XmlCatalogue(str(tmp_path / 'catalogue.sqlite'))
	catalogue.add_pages([(0, 1, 'Existing.md', 'existing.md')])
	indexer = xml_build._PageIndexer(catalogue, 4, 1)

	try:
		with pytest.raises(xml_build.XmlBuildError, match = 'Two pages would be written to the same file.'):
			indexer.feed(src.read_bytes(), True)

		assert catalogue.count_pages() == 1
		assert catalogue.names(1) == ['Existing.md']
	finally:
		catalogue.close()
