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
	assert [capability['function']['name'] for capability in graph.meta['capabilities']] == [children_name, node_name, 'search_ontology']
	assert graph.dry_run({'anything': True}) == {'status': 0, 'description': 'Valid request.'}
	assert graph.get_children_idx() is None
	assert graph.child('ontology') is None

	with pytest.raises(AgenticRunInvalidRequest):
		graph._run({'name': 'unknown', 'function': 'unknown', 'arguments': {'index': 'ontology'}})

	with pytest.raises(AgenticRunInvalidRequest):
		graph._run({'name': children_name, 'function': children_name, 'arguments': {}})

	assert len(logger) == 4
	assert logger[-2]['error'] == 'AgenticGraph does not have a function named "unknown".'
	assert logger[-1]['error'] == 'AgenticGraph function "children_by_idx_ontology" requires the argument "index".'


def test_agentic_graph_run_passes_every_argument(tmp_path):
	""" Verifies that a capability receives all its arguments and that required arguments come from its definition. """
	logger = []
	graph = AgenticGraph(schema = 'ontology', extra_args = {}, logger = logger)
	graph.pilot(graph.states.READY.value)
	received = []
	graph.call['children_by_idx_ontology'] = lambda arguments: received.append(arguments) or []

	graph._run({'name': 'children_by_idx_ontology', 'arguments': {'index': 'person', 'depth': 2}})

	assert received == [{'index': 'person', 'depth': 2}]

	graph._meta_['capabilities'][0]['function']['parameters']['required'] = ['index', 'depth']

	with pytest.raises(AgenticRunInvalidRequest):
		graph._run({'name': 'children_by_idx_ontology', 'arguments': {'index': 'person'}})

	assert logger[-1]['error'] == 'AgenticGraph function "children_by_idx_ontology" requires the argument "depth".'
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
	assert graph._run({'name': 'children_by_idx_empty', 'arguments': {'index': ''}}) == {'finish_reason': 'stop', 'message': []}

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

	assert graph.get_children_idx() == ['animal']
	assert graph.get_children_idx('animal') == ['animal|mammal', 'animal|bird']
	assert graph.get_children_idx('animal|mammal') is None
	assert graph.child('animal|mammal') == {'label': 'Mammal'}
	assert graph._graph.networkx.edges['animal|mammal', 'animal|bird', 'related'] == {'weight': 2}
	graph._graph.networkx.remove_node('animal|bird')
	assert graph.child('animal|bird') is None
	graph._graph.networkx.add_node('animal|bird', label = 'Bird')
	graph._graph.networkx.add_edge('animal|mammal', 'animal|bird', key = 'related', weight = 2)

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
	assert graph.child('root|child') == {'label': 'Child'}
	graph.close(False)


def test_agentic_graph_index_tree_does_not_depend_on_node_order(tmp_path):
	""" Verifies that a parent listed after its children keeps them in the navigation tree. """
	trees = []
	for n, order in enumerate([['person', 'person|teacher'], ['person|teacher', 'person']]):
		nodes_path = tmp_path / ('nodes_%d.csv' % n)
		pd.DataFrame([{'id': i, 'definition': i} for i in order]).to_csv(nodes_path, index = False, sep = '\t')
		graph = AgenticGraph(schema = 'entities', extra_args = {'initial_nodes': {'type': 'csv', 'path': str(nodes_path)}})

		graph.pilot(graph.states.READY.value)
		assert graph.get_children_idx('person') == ['person|teacher']
		assert graph.child('person') == {'definition': 'person'}
		trees.append(graph._indices)

	assert trees[0] == trees[1]


def test_agentic_graph_ids_do_not_include_the_ontology_name(tmp_path):
	""" Verifies that ids are used exactly as in the .csv files, without the name of the ontology in front. """
	nodes_path = tmp_path / 'nodes.csv'
	pd.DataFrame([{'id': 'person', 'definition': 'A human being.'}, {'id': 'person|teacher', 'definition': 'A teacher.'}]).to_csv(nodes_path, index = False, sep = '\t')
	graph = AgenticGraph(schema = 'entities', extra_args = {'initial_nodes': {'type': 'csv', 'path': str(nodes_path)}})

	graph.pilot(graph.states.READY.value)

	assert graph.get_children_idx() == ['person']
	assert graph.get_children_idx('person') == ['person|teacher']
	assert graph.child('person|teacher') == {'definition': 'A teacher.'}
	assert graph._run({'name': 'node_by_idx_entities', 'arguments': {'index': 'person|teacher'}})['message']['properties'] == {'definition': 'A teacher.'}

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
		'initial_nodes': {'type': 'csv', 'path': str(nodes_path)},
		'initial_edges': {'type': 'csv', 'path': str(edges_path)}
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
	extra_args = {'initial_nodes': {'type': 'csv', 'path': str(path)}}
	if max_results is not None:
		extra_args['max_results'] = max_results
	graph = AgenticGraph(schema = name, extra_args = extra_args)
	graph.pilot(graph.states.READY.value)

	return graph


def _call(graph, capability, **arguments):
	""" Returns the message of running a capability of graph with the given arguments. """
	return graph._run({'name': '%s_%s' % (capability, graph.name), 'arguments': arguments})['message']


def test_children_by_idx_returns_children_with_definitions(tmp_path):
	""" With the default depth, every child comes with its definition and "more" when it has children of its own. """
	graph = _school_graph(tmp_path)

	assert _call(graph, 'children_by_idx', index = '') == [
		{'id': 'person', 'definition': 'A human being.', 'more': True},
		{'id': 'event', 'definition': 'Something that takes place.'},
		{'id': 'place', 'definition': 'A physical location.', 'more': True}
	]


def test_children_by_idx_goes_down_to_depth(tmp_path):
	""" With a larger depth, children are nested and "more" only marks the nodes below the last level. """
	graph = _school_graph(tmp_path)

	assert _call(graph, 'children_by_idx', index = 'place', depth = 1) == [
		{'id': 'place|room', 'definition': 'A room inside a building.', 'more': True}
	]
	assert _call(graph, 'children_by_idx', index = 'place', depth = 2) == [
		{'id': 'place|room', 'definition': 'A room inside a building.', 'children': [
			{'id': 'place|room|laboratory', 'definition': 'A room for scientific work.'}
		]}
	]


def test_children_by_idx_folders_have_no_definition(tmp_path):
	""" A level that is only a folder (not a node of this graph) has no definition. """
	graph = _school_graph(tmp_path)

	assert _call(graph, 'children_by_idx', index = 'person') == [
		{'id': 'person|teacher', 'definition': 'A person who teaches.'},
		{'id': 'person|student', 'more': True}
	]
	assert _call(graph, 'children_by_idx', index = 'person|student') == [{'id': 'person|student|Noah'}]


def test_children_by_idx_leaves_and_missing_ids(tmp_path):
	""" A leaf has no children and an id that does not exist returns None. The Python method keeps returning None for both. """
	graph = _school_graph(tmp_path)

	assert _call(graph, 'children_by_idx', index = 'event') == []
	assert _call(graph, 'children_by_idx', index = 'missing') is None
	assert graph.get_children_idx('event') is None
	assert graph.get_children_idx('missing') is None


def test_children_by_idx_accepts_loose_depths(tmp_path):
	""" A depth given as text is accepted and a depth that is not a positive number is taken as 1. """
	graph = _school_graph(tmp_path)
	one_level = _call(graph, 'children_by_idx', index = 'place')

	assert _call(graph, 'children_by_idx', index = 'place', depth = '2') == _call(graph, 'children_by_idx', index = 'place', depth = 2)
	assert _call(graph, 'children_by_idx', index = 'place', depth = 0) == one_level
	assert _call(graph, 'children_by_idx', index = 'place', depth = 'deep') == one_level


def test_children_by_idx_truncates_long_answers(tmp_path):
	""" Answers longer than max_results entries (counting nested ones) are cut and end with a truncated marker. Siblings come
	before the children of any of them, and a node whose children did not fit is marked with "more". """
	graph = _school_graph(tmp_path, max_results = 4)

	answer = _call(graph, 'children_by_idx', index = '', depth = 3)

	assert [entry['id'] for entry in answer[:-1]] == ['person', 'event', 'place']
	assert [entry['id'] for entry in answer[0]['children']] == ['person|teacher']
	assert answer[2] == {'id': 'place', 'definition': 'A physical location.', 'more': True}
	assert answer[-1]['truncated'] is True
	assert 'hint' in answer[-1]


def test_node_by_idx_returns_properties_and_ancestors(tmp_path):
	""" A node comes with its properties and its ancestors, from its parent to the root, with definitions when they are nodes. """
	graph = _school_graph(tmp_path)

	assert _call(graph, 'node_by_idx', index = 'place|room|laboratory') == {
		'id': 'place|room|laboratory',
		'properties': {'definition': 'A room for scientific work.'},
		'ancestors': [
			{'id': 'place|room', 'definition': 'A room inside a building.'},
			{'id': 'place', 'definition': 'A physical location.'}
		]
	}
	assert _call(graph, 'node_by_idx', index = 'person|student|Noah')['ancestors'] == [
		{'id': 'person|student'},
		{'id': 'person', 'definition': 'A human being.'}
	]
	assert _call(graph, 'node_by_idx', index = 'event')['ancestors'] == []
	assert _call(graph, 'node_by_idx', index = 'person|student') is None
	assert _call(graph, 'node_by_idx', index = 'missing') is None


def test_children_by_idx_declares_an_optional_depth(tmp_path):
	""" The capability declares depth as an optional integer parameter. """
	graph = _school_graph(tmp_path)
	capability = [c['function'] for c in graph.meta['capabilities'] if c['function']['name'] == 'children_by_idx_entities'][0]

	assert capability['parameters']['properties']['depth']['type'] == 'integer'
	assert capability['parameters']['required'] == ['index']


def _csv_graph(directory, name, nodes, edges = None, **extra_args):
	""" Returns a ready AgenticGraph loaded from tab separated .csv files written in directory from lists of dictionaries. """
	for kind, rows in (('nodes', nodes), ('edges', edges)):
		if rows is not None:
			path = directory / ('%s_%s.csv' % (name, kind))
			pd.DataFrame(rows).to_csv(path, index = False, sep = '\t')
			extra_args['initial_%s' % kind] = {'type': 'csv', 'path': str(path)}
	graph = AgenticGraph(schema = name, extra_args = extra_args)
	graph.pilot(graph.states.READY.value)

	return graph


def _relationships_graph(directory, **extra_args):
	""" Returns a ready relationships ontology: 'knows' connects persons and 'employs' has person as its dst. """
	rows = [
		('employs', 'organization', 'person', 'An organization employs a person.'),
		('knows', 'person', 'person', 'A person knows another person.'),
		('studies_at', 'person|student', 'organization|school', 'A student studies at a school.'),
		('teaches_at', 'person|teacher', 'organization|school', 'A teacher teaches at a school.'),
		('works_on', 'person', 'project', 'A person works on a project.'),
		('works_on|leads', 'person', 'project', 'A person leads a project.')
	]
	nodes = [{'id': i, 'src': src, 'dst': dst, 'definition': d} for i, src, dst, d in rows]

	return _csv_graph(directory, 'relationships', nodes, **extra_args)


def _known_ids_graph(directory, **extra_args):
	""" Returns a ready known_ids ontology with a few instances, one of them (the award) without edges. """
	nodes = [{'id': i} for i in (
		'person|student|Noah Kim', 'person|student|Priya Shah', 'person|teacher|Elena Ruiz', 'organization|school|Riverside High School',
		'project|Helios Solar Car', 'award|Science Prize'
	)]
	edges = [
		{'src': 'person|student|Noah Kim', 'dst': 'project|Helios Solar Car', 'relation': 'works_on|leads', 'id': 'noah_helios'},
		{'src': 'person|student|Priya Shah', 'dst': 'project|Helios Solar Car', 'relation': 'works_on', 'id': 'priya_helios'},
		{'src': 'person|student|Noah Kim', 'dst': 'organization|school|Riverside High School', 'relation': 'studies_at', 'id': 'noah_rhs'},
		{'src': 'person|teacher|Elena Ruiz', 'dst': 'organization|school|Riverside High School', 'relation': 'teaches_at', 'id': 'elena_rhs'}
	]

	return _csv_graph(directory, 'known_ids', nodes, edges, **extra_args)


def _capability_names(graph):
	""" Returns the names of the capabilities of graph without the suffix with its name. """
	return [c['function']['name'][:-len(graph.name) - 1] for c in graph.meta['capabilities']]


def test_capabilities_depend_on_the_content_of_the_graph(tmp_path):
	""" edges is only available with edges and relations_for only when nodes declare src and dst. Before loading, only the
	capabilities that do not depend on the content are available.
	"""
	assert _capability_names(AgenticGraph(schema = 'known_ids', extra_args = {})) == ['children_by_idx', 'node_by_idx', 'search']
	assert _capability_names(_school_graph(tmp_path)) == ['children_by_idx', 'node_by_idx', 'search']
	assert _capability_names(_relationships_graph(tmp_path)) == ['children_by_idx', 'node_by_idx', 'search', 'relations_for']
	assert _capability_names(_known_ids_graph(tmp_path)) == ['children_by_idx', 'node_by_idx', 'search', 'edges']


def test_search_finds_nodes_by_id_and_then_by_definition(tmp_path):
	""" The search ignores case, lists matches in the id before matches in the definition and never returns folders. """
	graph = _school_graph(tmp_path)

	assert _call(graph, 'search', text = 'NOAH') == [{'id': 'person|student|Noah'}]
	assert _call(graph, 'search', text = 'student') == [{'id': 'person|student|Noah'}]
	assert _call(graph, 'search', text = 'room') == [
		{'id': 'place|room', 'definition': 'A room inside a building.'},
		{'id': 'place|room|laboratory', 'definition': 'A room for scientific work.'}
	]
	assert _call(graph, 'search', text = 'teaches') == [{'id': 'person|teacher', 'definition': 'A person who teaches.'}]
	assert _call(graph, 'search', text = 'missing') == []
	assert _call(graph, 'search', text = ' ') == []


def test_search_is_limited(tmp_path):
	""" The search returns at most limit results (and never more than max_results), ending with a truncated marker if cut. """
	graph = _school_graph(tmp_path, max_results = 3)

	answer = _call(graph, 'search', text = 'p', limit = 2)

	assert [entry['id'] for entry in answer[:-1]] == ['person', 'person|student|Noah']
	assert answer[-1]['truncated'] is True
	assert len(_call(graph, 'search', text = 'p', limit = 10)) == 3 + 1


def test_edges_returns_the_edges_from_and_to_a_node(tmp_path):
	""" Edges going out of and coming into a node are returned, sorted by id, with their relation. """
	graph = _known_ids_graph(tmp_path)

	assert _call(graph, 'edges', index = 'person|student|Noah Kim') == [
		{'id': 'noah_helios', 'src': 'person|student|Noah Kim', 'dst': 'project|Helios Solar Car', 'relation': 'works_on|leads'},
		{'id': 'noah_rhs', 'src': 'person|student|Noah Kim', 'dst': 'organization|school|Riverside High School', 'relation': 'studies_at'}
	]
	assert [e['id'] for e in _call(graph, 'edges', index = 'project|Helios Solar Car')] == ['noah_helios', 'priya_helios']
	assert _call(graph, 'edges', index = 'award|Science Prize') == []
	assert _call(graph, 'edges', index = 'person|student') is None
	assert _call(graph, 'edges', index = 'missing') is None


def test_edges_can_be_filtered_by_a_relation_and_its_descendants(tmp_path):
	""" A relation filter includes the relations under it in the hierarchy (works_on includes works_on|leads). """
	graph = _known_ids_graph(tmp_path)

	assert [e['id'] for e in _call(graph, 'edges', index = 'project|Helios Solar Car', relation = 'works_on')] == ['noah_helios', 'priya_helios']
	assert [e['id'] for e in _call(graph, 'edges', index = 'project|Helios Solar Car', relation = 'works_on|leads')] == ['noah_helios']
	assert _call(graph, 'edges', index = 'project|Helios Solar Car', relation = 'works') == []


def test_edges_are_limited(tmp_path):
	""" Edges are limited to max_results, ending with a truncated marker if cut. """
	graph = _known_ids_graph(tmp_path, max_results = 1)

	answer = _call(graph, 'edges', index = 'person|student|Noah Kim')

	assert [e['id'] for e in answer[:-1]] == ['noah_helios']
	assert answer[-1]['truncated'] is True


def test_relations_for_includes_inherited_relations(tmp_path):
	""" A concept takes part in the relations declared for it or for any of its ancestors, as src, dst or both. """
	graph = _relationships_graph(tmp_path)

	answer = _call(graph, 'relations_for', concept = 'person|student')

	assert [(e['id'], e['as']) for e in answer] == [
		('employs', 'dst'), ('knows', 'both'), ('studies_at', 'src'), ('works_on', 'src'), ('works_on|leads', 'src')
	]
	assert answer[2] == {
		'id': 'studies_at', 'src': 'person|student', 'dst': 'organization|school', 'as': 'src', 'definition': 'A student studies at a school.'
	}


def test_relations_for_without_inheritance(tmp_path):
	""" Without inheritance, only the relations declared exactly for the concept are returned. A more general concept does not take
	part in the relations of its descendants.
	"""
	graph = _relationships_graph(tmp_path)

	assert [e['id'] for e in _call(graph, 'relations_for', concept = 'person|student', inherited = False)] == ['studies_at']
	assert [e['id'] for e in _call(graph, 'relations_for', concept = 'person|student', inherited = 'false')] == ['studies_at']
	assert [e['id'] for e in _call(graph, 'relations_for', concept = 'person')] == ['employs', 'knows', 'works_on', 'works_on|leads']
	assert _call(graph, 'relations_for', concept = 'vehicle') == []


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
