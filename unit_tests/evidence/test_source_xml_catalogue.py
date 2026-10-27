import sqlite3

import pytest

from mercury.graph.evidence.source_parts.xml_catalogue import XmlCatalogue, cluster_count
from mercury.graph.evidence.source_parts.xml_conversion import collision_key


def _catalogue(path, size, names):
	""" Returns a catalogue with the given file names as pages 0, 1, ..., in clusters of the given size. """

	catalogue = XmlCatalogue(str(path))
	catalogue.add_pages([(seq, seq // size + 1, name, collision_key(name)) for seq, name in enumerate(names)])
	catalogue.set_meta('cluster_size', size)
	catalogue.set_meta('total_pages', len(names))
	catalogue.close()

	return XmlCatalogue(str(path))


def test_cluster_tree(tmp_path):
	""" Clusters are numbered in page order. The tree is derived from the leaf numbers, and children are queried one cluster at a time. """

	names = ['page%d.md' % i for i in range(5)]
	catalogue = _catalogue(tmp_path / 'catalogue.sqlite', 2, names)

	assert cluster_count(5, 2, 1) == 3
	assert catalogue.depth == 2
	assert catalogue.children([]) == ['2:1', '2:2']
	assert catalogue.children([1]) == ['1:1', '1:2']
	assert catalogue.children([2]) == ['1:3']
	assert catalogue.children([1, 2]) == ['page2.md', 'page3.md']

	assert catalogue.locate(['2:2', '1:3', 'page4.md']) == ([2, 3], 'page4.md', 3)
	assert catalogue.locate(['2:1', '1:2', 'page2.md', 'extra']) == ([1, 2], 'page2.md', 3)
	assert catalogue.locate(['2:1', '1:2']) == ([1, 2], None, 2)
	assert catalogue.locate(['2:2', '1:3', 'missing.md']) is None
	assert catalogue.locate(['2:1', '1:3', 'page4.md']) is None
	assert catalogue.locate(['3:1']) is None
	assert catalogue.locate(['2:9']) is None
	assert catalogue.locate(['0:1']) is None
	catalogue.close()


def test_small_catalogue_has_no_clusters(tmp_path):
	""" When the pages fit in one cluster, the SourceMaker itself holds the file names. """

	catalogue = _catalogue(tmp_path / 'catalogue.sqlite', 5, ['One.md', 'Two.md'])

	assert catalogue.depth == 0
	assert catalogue.children([]) == ['One.md', 'Two.md']
	assert catalogue.locate(['Two.md']) == ([], 'Two.md', 1)
	assert catalogue.locate(['Missing.md']) is None
	catalogue.close()


def test_recluster(tmp_path):
	""" Changing the cluster size regroups the pages, keeps their names, and stores the new size. """

	names = ['page%d.md' % i for i in range(5)]
	catalogue = _catalogue(tmp_path / 'catalogue.sqlite', 2, names)

	catalogue.recluster(3)

	assert catalogue.size == 3
	assert catalogue.depth == 1
	assert catalogue.children([]) == ['1:1', '1:2']
	assert catalogue.children([2]) == ['page3.md', 'page4.md']
	assert catalogue.locate(['1:2', 'page4.md']) == ([2], 'page4.md', 2)
	catalogue.close()

	assert XmlCatalogue(str(tmp_path / 'catalogue.sqlite')).size == 3


def test_duplicate_key_is_rejected(tmp_path):
	""" Two pages whose file names clash on a case-insensitive file system cannot both be stored. """

	catalogue = XmlCatalogue(str(tmp_path / 'catalogue.sqlite'))
	catalogue.add_pages([(0, 1, 'Iphone.md', collision_key('Iphone.md'))])

	with pytest.raises(sqlite3.IntegrityError):
		catalogue.add_pages([(1, 1, 'IPhone.md', collision_key('IPhone.md'))])

	assert catalogue.count_pages() == 1
	assert catalogue.name_for(collision_key('IPhone.md')) == 'Iphone.md'
	catalogue.close()


def test_build_state(tmp_path):
	""" Completed batches and the ready flag are stored, and reset clears them. """

	catalogue = XmlCatalogue(str(tmp_path / 'catalogue.sqlite'))
	assert not catalogue.index_complete()
	assert not catalogue.is_ready()

	catalogue.mark_done(0, 2)
	catalogue.mark_done(1, 1)
	catalogue.mark_done(1, 1)

	assert catalogue.done_batches() == {0, 1}
	assert catalogue.done_summary() == (2, 3)

	catalogue.set_meta('ready', 1)
	assert catalogue.is_ready()

	catalogue.reset()
	assert not catalogue.is_ready()
	assert catalogue.done_summary() == (0, 0)
	catalogue.close()
