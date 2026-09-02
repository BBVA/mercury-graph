import pickle

import pandas as pd
import pytest
import networkx as nx

from mercury.graph.evidence import AgenticGraph, MultiGraph
from mercury.graph.evidence.agentic import AgenticRunInvalidRequest


def test_multi_graph_builds_directed_multigraph():
	""" Verifies that MultiGraph preserves edge keys and attributes from pandas data. """
	edges = pd.DataFrame([
		{'from': 'a', 'to': 'b', 'edge_id': 'first', 'relation': 'owns'},
		{'from': 'a', 'to': 'b', 'edge_id': 'second', 'relation': 'manages'}
	])
	nodes = pd.DataFrame([
		{'edge_id': 'a', 'kind': 'person'},
		{'edge_id': 'b', 'kind': 'company'}
	])
	keys = {'src': 'from', 'dst': 'to', 'id': 'edge_id', 'directed': True}

	graph = MultiGraph(data = edges, keys = keys, nodes = nodes)

	assert type(graph.networkx) is nx.MultiDiGraph
	assert graph.number_of_nodes == 2
	assert graph.number_of_edges == 2
	assert graph.networkx.edges['a', 'b', 'first'] == {'relation': 'owns'}
	assert graph.networkx.nodes['a'] == {'kind': 'person'}
	assert graph.edges_colnames == ['src', 'dst', 'key', 'relation']


def test_multi_graph_rejects_undirected_graphs():
	""" Verifies that MultiGraph only accepts directed graph definitions. """
	edges = pd.DataFrame([{'src': 'a', 'dst': 'b', 'id': 'edge'}])

	with pytest.raises(NotImplementedError):
		MultiGraph(data = edges, keys = {'directed': False})


def test_agentic_graph_metadata_and_requests():
	""" Verifies metadata, request dispatch, and errors before the graph is ready. """
	logger = []
	graph = AgenticGraph(schema = 'ontology', extra_args = {'description': ['First line.', 'Second line.']}, logger = logger)
	children_name = 'children_by_idx_ontology'
	node_name = 'node_by_idx_ontology'

	assert graph.meta['state'] == 0
	assert graph.meta['description'] == 'First line.\nSecond line.'
	assert [capability['function']['name'] for capability in graph.meta['capabilities']] == [children_name, node_name]
	assert graph.dry_run({'anything': True}) == {'status': 0, 'description': 'Valid request.'}
	assert graph.get_children_idx() is None
	assert graph.child('ontology') is None

	with pytest.raises(AgenticRunInvalidRequest):
		graph._run({'name': 'unknown', 'function': 'unknown', 'arguments': {'index': 'ontology'}})

	with pytest.raises(AgenticRunInvalidRequest):
		graph._run({'name': children_name, 'function': children_name, 'arguments': {}})

	assert len(logger) == 4
	assert logger[-2]['error'] == 'AgenticGraph does not have a function named "unknown".'
	assert logger[-1]['error'] == 'AgenticGraph function "children_by_idx_ontology" requires an "index" argument.'


def test_agentic_graph_creates_and_queries_default_graph():
	""" Verifies default graph creation, one-step piloting, and index query results. """
	graph = AgenticGraph(schema = 'empty', extra_args = {'description': 'Empty graph.'})

	graph.pilot(graph.states.READY.value, just_once = True)
	assert graph.meta['state'] == graph.states.GRAPH_LOADED_OK.value

	graph.pilot(graph.states.READY.value)
	assert graph.meta['state'] == graph.states.READY.value
	assert graph.get_children_idx() == []
	assert graph.get_children_idx('wrong') is None
	assert graph.get_children_idx('empty|missing') is None
	assert graph.child('wrong') is None
	assert graph.child('empty|missing') is None
	assert graph._run({'name': 'children_by_idx_empty', 'arguments': {'index': 'empty'}}) == {'finish_reason': 'stop', 'message': []}

	graph.close(False)
	assert graph._graph is None


def test_agentic_graph_loads_files_and_persists_graph(tmp_path):
	""" Verifies CSV and pickle initialization, hierarchical queries, and persistence. """
	nodes = pd.DataFrame([
		{'id': 'animal|mammal', 'label': 'Mammal'},
		{'id': 'animal|bird', 'label': 'Bird'}
	])
	edges = pd.DataFrame([{'source': 'animal|mammal', 'target': 'animal|bird', 'id': 'related', 'weight': 2}])
	nodes_path = tmp_path / 'nodes.csv'
	edges_path = tmp_path / 'edges.pkl'
	persistence_path = tmp_path / 'graphs' / 'ontology.pkl'
	nodes.to_csv(nodes_path, index = False, sep = ';')
	edges.to_pickle(edges_path)
	config = {
		'file_format': {'src': 'source', 'dst': 'target', 'id': 'id', 'directed': True, 'sep': ';'},
		'initial_nodes': {'type': 'csv', 'path': str(nodes_path)},
		'initial_edges': {'type': 'pickle', 'path': str(edges_path)},
		'persistence': {'path': str(persistence_path)}
	}
	graph = AgenticGraph(schema = 'ontology', extra_args = config)

	graph.pilot(graph.states.READY.value)

	assert graph.get_children_idx() == ['ontology|animal', 'ontology|_edge_']
	assert graph.get_children_idx('ontology|animal') == ['ontology|animal|mammal', 'ontology|animal|bird']
	assert graph.get_children_idx('ontology|animal|mammal') is None
	assert graph.child('ontology|animal|mammal') == {'label': 'Mammal'}
	assert graph.child('ontology|_edge_|animal|mammal||animal|bird||related') == {'weight': 2}
	assert graph.child('ontology|_edge_|missing') is None
	graph._graph.networkx.remove_node('animal|bird')
	assert graph.child('ontology|animal|bird') is None
	assert graph.child('ontology|_edge_|animal|mammal||animal|bird||related') is None
	graph._graph.networkx.add_node('animal|bird', label = 'Bird')
	graph._graph.networkx.add_edge('animal|mammal', 'animal|bird', key = 'related', weight = 2)

	graph.close(True)
	assert persistence_path.is_file()

	with open(persistence_path, 'rb') as f:
		persisted = pickle.load(f)
	assert type(persisted) is nx.MultiDiGraph

	reloaded = AgenticGraph(schema = 'ontology', extra_args = config)
	reloaded.pilot(reloaded.states.READY.value)
	assert reloaded.child('ontology|animal|bird') == {'label': 'Bird'}
	reloaded.close(False)


def test_agentic_graph_loads_pickle_nodes_and_csv_edges(tmp_path):
	""" Verifies the remaining supported initial data file formats. """
	nodes = pd.DataFrame([{'id': 'root|child', 'label': 'Child'}])
	edges = pd.DataFrame([{'src': 'root|child', 'dst': 'root|child', 'id': 'self'}])
	nodes_path = tmp_path / 'nodes.pkl'
	edges_path = tmp_path / 'edges.csv'
	nodes.to_pickle(nodes_path)
	edges.to_csv(edges_path, index = False)
	graph = AgenticGraph(
		schema = 'formats',
		extra_args = {
			'file_format': {'src': 'src', 'dst': 'dst', 'id': 'id', 'directed': True, 'sep': ','},
			'initial_nodes': {'type': 'pickle', 'path': str(nodes_path)},
			'initial_edges': {'type': 'csv', 'path': str(edges_path)}
		}
	)

	graph.pilot(graph.states.READY.value)
	assert graph.child('formats|root|child') == {'label': 'Child'}
	graph.close(False)


def test_agentic_graph_handles_initialization_errors(tmp_path):
	""" Verifies errors during graph creation and attempts to reuse an invalid graph. """
	logger = []
	graph = AgenticGraph(
		schema = 'broken',
		extra_args = {'initial_nodes': {'type': 'csv', 'path': str(tmp_path / 'missing.csv')}},
		logger = logger
	)

	graph.pilot(graph.states.READY.value)
	assert graph.meta['state'] == graph.states.ERR_GRAPH_INIT.value
	assert logger[-1]['error'] == 'Graph could not be created and initialized for AgenticGraph "broken".'

	graph.pilot(graph.states.READY.value)
	assert logger[-1]['error'] == 'AgenticGraph is in error state -1'


# if __name__ == "__main__":
# 	pytest.main([__file__])
