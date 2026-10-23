import pickle

import pandas as pd
import pytest
from mercury.graph.evidence.agentic import AgenticRunFailed

from mercury.graph.evidence import AgenticGraph, EvidenceGraph
from mercury.graph.evidence.agentic import AgenticRunInvalidRequest


class Downstream:
	"""Provides the Formalizer attributes used by EvidenceGraph connections."""

	def __init__(self, ontology = None):
		"""Creates an ontology placeholder for connection assertions, or keeps the given ontology."""
		self._ontology = object() if ontology is None else ontology


def _agentics(sources = 'source'):
	"""Returns a minimal complete downstream configuration."""
	return {'formalizer': 'main', 'id_nodes': 'nodes', 'id_edges': 'edges', 'is_same': 'same', 'sources': sources}


def _connected_graph(schema = 'graph', persistence = None, sources = 'source', ontology = None, logger = None, **extra_args):
	"""Returns an EvidenceGraph with all configured downstream tools attached."""
	conf = dict(extra_args, agentics = _agentics(sources))
	if persistence is not None:
		conf['persistence'] = {'path': str(persistence)}
	graph = EvidenceGraph(schema = schema, extra_args = conf, logger = logger)
	formalizer = Downstream(ontology)
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
	assert graph.meta['capabilities'][0]['function']['name'] == 'crawl_source_any'
	assert graph.dry_run({}) == {'status': 0, 'description': 'Valid request.'}

	graph.call['test'] = lambda args: args['index']
	assert graph._run({'name': 'test', 'arguments': {'index': 'index'}})['message'] == 'index'

	with pytest.raises(AgenticRunInvalidRequest):
		graph._run({'name': 'missing', 'arguments': {'index': 'index'}})
	with pytest.raises(KeyError, match = 'index'):
		graph._run({'name': 'test', 'arguments': {}})

	assert len(logger) == 1


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
	assert graph._ontology is formalizer._ontology
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
	assert graph._graph is graph._formalizer is graph._ontology is None

	reloaded, reloaded_formalizer, _ = _connected_graph(schema = 'persisted', persistence = path, sources = ['first', 'second'])
	reloaded.pilot(reloaded.states.READY.value)
	assert reloaded.meta['state'] == reloaded.states.READY.value
	assert reloaded._formalizer is reloaded_formalizer
	reloaded.close(False)


def test_evidence_graph_handles_initialization_errors_and_crawling():
	"""Verifies initialization failures and rejection of invalid crawl arguments."""
	logger = []
	broken = EvidenceGraph(schema = 'broken', extra_args = {'persistence': {'path': None}}, logger = logger)
	broken.pilot(broken.states.READY.value)
	assert broken.meta['state'] == broken.states.ERR_GRAPH_INIT.value
	broken.pilot(broken.states.READY.value)
	assert len(logger) == 2
	with pytest.raises(AgenticRunFailed):
		broken.crawl('source')

	graph, _, _ = _connected_graph(schema = 'crawl')
	with pytest.raises(AgenticRunFailed):
		graph.crawl('source')
	graph.pilot(graph.states.READY.value)
	with pytest.raises(AgenticRunFailed):
		graph.crawl('source')


def _csv(directory, name, rows):
	"""Writes rows (a list of dicts) as a tab separated .csv file in directory and returns it as a file of a configuration."""
	path = directory / ('%s.csv' % name)
	pd.DataFrame(rows).to_csv(path, index = False, sep = '\t')
	return {'type': 'csv', 'path': str(path)}


def _school_ontology(directory):
	"""Returns a ready ontology of persons, students, projects and schools, with relationships between them."""
	entities = ['person', 'person|student', 'person|teacher', 'project', 'organization', 'organization|school']
	relations = [('works_on', 'person', 'project'), ('works_on|leads', 'person', 'project'), ('teaches_at', 'person|teacher', 'organization|school')]
	ontology = AgenticGraph(schema = 'ontology', extra_args = {
		'nodes': _csv(directory, 'entities', [{'id': i, 'definition': 'A %s.' % i} for i in entities]),
		'edges': _csv(directory, 'relationships', [{'id': i, 'src': s, 'dst': d, 'definition': 'To %s.' % i} for i, s, d in relations])
	})
	ontology.pilot(ontology.states.READY.value)
	return ontology


def _seeded_graph(directory, nodes, edges, logger = None, persistence = None):
	"""Returns an EvidenceGraph whose initial graph has the given node ids and (src, dst, relation, id) edges."""
	initial_nodes = _csv(directory, 'initial_nodes', [{'id': i} for i in nodes])
	initial_edges = _csv(directory, 'initial_edges', [{'src': s, 'dst': d, 'relation': r, 'id': i} for s, d, r, i in edges])
	graph, _, _ = _connected_graph(schema = 'seeded', persistence = persistence, ontology = _school_ontology(directory), logger = logger,
								   initial_nodes = initial_nodes, initial_edges = initial_edges)
	return graph


VALID_NODES = ['person|student|Noah', 'person|teacher|Elena', 'project|Helios', 'organization|school|Riverside']
VALID_EDGES = [('person|student|Noah', 'project|Helios', 'works_on|leads', 'noah_helios'),
			   ('person|teacher|Elena', 'organization|school|Riverside', 'teaches_at', 'elena_riverside')]


def test_evidence_graph_loads_its_initial_graph(tmp_path):
	"""Without a pickle, the EvidenceGraph starts from its initial graph, validated against the ontology."""
	graph = _seeded_graph(tmp_path, VALID_NODES, VALID_EDGES)

	graph.pilot(graph.states.READY.value)

	assert graph.meta['state'] == graph.states.READY.value
	assert set(graph._graph.networkx.nodes) == set(VALID_NODES)
	assert graph._graph.networkx.edges['person|student|Noah', 'project|Helios', 'noah_helios'] == {'relation': 'works_on|leads'}


def test_evidence_graph_ignores_its_initial_graph_when_there_is_a_pickle(tmp_path):
	"""The initial graph is only loaded when the pickle does not exist."""
	path = tmp_path / 'graphs' / 'evidence.pkl'
	empty, _, _ = _connected_graph(schema = 'seeded', persistence = path)
	empty.pilot(empty.states.READY.value)
	empty.close(True)

	graph = _seeded_graph(tmp_path, VALID_NODES, VALID_EDGES, persistence = path)
	graph.pilot(graph.states.READY.value)

	assert graph.meta['state'] == graph.states.READY.value
	assert graph._graph.networkx.number_of_nodes() == 0


def test_evidence_graph_rejects_an_invalid_initial_graph_without_saving_it(tmp_path):
	"""An initial graph that does not match the ontology leaves the EvidenceGraph in ERR_BUILDING, logs every problem and is not
	saved, so that the next start does not load it from the pickle.
	"""
	logger = []
	path = tmp_path / 'graphs' / 'evidence.pkl'
	graph = _seeded_graph(tmp_path, VALID_NODES + ['vehicle|Car'], VALID_EDGES + [('person|student|Noah', 'project|Helios', 'drives', 'x')],
						  logger = logger, persistence = path)

	graph.pilot(graph.states.READY.value)
	graph.close(True)

	errors = [event['error'] for event in logger if event['type'] == 'error']
	assert graph.meta['state'] == graph.states.ERR_BUILDING.value
	assert len(errors) == 2
	assert any('vehicle|Car' in error for error in errors) and any('drives' in error for error in errors)
	assert not path.exists()
