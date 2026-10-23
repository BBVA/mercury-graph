import os, pickle

import pandas as pd
import pytest
import networkx as nx

from mercury.graph.evidence import AgenticGraph, MultiGraph
from mercury.graph.evidence.agentic import AgenticRunInvalidRequest
from mercury.graph.evidence.agentic_graph import graph_from_files


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


def _files(directory, nodes, edges = None, sep = '\t'):
	""" Writes nodes and edges (lists of dicts) as .csv files in directory and returns them as the arguments of graph_from_files(). """
	conf = {}
	for kind, rows in (('nodes', nodes), ('edges', edges)):
		if rows is not None:
			path = directory / ('%s.csv' % kind)
			pd.DataFrame(rows).to_csv(path, index = False, sep = sep)
			conf[kind] = {'type': 'csv', 'path': str(path)}

	return conf


def test_graph_from_files_loads_nodes_and_edges(tmp_path):
	""" Nodes and edges keep their attributes and the id of an edge becomes its key. """
	conf = _files(tmp_path, [{'id': 'a', 'kind': 'person'}, {'id': 'b', 'kind': 'company'}], [{'src': 'a', 'dst': 'b', 'id': 'e1', 'relation': 'owns'}])

	ntx = graph_from_files(**conf).networkx

	assert dict(ntx.nodes(data = True)) == {'a': {'kind': 'person'}, 'b': {'kind': 'company'}}
	assert list(ntx.edges(keys = True, data = True)) == [('a', 'b', 'e1', {'relation': 'owns'})]


def test_graph_from_files_uses_the_file_format(tmp_path):
	""" The column names and the separator come from "file_format". """
	conf = _files(tmp_path, [{'name': 'a'}, {'name': 'b'}], [{'from': 'a', 'to': 'b', 'name': 'e1'}], sep = ';')
	conf['file_format'] = {'src': 'from', 'dst': 'to', 'id': 'name', 'directed': True, 'sep': ';'}

	assert list(graph_from_files(**conf).networkx.edges(keys = True)) == [('a', 'b', 'e1')]


def test_graph_from_files_completes_a_partial_file_format(tmp_path):
	""" The keys missing in "file_format" take their default values, including the tab separator. """
	conf = _files(tmp_path, [{'id': 'a'}, {'id': 'b'}], [{'from': 'a', 'to': 'b', 'id': 'e1'}])
	conf['file_format'] = {'src': 'from', 'dst': 'to'}

	assert list(graph_from_files(**conf).networkx.edges(keys = True)) == [('a', 'b', 'e1')]


def test_graph_from_files_requires_nodes_for_edges(tmp_path):
	""" Edges cannot be loaded without a file of nodes. """
	conf = _files(tmp_path, None, [{'src': 'a', 'dst': 'b', 'id': 'e1'}])

	with pytest.raises(ValueError, match = 'file of nodes'):
		graph_from_files(**conf)


def test_graph_from_files_requires_declared_edge_ends(tmp_path):
	""" Every src and dst of an edge must be a declared node, and every missing one is reported at once. """
	conf = _files(tmp_path, [{'id': 'a'}, {'id': 'b'}], [{'src': 'a', 'dst': 'c', 'id': 'e1'}, {'src': 'd', 'dst': 'b', 'id': 'e2'}])

	with pytest.raises(ValueError) as error:
		graph_from_files(**conf)

	assert '"c" (dst of "e1")' in str(error.value)
	assert '"d" (src of "e2")' in str(error.value)


def test_graph_from_files_requires_unique_node_ids(tmp_path):
	""" Two nodes with the same id are an error, and every repeated id is reported at once. """
	conf = _files(tmp_path, [{'id': 'a', 'kind': 'x'}, {'id': 'a', 'kind': 'y'}, {'id': 'b'}, {'id': 'b'}, {'id': 'c'}])

	with pytest.raises(ValueError) as error:
		graph_from_files(**conf)

	assert 'Nodes have repeated ids: "a", "b".' in str(error.value)


def test_graph_from_files_requires_unique_edge_ids(tmp_path):
	""" Two edges with the same id are an error, whether they have the same ends or not. """
	edges = [{'src': 'a', 'dst': 'b', 'id': 'e1'}, {'src': 'a', 'dst': 'b', 'id': 'e1'},
			 {'src': 'a', 'dst': 'b', 'id': 'e2'}, {'src': 'b', 'dst': 'a', 'id': 'e2'}]
	conf = _files(tmp_path, [{'id': 'a'}, {'id': 'b'}], edges)

	with pytest.raises(ValueError) as error:
		graph_from_files(**conf)

	assert 'Edges have repeated ids: "e1", "e2".' in str(error.value)


def test_graph_from_files_accepts_nodes_without_edges(tmp_path):
	""" A graph can have nodes and no edges. """
	ntx = graph_from_files(**_files(tmp_path, [{'id': 'a'}, {'id': 'b'}])).networkx

	assert set(ntx.nodes) == {'a', 'b'}
	assert ntx.number_of_edges() == 0


def test_graph_from_files_without_files_is_empty():
	""" Without nodes and edges the graph is empty. """
	ntx = graph_from_files().networkx

	assert ntx.number_of_nodes() == 0
	assert ntx.number_of_edges() == 0


def test_graph_from_files_reads_pickles(tmp_path):
	""" Nodes and edges can also be pandas pickles. """
	pd.DataFrame([{'id': 'a'}, {'id': 'b'}]).to_pickle(tmp_path / 'nodes.pickle')
	pd.DataFrame([{'src': 'a', 'dst': 'b', 'id': 'e1'}]).to_pickle(tmp_path / 'edges.pickle')
	conf = {'nodes': {'type': 'pickle', 'path': str(tmp_path / 'nodes.pickle')},
			'edges': {'type': 'pickle', 'path': str(tmp_path / 'edges.pickle')}}

	ntx = graph_from_files(**conf).networkx

	assert set(ntx.nodes) == {'a', 'b'}
	assert list(ntx.edges(keys = True)) == [('a', 'b', 'e1')]


def test_graph_from_files_rejects_unknown_file_types():
	""" A file type other than "csv" or "pickle" is an error. """
	with pytest.raises(ValueError):
		graph_from_files(nodes = {'type': 'parquet', 'path': 'nodes.parquet'})


def test_agentic_graph_metadata_and_requests():
	""" Verifies metadata, request dispatch, and errors before the graph is ready. """
	logger = []
	graph = AgenticGraph(schema = 'ontology', extra_args = {'description': ['First line.', 'Second line.']}, logger = logger)
	children_name = 'children_entities_by_idx_ontology'
	node_name = 'entity_by_idx_ontology'

	assert graph.meta['state'] == 0
	assert graph.meta['description'] == 'First line.\nSecond line.'
	assert [capability['function']['name'] for capability in graph.meta['capabilities']] == [children_name, node_name, 'search_entities_ontology']
	assert graph.dry_run({'anything': True}) == {'status': 0, 'description': 'Valid request.'}
	assert graph.get_children_idx() is None
	assert graph.child('ontology') is None

	with pytest.raises(AgenticRunInvalidRequest):
		graph._run({'name': 'unknown', 'function': 'unknown', 'arguments': {'index': 'ontology'}})
	assert graph._missing_arguments('unknown', {}) == []

	with pytest.raises(AgenticRunInvalidRequest):
		graph._run({'name': children_name, 'function': children_name, 'arguments': {}})

	assert len(logger) == 4
	assert logger[-2]['error'] == 'AgenticGraph does not have a function named "unknown".'
	assert logger[-1]['error'] == 'AgenticGraph function "children_entities_by_idx_ontology" requires the argument "index".'


def test_agentic_graph_run_passes_every_argument(tmp_path):
	""" Verifies that a capability receives all its arguments and that required arguments come from its definition. """
	logger = []
	graph = AgenticGraph(schema = 'ontology', extra_args = {}, logger = logger)
	graph.pilot(graph.states.READY.value)
	received = []
	graph.call['children_entities_by_idx_ontology'] = lambda arguments: received.append(arguments) or []

	graph._run({'name': 'children_entities_by_idx_ontology', 'arguments': {'index': 'person', 'depth': 2}})

	assert received == [{'index': 'person', 'depth': 2}]

	graph._meta_['capabilities'][0]['function']['parameters']['required'] = ['index', 'depth']

	with pytest.raises(AgenticRunInvalidRequest):
		graph._run({'name': 'children_entities_by_idx_ontology', 'arguments': {'index': 'person'}})

	assert logger[-1]['error'] == 'AgenticGraph function "children_entities_by_idx_ontology" requires the argument "depth".'
	assert len(received) == 1


def test_agentic_graph_allows_schema_discovery_without_configuration():
	""" Verifies construction for callers that only need the AgenticGraph class identity. """
	graph = AgenticGraph(schema = None, extra_args = None)

	assert type(graph) is AgenticGraph
	assert graph.id == 'agentic_graph'
	assert graph.states.__name__ == 'AlwaysReadyState'


def test_agentic_graph_creates_and_queries_default_graph():
	""" Verifies default graph creation, one-step piloting, and index query results. """
	graph = AgenticGraph(schema = 'empty', extra_args = {'description': 'Empty graph.'})

	graph.pilot(graph.states.READY.value, just_once = True)
	assert graph.meta['state'] == graph.states.GRAPH_LOADED_OK.value

	graph.pilot(graph.states.READY.value)
	assert graph.meta['state'] == graph.states.READY.value
	assert graph.get_children_idx() == []
	assert graph.get_children_idx('') == []
	assert graph.get_children_idx('missing') is None
	assert graph.get_children_idx('missing|child') is None
	assert graph.child('') is None
	assert graph.child('missing') is None
	assert graph._run({'name': 'children_entities_by_idx_empty', 'arguments': {'index': ''}}) == {'finish_reason': 'stop', 'message': []}

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
		'nodes': {'type': 'csv', 'path': str(nodes_path)},
		'edges': {'type': 'pickle', 'path': str(edges_path)},
		'persistence': {'path': str(persistence_path)}
	}
	graph = AgenticGraph(schema = 'ontology', extra_args = config)

	graph.pilot(graph.states.READY.value)

	assert graph.get_children_idx() == ['animal']
	assert graph.get_children_idx('animal') == ['animal|mammal', 'animal|bird']
	assert graph.get_children_idx('animal|mammal') is None
	assert graph.child('animal|mammal') == {'label': 'Mammal'}
	assert graph._graph.networkx.edges['animal|mammal', 'animal|bird', 'related'] == {'weight': 2}

	graph.close(True)
	assert persistence_path.is_file()

	with open(persistence_path, 'rb') as f:
		persisted = pickle.load(f)
	assert type(persisted) is nx.MultiDiGraph

	reloaded = AgenticGraph(schema = 'ontology', extra_args = config)
	reloaded.pilot(reloaded.states.READY.value)
	assert reloaded.child('animal|bird') == {'label': 'Bird'}
	assert reloaded._graph.networkx.edges['animal|mammal', 'animal|bird', 'related'] == {'weight': 2}
	reloaded.close(False)


def _persisted_graph(directory, logger):
	""" Returns the configuration of a graph whose pickle has been saved after loading its .csv files, and the paths of these files. """
	conf = _files(directory, [{'id': 'a'}, {'id': 'b'}], [{'src': 'a', 'dst': 'b', 'id': 'e1'}])
	conf['persistence'] = {'path': str(directory / 'graph.pickle')}
	graph = AgenticGraph(schema = 'ontology', extra_args = conf, logger = logger)
	graph.pilot(graph.states.READY.value)
	graph.close(True)

	return conf, conf['nodes']['path'], conf['edges']['path']


def _messages(logger):
	""" Returns the text of the 'message' events in logger. """
	return [event['message'] for event in logger if event['type'] == 'message']


def test_agentic_graph_warns_when_a_file_changed_after_its_pickle(tmp_path):
	""" Loading from the pickle ignores the .csv files, so a file modified after the pickle was saved is reported. """
	logger = []
	conf, nodes_path, edges_path = _persisted_graph(tmp_path, logger)
	later = os.path.getmtime(conf['persistence']['path']) + 10
	os.utime(nodes_path, (later, later))

	graph = AgenticGraph(schema = 'ontology', extra_args = conf, logger = logger)
	graph.pilot(graph.states.READY.value)

	assert graph.meta['state'] == graph.states.READY.value
	assert len(_messages(logger)) == 1
	assert nodes_path in _messages(logger)[0] and 'Delete' in _messages(logger)[0]


def test_agentic_graph_does_not_warn_when_the_files_did_not_change(tmp_path):
	""" Without changes after the pickle was saved, loading it logs no warning. """
	logger = []
	conf, nodes_path, edges_path = _persisted_graph(tmp_path, logger)
	earlier = os.path.getmtime(conf['persistence']['path']) - 10
	os.utime(nodes_path, (earlier, earlier))
	os.utime(edges_path, (earlier, earlier))

	graph = AgenticGraph(schema = 'ontology', extra_args = conf, logger = logger)
	graph.pilot(graph.states.READY.value)

	assert _messages(logger) == []


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
			'nodes': {'type': 'pickle', 'path': str(nodes_path)},
			'edges': {'type': 'csv', 'path': str(edges_path)}
		}
	)

	graph.pilot(graph.states.READY.value)
	assert graph.child('root|child') == {'label': 'Child'}
	graph.close(False)


def test_agentic_graph_index_tree_does_not_depend_on_node_order(tmp_path):
	""" Verifies that a parent listed after its children keeps them in the navigation tree. """
	trees = []
	for n, order in enumerate([['person', 'person|teacher'], ['person|teacher', 'person']]):
		nodes_path = tmp_path / ('nodes_%d.csv' % n)
		pd.DataFrame([{'id': i, 'definition': i} for i in order]).to_csv(nodes_path, index = False, sep = '\t')
		graph = AgenticGraph(schema = 'entities', extra_args = {'nodes': {'type': 'csv', 'path': str(nodes_path)}})

		graph.pilot(graph.states.READY.value)
		assert graph.get_children_idx('person') == ['person|teacher']
		assert graph.child('person') == {'definition': 'person'}
		trees.append(graph._entities._tree)

	assert trees[0] == trees[1]


def test_agentic_graph_ids_do_not_include_the_ontology_name(tmp_path):
	""" Verifies that ids are used exactly as in the .csv files, without the name of the ontology in front. """
	nodes_path = tmp_path / 'nodes.csv'
	pd.DataFrame([{'id': 'person', 'definition': 'A human being.'}, {'id': 'person|teacher', 'definition': 'A teacher.'}]).to_csv(nodes_path, index = False, sep = '\t')
	graph = AgenticGraph(schema = 'entities', extra_args = {'nodes': {'type': 'csv', 'path': str(nodes_path)}})

	graph.pilot(graph.states.READY.value)

	assert graph.get_children_idx() == ['person']
	assert graph.get_children_idx('person') == ['person|teacher']
	assert graph.child('person|teacher') == {'definition': 'A teacher.'}
	assert graph._run({'name': 'entity_by_idx_entities', 'arguments': {'index': 'person|teacher'}})['message']['properties'] == {'definition': 'A teacher.'}

	assert graph.get_children_idx('entities') is None
	assert graph.get_children_idx('entities|person') is None
	assert graph.child('entities|person|teacher') is None


def test_agentic_graph_edges_are_not_in_the_navigation_tree(tmp_path):
	""" Verifies that edges stay in the graph but are not navigated as children or read as nodes. """
	nodes_path = tmp_path / 'nodes.csv'
	edges_path = tmp_path / 'edges.csv'
	pd.DataFrame([{'id': 'person|Noah'}, {'id': 'project|Helios'}]).to_csv(nodes_path, index = False, sep = '\t')
	pd.DataFrame([{'src': 'person|Noah', 'dst': 'project|Helios', 'relation': 'works_on', 'id': 'noah_helios'}]).to_csv(edges_path, index = False, sep = '\t')
	graph = AgenticGraph(schema = 'known_ids', extra_args = {
		'nodes': {'type': 'csv', 'path': str(nodes_path)},
		'edges': {'type': 'csv', 'path': str(edges_path)}
	})

	graph.pilot(graph.states.READY.value)

	assert graph._graph.networkx.number_of_edges() == 1
	assert graph.get_children_idx() == ['person', 'project']
	assert graph.get_children_idx('_edge_') is None
	assert graph.child('_edge_|person|Noah||project|Helios||noah_helios') is None


def _school_graph(directory, name = 'entities', max_results = None):
	""" Returns a ready AgenticGraph with a small hierarchy of concepts; 'person|student' is a folder without a node of its own. """
	nodes = [
		('person', 'A human being.'),
		('person|teacher', 'A person who teaches.'),
		('person|student|Noah', None),
		('event', 'Something that takes place.'),
		('place', 'A physical location.'),
		('place|room', 'A room inside a building.'),
		('place|room|laboratory', 'A room for scientific work.')
	]
	path = directory / ('%s.csv' % name)
	pd.DataFrame([{'id': i, 'definition': d} for i, d in nodes]).to_csv(path, index = False, sep = '\t')
	extra_args = {'nodes': {'type': 'csv', 'path': str(path)}}
	if max_results is not None:
		extra_args['max_results'] = max_results
	graph = AgenticGraph(schema = name, extra_args = extra_args)
	graph.pilot(graph.states.READY.value)

	return graph


def _call(graph, capability, **arguments):
	""" Returns the message of running a capability of graph with the given arguments. """
	return graph._run({'name': '%s_%s' % (capability, graph.name), 'arguments': arguments})['message']


def test_children_entities_by_idx_returns_children_with_definitions(tmp_path):
	""" With the default depth, every child comes with its definition and "more" when it has children of its own. """
	graph = _school_graph(tmp_path)

	assert _call(graph, 'children_entities_by_idx', index = '') == [
		{'id': 'person', 'definition': 'A human being.', 'more': True},
		{'id': 'event', 'definition': 'Something that takes place.'},
		{'id': 'place', 'definition': 'A physical location.', 'more': True}
	]


def test_children_entities_by_idx_goes_down_to_depth(tmp_path):
	""" With a larger depth, children are nested and "more" only marks the nodes below the last level. """
	graph = _school_graph(tmp_path)

	assert _call(graph, 'children_entities_by_idx', index = 'place', depth = 1) == [
		{'id': 'place|room', 'definition': 'A room inside a building.', 'more': True}
	]
	assert _call(graph, 'children_entities_by_idx', index = 'place', depth = 2) == [
		{'id': 'place|room', 'definition': 'A room inside a building.', 'children': [
			{'id': 'place|room|laboratory', 'definition': 'A room for scientific work.'}
		]}
	]


def test_children_entities_by_idx_folders_have_no_definition(tmp_path):
	""" A level that is only a folder (not a node of this graph) has no definition. """
	graph = _school_graph(tmp_path)

	assert _call(graph, 'children_entities_by_idx', index = 'person') == [
		{'id': 'person|teacher', 'definition': 'A person who teaches.'},
		{'id': 'person|student', 'more': True}
	]
	assert _call(graph, 'children_entities_by_idx', index = 'person|student') == [{'id': 'person|student|Noah'}]


def test_children_entities_by_idx_leaves_and_missing_ids(tmp_path):
	""" A leaf has no children and an id that does not exist returns None. The Python method keeps returning None for both. """
	graph = _school_graph(tmp_path)

	assert _call(graph, 'children_entities_by_idx', index = 'event') == []
	assert _call(graph, 'children_entities_by_idx', index = 'missing') is None
	assert graph.get_children_idx('event') is None
	assert graph.get_children_idx('missing') is None


def test_children_entities_by_idx_accepts_loose_depths(tmp_path):
	""" A depth given as text is accepted and a depth that is not a positive number is taken as 1. """
	graph = _school_graph(tmp_path)
	one_level = _call(graph, 'children_entities_by_idx', index = 'place')

	assert _call(graph, 'children_entities_by_idx', index = 'place', depth = '2') == _call(graph, 'children_entities_by_idx', index = 'place', depth = 2)
	assert _call(graph, 'children_entities_by_idx', index = 'place', depth = 0) == one_level
	assert _call(graph, 'children_entities_by_idx', index = 'place', depth = 'deep') == one_level


def test_children_entities_by_idx_truncates_long_answers(tmp_path):
	""" Answers longer than max_results entries (counting nested ones) are cut and end with a truncated marker. Siblings come
	before the children of any of them, and a node whose children did not fit is marked with "more". """
	graph = _school_graph(tmp_path, max_results = 4)

	answer = _call(graph, 'children_entities_by_idx', index = '', depth = 3)

	assert [entry['id'] for entry in answer[:-1]] == ['person', 'event', 'place']
	assert [entry['id'] for entry in answer[0]['children']] == ['person|teacher']
	assert answer[2] == {'id': 'place', 'definition': 'A physical location.', 'more': True}
	assert answer[-1]['truncated'] is True
	assert 'hint' in answer[-1]


def test_entity_by_idx_returns_properties_and_ancestors(tmp_path):
	""" A node comes with its properties and its ancestors, from its parent to the root, with definitions when they are nodes. """
	graph = _school_graph(tmp_path)

	assert _call(graph, 'entity_by_idx', index = 'place|room|laboratory') == {
		'id': 'place|room|laboratory',
		'properties': {'definition': 'A room for scientific work.'},
		'ancestors': [
			{'id': 'place|room', 'definition': 'A room inside a building.'},
			{'id': 'place', 'definition': 'A physical location.'}
		]
	}
	assert _call(graph, 'entity_by_idx', index = 'person|student|Noah')['ancestors'] == [
		{'id': 'person|student'},
		{'id': 'person', 'definition': 'A human being.'}
	]
	assert _call(graph, 'entity_by_idx', index = 'event')['ancestors'] == []
	assert _call(graph, 'entity_by_idx', index = 'person|student') is None
	assert _call(graph, 'entity_by_idx', index = 'missing') is None


def test_children_entities_by_idx_declares_an_optional_depth(tmp_path):
	""" The capability declares depth as an optional integer parameter. """
	graph = _school_graph(tmp_path)
	capability = [c['function'] for c in graph.meta['capabilities'] if c['function']['name'] == 'children_entities_by_idx_entities'][0]

	assert capability['parameters']['properties']['depth']['type'] == 'integer'
	assert capability['parameters']['required'] == ['index']


def _csv_graph(directory, name, nodes, edges = None, **extra_args):
	""" Returns a ready AgenticGraph loaded from tab separated .csv files written in directory from lists of dictionaries. """
	for kind, rows in (('nodes', nodes), ('edges', edges)):
		if rows is not None:
			path = directory / ('%s_%s.csv' % (name, kind))
			pd.DataFrame(rows).to_csv(path, index = False, sep = '\t')
			extra_args[kind] = {'type': 'csv', 'path': str(path)}
	graph = AgenticGraph(schema = name, extra_args = extra_args)
	graph.pilot(graph.states.READY.value)

	return graph


ENTITIES = (
	('organization', 'A group of people.'),
	('organization|school', 'A place where people learn.'),
	('person', 'A human being.'),
	('person|student', 'A person who studies.'),
	('person|teacher', 'A person who teaches.'),
	('project', 'A piece of work.')
)
RELATIONSHIPS = (
	('works_on', 'person', 'project', 'A person works on a project.'),
	('works_on|leads', 'person', 'project', 'A person leads a project.'),
	('teaches_at', 'person|teacher', 'organization|school', 'A teacher teaches at a school.'),
	('studies_at', 'person|student', 'organization|school', 'A student studies at a school.'),
	('knows', 'person', 'person', 'A person knows another person.'),
	('employs', 'organization', 'person', 'An organization employs a person.')
)


def _ontology_graph(directory, **extra_args):
	""" Returns a ready ontology with ENTITIES as nodes and RELATIONSHIPS as edges. """
	nodes = [{'id': i, 'definition': d} for i, d in ENTITIES]
	edges = [{'id': i, 'src': src, 'dst': dst, 'definition': d} for i, src, dst, d in RELATIONSHIPS]

	return _csv_graph(directory, 'ontology', nodes, edges, **extra_args)


def _capability_names(graph):
	""" Returns the names of the capabilities of graph without the suffix with its name. """
	return [c['function']['name'][:-len(graph.name) - 1] for c in graph.meta['capabilities']]


def test_capabilities_depend_on_the_content_of_the_graph(tmp_path):
	""" The capabilities of relationships are only available when the graph has edges. Before loading, only those of entities are. """
	entities	  = ['children_entities_by_idx', 'entity_by_idx', 'search_entities']
	relationships = ['children_relationships_by_idx', 'relationship_by_idx', 'search_relationships', 'relations_for']

	assert _capability_names(AgenticGraph(schema = 'ontology', extra_args = {})) == entities
	assert _capability_names(_school_graph(tmp_path)) == entities
	assert _capability_names(_ontology_graph(tmp_path)) == entities + relationships


def test_search_entities_finds_nodes_by_id_and_then_by_definition(tmp_path):
	""" The search ignores case, lists matches in the id before matches in the definition and never returns folders. """
	graph = _school_graph(tmp_path)

	assert _call(graph, 'search_entities', text = 'NOAH') == [{'id': 'person|student|Noah'}]
	assert _call(graph, 'search_entities', text = 'student') == [{'id': 'person|student|Noah'}]
	assert _call(graph, 'search_entities', text = 'room') == [
		{'id': 'place|room', 'definition': 'A room inside a building.'},
		{'id': 'place|room|laboratory', 'definition': 'A room for scientific work.'}
	]
	assert _call(graph, 'search_entities', text = 'teaches') == [{'id': 'person|teacher', 'definition': 'A person who teaches.'}]
	assert _call(graph, 'search_entities', text = 'missing') == []
	assert _call(graph, 'search_entities', text = ' ') == []


def test_search_entities_is_limited(tmp_path):
	""" The search returns at most limit results (and never more than max_results), ending with a truncated marker if cut. """
	graph = _school_graph(tmp_path, max_results = 3)

	answer = _call(graph, 'search_entities', text = 'p', limit = 2)

	assert [entry['id'] for entry in answer[:-1]] == ['person', 'person|student|Noah']
	assert answer[-1]['truncated'] is True
	assert len(_call(graph, 'search_entities', text = 'p', limit = 10)) == 3 + 1


def test_children_relationships_by_idx_returns_relationships_with_their_ends(tmp_path):
	""" Relationships are listed by id with their definition and the types of entity they connect; "more" marks those with children. """
	graph = _ontology_graph(tmp_path)

	answer = _call(graph, 'children_relationships_by_idx', index = '')

	assert [entry['id'] for entry in answer] == ['employs', 'knows', 'studies_at', 'teaches_at', 'works_on']
	assert answer[-1] == {'id': 'works_on', 'definition': 'A person works on a project.', 'src': 'person', 'dst': 'project', 'more': True}
	assert _call(graph, 'children_relationships_by_idx', index = 'works_on') == [
		{'id': 'works_on|leads', 'definition': 'A person leads a project.', 'src': 'person', 'dst': 'project'}
	]
	assert _call(graph, 'children_relationships_by_idx', index = '', depth = 2)[-1]['children'][0]['id'] == 'works_on|leads'
	assert _call(graph, 'children_relationships_by_idx', index = 'missing') is None


def test_children_relationships_by_idx_truncates_long_answers(tmp_path):
	""" Relationships are limited to max_results entries, like entities. """
	graph = _ontology_graph(tmp_path, max_results = 2)

	answer = _call(graph, 'children_relationships_by_idx', index = '')

	assert [entry['id'] for entry in answer[:-1]] == ['employs', 'knows']
	assert answer[-1]['truncated'] is True


def test_relationship_by_idx_returns_properties_and_ancestors(tmp_path):
	""" A relationship comes with its src, dst and definition, and its ancestors with theirs. """
	graph = _ontology_graph(tmp_path)

	assert _call(graph, 'relationship_by_idx', index = 'works_on|leads') == {
		'id': 'works_on|leads',
		'properties': {'src': 'person', 'dst': 'project', 'definition': 'A person leads a project.'},
		'ancestors': [{'id': 'works_on', 'definition': 'A person works on a project.', 'src': 'person', 'dst': 'project'}]
	}
	assert _call(graph, 'relationship_by_idx', index = 'person') is None
	assert _call(graph, 'relationship_by_idx', index = 'missing') is None


def test_search_relationships_finds_them_by_id_and_then_by_definition(tmp_path):
	""" The search of relationships works like that of entities, on the ids and definitions of the relationships. """
	graph = _ontology_graph(tmp_path)

	assert [entry['id'] for entry in _call(graph, 'search_relationships', text = 'WORKS')] == ['works_on', 'works_on|leads']
	assert [entry['id'] for entry in _call(graph, 'search_relationships', text = 'school')] == ['studies_at', 'teaches_at']
	assert _call(graph, 'search_relationships', text = 'person|student') == []
	assert [entry['id'] for entry in _call(graph, 'search_relationships', text = 'a', limit = 2)[:-1]] == ['studies_at', 'teaches_at']


def test_relations_for_includes_inherited_relations(tmp_path):
	""" A type of entity takes part in the relationships declared for it or for any of its ancestors, as src, dst or both. """
	graph = _ontology_graph(tmp_path)

	answer = _call(graph, 'relations_for', concept = 'person|student')

	assert [(e['id'], e['as']) for e in answer] == [
		('employs', 'dst'), ('knows', 'both'), ('studies_at', 'src'), ('works_on', 'src'), ('works_on|leads', 'src')
	]
	assert answer[2] == {
		'id': 'studies_at', 'src': 'person|student', 'dst': 'organization|school', 'as': 'src', 'definition': 'A student studies at a school.'
	}


def test_relations_for_without_inheritance(tmp_path):
	""" Without inheritance, only the relationships declared exactly for the type of entity are returned. A more general type does not
	take part in the relationships of its descendants.
	"""
	graph = _ontology_graph(tmp_path)

	assert [e['id'] for e in _call(graph, 'relations_for', concept = 'person|student', inherited = False)] == ['studies_at']
	assert [e['id'] for e in _call(graph, 'relations_for', concept = 'person|student', inherited = 'false')] == ['studies_at']
	assert [e['id'] for e in _call(graph, 'relations_for', concept = 'person')] == ['employs', 'knows', 'works_on', 'works_on|leads']
	assert _call(graph, 'relations_for', concept = 'vehicle') == []


def test_relations_for_is_limited(tmp_path):
	""" The relationships of a type of entity are limited to max_results, ending with a truncated marker if cut. """
	graph = _ontology_graph(tmp_path, max_results = 1)

	answer = _call(graph, 'relations_for', concept = 'person')

	assert [e['id'] for e in answer[:-1]] == ['employs']
	assert answer[-1]['truncated'] is True


def test_capabilities_are_not_ready_before_loading():
	""" Before the graph is loaded, every capability returns None and logs why. """
	logger = []
	graph = AgenticGraph(schema = 'ontology', extra_args = {}, logger = logger)
	runners = (graph._children_entities_by_idx, graph._entity_by_idx, graph._search_entities, graph._children_relationships_by_idx,
			   graph._relationship_by_idx, graph._search_relationships, graph._relations_for)

	for runner in runners:
		assert runner({'index': '', 'text': 'x', 'concept': 'x'}) is None

	assert len(logger) == len(runners)


def test_capability_definitions_are_not_shared(tmp_path):
	""" Changing the definition of a capability of a graph does not change it in other graphs. """
	first, second = AgenticGraph(schema = 'first', extra_args = {}), AgenticGraph(schema = 'second', extra_args = {})

	first.meta['capabilities'][0]['function']['parameters']['required'].append('depth')

	assert second.meta['capabilities'][0]['function']['parameters']['required'] == ['index']


def test_agentic_graph_handles_initialization_errors(tmp_path):
	""" Verifies errors during graph creation and attempts to reuse an invalid graph. """
	logger = []
	graph = AgenticGraph(
		schema = 'broken',
		extra_args = {'nodes': {'type': 'csv', 'path': str(tmp_path / 'missing.csv')}},
		logger = logger
	)

	graph.pilot(graph.states.READY.value)
	assert graph.meta['state'] == graph.states.ERR_GRAPH_INIT.value
	assert logger[-1]['error'].startswith('Graph could not be created and initialized for AgenticGraph "broken": ')
	assert 'missing.csv' in logger[-1]['error']

	graph.pilot(graph.states.READY.value)
	assert logger[-1]['error'] == 'AgenticGraph is in error state -1'


# if __name__ == "__main__":
# 	pytest.main([__file__])
