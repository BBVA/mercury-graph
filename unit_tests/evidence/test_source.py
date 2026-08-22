import pytest

import mercury.graph.evidence.source as source_module

from mercury.graph.evidence import Source
from mercury.graph.evidence.agentic import AgenticRunInvalidRequest
from mercury.graph.evidence.source_parts import SourceEntity, SourceMaker, SourceState


def _conf(path):
	""" Return a minimal markdown Source configuration for path. """
	return {'type': 'markdown_tree', 'src_path': None, 'dst_path': str(path)}


def test_source(tmp_path):
	""" Exercise Source initialization, piloting, and capability calls. """
	(tmp_path / 'source.md').write_text('# Source\n')
	conf = _conf(tmp_path)
	s = Source(schema = 'any', extra_args = conf)
	assert type(s) is Source
	assert Source(schema = 'any', extra_args = conf).conf == conf
	assert s.state_name(0) == 'INITIAL'

	s.pilot(100)
	request = {'name': 'children_by_idx_any', 'arguments': {'index': 'any'}}
	assert s.run(request)['message'] == ['any|source.md']
	assert s._dry_run(request) == {'status': 0, 'description': 'Valid request.'}
	assert type(s.meta) == dict

	s._meta_['state'] = -1
	s.pilot(100)


def test_source_run_errors_and_close(tmp_path):
	""" Exercise invalid calls, logging, and resource cleanup. """
	s = Source(schema = 'any', extra_args = _conf(tmp_path), logger = [])

	with pytest.raises(AgenticRunInvalidRequest):
		s._run({'name': 'missing', 'function': 'missing', 'arguments': {'index': 'any'}})

	with pytest.raises(AgenticRunInvalidRequest):
		s._run({'name': 'children_by_idx_any', 'function': 'children_by_idx_any', 'arguments': {}})

	s._maker = object()
	s._chroma = object()
	s.close(False)
	assert s._maker is None
	assert s._chroma is None
	assert len(s.logger) == 2


def test_source_pilot_outcomes(tmp_path, monkeypatch):
	""" Exercise every Source piloting transition and failure outcome. """
	class DummyMaker:
		""" Configurable SourceMaker replacement used to isolate piloting. """

		build_result = True

		def __init__(self, index, typ, src, dst, size, extensions, pdf):
			self.state = SourceState.INITIAL.value

		def build_indices(self):
			""" Return the configured index-building result. """
			self.state = SourceState.MAKER_READY_OK.value
			return self.build_result

	monkeypatch.setattr(source_module, 'SourceMaker', DummyMaker)

	just_once = Source(schema = 'just_once', extra_args = _conf(tmp_path))
	just_once.pilot(100, just_once = True)
	assert just_once.meta['state'] == SourceState.MAKER_INIT_OK.value
	just_once.pilot(100, just_once = True)
	assert just_once.meta['state'] == SourceState.MAKER_READY_OK.value

	failed_indices = Source(schema = 'failed_indices', extra_args = _conf(tmp_path))
	DummyMaker.build_result = False
	failed_indices.pilot(100)
	assert failed_indices.meta['state'] == SourceState.ERR_MAKER_INDEX.value

	failed_db = Source(schema = 'failed_db', extra_args = _conf(tmp_path))
	DummyMaker.build_result = True
	failed_db._setup_chroma_db = lambda: False
	failed_db.pilot(100)
	assert failed_db.meta['state'] == SourceState.ERR_DB_SETUP.value

	failed_maker = Source(schema = 'failed_maker', extra_args = {})
	failed_maker.pilot(100)
	assert failed_maker.meta['state'] == SourceState.ERR_MAKER_INIT.value


def test_source_tree_delegation(tmp_path):
	""" Exercise Source tree delegation and serialized object representations. """
	(tmp_path / 'source.md').write_text('# Source\nText\n')
	s = Source(schema = 'tree', extra_args = _conf(tmp_path), logger = [])
	assert s.get_children_idx() is None
	assert s.child('tree') is None

	s.pilot(100)
	assert s.get_children_idx() == ['tree|source.md']
	assert s.get_children_idx('missing') is None
	assert s.child('missing') is None
	assert s.child('tree')['type'] == 'object'
	assert s.child('tree|source.md')['type'] == 'object'

	class InvalidMaker:
		""" SourceMaker replacement that cannot provide a SourceFile. """

		state = SourceState.MAKER_READY_OK.value

		def get_children_idx(self, index):
			""" Return the index of an unavailable SourceFile. """
			return index

		def child(self, index):
			""" Return an invalid value for a SourceFile index. """
			return index

	s._maker = InvalidMaker()
	assert s.get_children_idx('tree|invalid') is None
	s._maker = SourceMaker('tree', 'markdown_tree', None, str(tmp_path), 10, None, None)
	s._maker.build_indices()

	file_index = 'tree|source.md'
	entity_index = s.get_children_idx(file_index)[0]
	entity = s._maker.child(file_index).child(entity_index)
	assert type(entity) is SourceEntity
	assert s.child(entity_index)['description'] == entity.description

	leaf_index = entity.get_children_idx()[0]
	leaf = entity.child(leaf_index)
	assert s.child(leaf_index) == {'type': str(leaf.entity_type), 'content': 'Source'}
	assert s.get_children_idx(leaf_index) is None
	assert s.child('%s|missing' % entity_index) is None
	assert len(s.logger) == 3


def test_source_chroma_setup(tmp_path, monkeypatch):
	""" Exercise Chroma client and collection setup outcomes. """
	conf = _conf(tmp_path)
	s = Source(schema = 'chroma', extra_args = conf, logger = [])
	assert s._setup_chroma_db() is True

	s.conf['chroma_path'] = str(tmp_path / 'chroma')
	s.conf['chroma_descriptions_collection_name'] = 'descriptions'
	s.conf['chroma_chunks_collection_name'] = 'chunks'
	monkeypatch.setattr(source_module.chroma, 'PersistentClient', lambda path: (_ for item in ()).throw(RuntimeError()))
	assert s._setup_chroma_db() is False

	class Client:
		""" Chroma client that fails while creating collections. """

		def get_or_create_collection(self, name):
			""" Raise an error while creating a collection. """
			raise RuntimeError()

	monkeypatch.setattr(source_module.chroma, 'PersistentClient', lambda path: Client())
	assert s._setup_chroma_db() is False

	class ReadyClient:
		""" Chroma client that records successful collection creation. """

		def get_or_create_collection(self, name):
			""" Return a collection object for name. """
			return {'name': name}

	monkeypatch.setattr(source_module.chroma, 'PersistentClient', lambda path: ReadyClient())
	assert s._setup_chroma_db() is True
	assert s._chroma_descr == {'name': 'descriptions'}
	assert s._chroma_chunks == {'name': 'chunks'}
	assert len(s.logger) == 2


# if __name__ == "__main__":
# 	pytest.main([__file__])
