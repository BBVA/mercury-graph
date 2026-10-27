import os

import pytest

from cli.xml_to_markdown import main
from mercury.graph.evidence.source_parts import SourceMaker, xml_build


def test_cli_builds_the_output_that_a_source_reuses(tmp_path, monkeypatch):
	""" The command line converts the export into a ready build, and a SourceMaker reuses that build without converting again. """

	src = tmp_path / 'export.xml'
	src.write_text('<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">'
		'<page><title>One</title><revision><text>First</text></revision></page>'
		'<page><title>Two</title><revision><text>Second</text></revision></page>'
		'<page><title>Three</title><revision><text>Third</text></revision></page></mediawiki>', encoding = 'utf-8')
	dst = tmp_path / 'out'

	assert main(['--src', str(src), '--dst', str(dst), '--workers', '1', '--pages-per-batch', '2']) == 0
	assert sorted(os.listdir(str(dst))) == ['One.md', 'Three.md', 'Two.md']

	monkeypatch.setattr(xml_build, 'convert_batch', lambda *args: pytest.fail('The export must not be converted again.'))
	maker = SourceMaker('xml', 'xml_stream', str(src), str(dst), xml_build.DEFAULT_CLUSTER_SIZE, None, None)

	assert maker.build_indices() is True
	assert maker.get_children_idx('xml') == ['xml|One.md', 'xml|Two.md', 'xml|Three.md']


def test_cli_reports_a_build_that_is_not_ready(tmp_path):
	""" A missing export is reported by the exit code, not by an exception. """

	assert main(['--src', str(tmp_path / 'missing.xml'), '--dst', str(tmp_path / 'out')]) == 1


def test_cli_rejects_invalid_options(tmp_path):
	""" Workers and pages per batch must be at least one. """

	with pytest.raises(SystemExit):
		main(['--src', str(tmp_path / 'export.xml'), '--dst', str(tmp_path / 'out'), '--workers', '0'])

	with pytest.raises(SystemExit):
		main(['--src', str(tmp_path / 'export.xml'), '--dst', str(tmp_path / 'out'), '--pages-per-batch', '0'])
