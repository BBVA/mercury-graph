import pickle

import pytest

from mercury.graph.evidence import EvidenceGraph
from mercury.graph.evidence.agentic import AgenticRunInvalidRequest


class Downstream:
	"""Provides the Formalizer attributes used by EvidenceGraph connections."""

	def __init__(self):
		"""Creates distinct ontology placeholders for connection assertions."""
		self._entities = object()
		self._relation = object()
		self._known_id = object()


def _agentics(sources = 'source'):
	"""Returns a minimal complete downstream configuration."""
	return {'formalizer': 'main', 'id_nodes': 'nodes', 'id_edges': 'edges', 'is_same': 'same', 'sources': sources}


def _connected_graph(schema = 'graph', persistence = None, sources = 'source'):
	"""Returns an EvidenceGraph with all configured downstream tools attached."""
	conf = {'agentics': _agentics(sources)}
	if persistence is not None:
		conf['persistence'] = {'path': str(persistence)}
	graph = EvidenceGraph(schema = schema, extra_args = conf)
	formalizer = Downstream()
	tools = {
		'%s/formalizer_main' % graph.id: formalizer,
		'%s/formalizer_nodes' % graph.id: object(),
		'%s/agent_edges' % graph.id: object(),
		'%s/formalizer_same' % graph.id: object()
	}
	for source in sources if type(sources) is list else [sources]:
		tools['%s/source_%s' % (graph.id, source)] = object()
	graph.tools.update(tools)
	return graph, formalizer, tools


def test_evidence_graph_metadata_and_requests():
	"""Verifies construction, metadata, request dispatch, and request errors."""
	logger = []
	graph = EvidenceGraph(schema = 'any', extra_args = {'description': ['First line.', 'Second line.']}, logger = logger)

	assert type(graph) is EvidenceGraph
	assert graph.meta['state'] == graph.states.INITIAL.value
	assert graph.meta['description'] == 'First line.\nSecond line.'
	assert graph.meta['capabilities'][0]['function']['name'] == 'crawl_any'
	assert graph.dry_run({}) == {'status': 0, 'description': 'Valid request.'}

	graph.call['test'] = lambda index: index
	assert graph._run({'name': 'test', 'arguments': {'index': 'index'}})['message'] == 'index'

	with pytest.raises(AgenticRunInvalidRequest):
		graph._run({'name': 'missing', 'arguments': {'index': 'index'}})
	with pytest.raises(AgenticRunInvalidRequest):
		graph._run({'name': 'test', 'arguments': {}})

	assert len(logger) == 2


def test_evidence_graph_allows_schema_discovery_without_configuration():
	"""Verifies construction for callers that only need the class identity."""
	graph = EvidenceGraph(schema = None, extra_args = None)

	assert graph.id == 'evidence_graph'
	assert graph.states.__name__ == 'AlwaysReadyState'


def test_evidence_graph_pilots_empty_and_connected_graphs():
	"""Verifies one-step initialization and successful downstream connection."""
	empty = EvidenceGraph(schema = 'empty', extra_args = {})
	empty.pilot(empty.states.READY.value, just_once = True)
	assert empty.meta['state'] == empty.states.GRAPH_LOADED_OK.value
	empty.pilot(empty.states.READY.value)
	assert empty.meta['state'] == empty.states.ERR_BUILDING.value

	graph, formalizer, tools = _connected_graph()
	graph.pilot(graph.states.READY.value)

	assert graph.meta['state'] == graph.states.READY.value
	assert graph._formalizer is formalizer
	assert graph._entities is formalizer._entities
	assert graph._id_nodes is tools['%s/formalizer_nodes' % graph.id]
	assert graph._id_edges is tools['%s/agent_edges' % graph.id]
	assert graph._is_same is tools['%s/formalizer_same' % graph.id]
	assert graph._sources == [tools['%s/source_source' % graph.id]]


def test_evidence_graph_handles_connection_errors():
	"""Verifies missing and incomplete downstream configurations are rejected."""
	missing = EvidenceGraph(schema = 'missing', extra_args = {}, logger = [])
	assert missing._connect_downstream() is False

	invalid = EvidenceGraph(schema = 'invalid', extra_args = {'agentics': {}}, logger = [])
	assert invalid._connect_downstream() is False

	graph, _, tools = _connected_graph(schema = 'errors')
	for key in ['%s/formalizer_main' % graph.id, '%s/formalizer_nodes' % graph.id, '%s/agent_edges' % graph.id,
		'%s/formalizer_same' % graph.id, '%s/source_source' % graph.id]:
		missing_graph, _, _ = _connected_graph(schema = 'errors')
		del missing_graph.tools[key]
		assert missing_graph._connect_downstream() is False

	assert graph._connect_downstream() is True
	assert len(tools) == 5


def test_evidence_graph_persists_and_reloads_graph(tmp_path):
	"""Verifies persistence creates parent directories and reloads graph data."""
	path = tmp_path / 'graphs' / 'evidence.pkl'
	graph, formalizer, _ = _connected_graph(schema = 'persisted', persistence = path, sources = ['first', 'second'])
	graph.pilot(graph.states.READY.value)
	graph.close(True)

	assert path.is_file()
	with open(path, 'rb') as f:
		assert pickle.load(f).number_of_nodes() == 0
	assert graph._graph is graph._formalizer is graph._entities is graph._relation is graph._known_id is None

	reloaded, reloaded_formalizer, _ = _connected_graph(schema = 'persisted', persistence = path, sources = ['first', 'second'])
	reloaded.pilot(reloaded.states.READY.value)
	assert reloaded.meta['state'] == reloaded.states.READY.value
	assert reloaded._formalizer is reloaded_formalizer
	reloaded.close(False)


def test_evidence_graph_handles_initialization_errors_and_crawling():
	"""Verifies initialization failures and the current crawl availability contract."""
	logger = []
	broken = EvidenceGraph(schema = 'broken', extra_args = {'persistence': {'path': None}}, logger = logger)
	broken.pilot(broken.states.READY.value)
	assert broken.meta['state'] == broken.states.ERR_GRAPH_INIT.value
	broken.pilot(broken.states.READY.value)
	assert len(logger) == 2
	assert broken.crawl('source') is None

	graph, _, _ = _connected_graph(schema = 'crawl')
	assert graph.crawl('source') is None
	graph.pilot(graph.states.READY.value)
	with pytest.raises(NotImplementedError):
		graph.crawl('source')
