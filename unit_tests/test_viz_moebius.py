import json, os, pytest

import pandas as pd

from mercury.graph.core.graph import Graph
import mercury.graph.viz as viz


def toy_datasets():
    data = {
        'src':    ['Alice', 'Bob', 'Alice', 'Eve', 'Diana', 'Charlie', 'Frank', 'Bob', 'Grace', 'Alice'],
        'dst':    ['Bob', 'Charlie', 'Diana', 'Frank', 'Eve', 'Grace', 'Grace', 'Eve', 'Diana', 'Frank'],
        'weight': [10, 15, 5, 20, 12, 8, 7, 14, 10, 25],
        'cost':   [1, 1, 0.5, 1.5, 1, 1, 1, 1, 1, 2]
    }

    node_data = {
        'id':   ['Alice', 'Bob', 'Charlie', 'Diana', 'Eve', 'Frank', 'Grace'],
        'role': ['Manager', 'Engineer', 'Engineer', 'HR', 'Manager', 'Technician', 'Technician'],
        'age':  [34, 28, 30, 25, 40, 35, 29]
    }

    return pd.DataFrame(data), pd.DataFrame(node_data)


def test_moebius():
    edges, nodes = toy_datasets()
    G = Graph(edges, nodes = nodes)
    M = viz.Moebius(G)

    bak_HTML = viz.moebius.HTML
    viz.moebius.HTML = None
    with pytest.raises(ImportError):
        X = viz.Moebius(G)

    viz.moebius.HTML = bak_HTML

    assert M.G is G

    assert str(M).startswith('Moebius')

    ec = M.node_or_edge_config()

    assert type(ec) == dict and len(ec) == 2
    assert type(ec['color_palette'])   == dict and len(ec['color_palette'])   == 0
    assert type(ec['size_thresholds']) == list and len(ec['size_thresholds']) == 0

    ec = M.node_or_edge_config(text_is = 'one', color_is = 'two', colors = {'lo' : '#cc6633'},
                               size_is = 'three', size_range = [1, 2], size_scale = 'sqrt')

    assert type(ec) == dict and len(ec) == 6
    assert type(ec['color_palette'])   == dict and len(ec['color_palette'])   == 1
    assert type(ec['size_thresholds']) == list and len(ec['size_thresholds']) == 2

    assert ec['label']           == 'one'
    assert ec['color']           == 'two'
    assert ec['color_palette']   == {'lo' : '#cc6633'}
    assert ec['size']            == 'three'
    assert ec['size_thresholds'] == [1, 2]
    assert ec['scale']           == 'sqrt'

    with pytest.raises(AssertionError):
        ec = M.node_or_edge_config(size_is = 'three', size_range = [])

    with pytest.raises(AssertionError):
        ec = M.node_or_edge_config(size_is = 'three', size_scale = 'tan')

    jj = M._pd_to_json_format(edges)

    assert type(jj) == list and len(jj) == 10

    M.show()


def check_key(jj, ky, neighbors, n_nodes, n_edges, degree, dim_n, dim_e):
    oo = json.loads(jj)
    assert type(oo) == dict and len(oo) == 2

    nodes = oo['nodes']

    assert type(nodes) == list and len(nodes) == n_nodes

    for node in nodes:
        assert type(node) == dict and len(node) == dim_n
        assert type(node['id']) == str
        assert type(node['count']) == int
        assert type(node['_int_id']) == int

        if node['id'] == ky:
            assert node['count'] == degree

    edges = oo['links']

    ids = set([node['id'] for node in nodes])

    for nei in neighbors:
        assert nei in ids

    assert type(edges) == list and len(edges) == n_edges

    for edge in edges:
        assert type(edge) == dict and len(edge) == dim_e
        assert type(edge['source']) == str
        assert type(edge['target']) == str
        assert type(edge['weight']) == int
        assert type(edge['_int_id']) == int

        assert (edge['source'] in ids) and (edge['target'] in ids)

        if n_edges == degree:
            assert (edge['source'] == ky) != (edge['target'] == ky)


def test_moebius_callbacks():
    edges, nodes = toy_datasets()
    G = Graph(edges, nodes = nodes)
    M = viz.moebius.MoebiusAnywidget(G)

    assert M.use_spark is False
    assert os.path.exists('%s/moebius.js' % M.front_pat)
    assert os.path.exists('%s/moebius.svg.html' % M.front_pat)
    assert os.path.exists('%s/moebius.css' % M.front_pat)
    assert type(M._int_id_map) == dict
    assert 'Charlie' in M._int_id_map

    # 'src':    ['Alice', 'Bob',     'Alice', 'Eve',   'Diana', 'Charlie', 'Frank', 'Bob', 'Grace', 'Alice']
    # 'dst':    ['Bob',   'Charlie', 'Diana', 'Frank', 'Eve',   'Grace',   'Grace', 'Eve', 'Diana', 'Frank']
    check_key(M['Alice'],   'Alice',   ['Bob', 'Diana', 'Frank'],     4, 3, 3, 5, 5)

    pd = M.G.nodes_as_pandas()
    assert pd.shape == nodes.shape
    pd = M.G.edges_as_pandas()
    assert pd.shape == edges.shape

    check_key(M['Bob'],     'Bob',     ['Alice', 'Charlie', 'Eve'],   4, 3, 3, 5, 5)
    check_key(M['Charlie'], 'Charlie', ['Bob', 'Grace'],              3, 2, 2, 5, 5)
    check_key(M['Diana'],   'Diana',   ['Alice', 'Eve', 'Grace'],     4, 3, 3, 5, 5)
    check_key(M['Eve'],     'Eve',     ['Frank', 'Diana', 'Bob'],     4, 3, 3, 5, 5)
    check_key(M['Frank'],   'Frank',   ['Eve', 'Grace', 'Alice'],     4, 3, 3, 5, 5)
    check_key(M['Grace'],   'Grace',   ['Charlie', 'Frank', 'Diana'], 4, 3, 3, 5, 5)

    jj = M._get_adjacent_nodes_moebius('Alice', depth = 4)

    check_key(jj, 'Frank', ['Alice', 'Bob', 'Charlie', 'Diana', 'Eve', 'Grace'], 7, 10, 3, 5, 5)

    kk = M._get_adjacent_nodes_moebius('Alice', limit = 5, depth = 2)
    oo = json.loads(kk)
    assert type(oo) == dict and len(oo) == 2
    kk_nodes = oo['nodes']
    assert type(kk_nodes) == list and len(kk_nodes) < 7

    pd = M.G.nodes_as_pandas()
    assert pd.shape == nodes.shape
    pd = M.G.edges_as_pandas()
    assert pd.shape == edges.shape

    spark_edges = G.edges_as_dataframe()
    spark_nodes = G.nodes_as_dataframe()

    H = Graph(spark_edges, nodes = spark_nodes)
    N = viz.moebius.MoebiusAnywidget(H)

    check_key(N['Alice'],   'Alice',   ['Bob', 'Diana', 'Frank'],     4, 3, 3, 5, 5)

    df = M.G.nodes_as_dataframe()
    assert (df.count(), len(df.columns)) == nodes.shape
    df = M.G.edges_as_dataframe()
    assert (df.count(), len(df.columns)) == edges.shape

    check_key(N['Bob'],     'Bob',     ['Alice', 'Charlie', 'Eve'],   4, 3, 3, 5, 5)
    check_key(N['Charlie'], 'Charlie', ['Bob', 'Grace'],              3, 2, 2, 5, 5)
    check_key(N['Diana'],   'Diana',   ['Alice', 'Eve', 'Grace'],     4, 3, 3, 5, 5)
    check_key(N['Eve'],     'Eve',     ['Frank', 'Diana', 'Bob'],     4, 3, 3, 5, 5)
    check_key(N['Frank'],   'Frank',   ['Eve', 'Grace', 'Alice'],     4, 3, 3, 5, 5)
    check_key(N['Grace'],   'Grace',   ['Charlie', 'Frank', 'Diana'], 4, 3, 3, 5, 5)

    df = M.G.nodes_as_dataframe()
    assert (df.count(), len(df.columns)) == nodes.shape
    df = M.G.edges_as_dataframe()
    assert (df.count(), len(df.columns)) == edges.shape

    jj = N._get_adjacent_nodes_moebius('Alice', depth = 4)

    check_key(jj, 'Frank', ['Alice', 'Bob', 'Charlie', 'Diana', 'Eve', 'Grace'], 7, 10, 3, 5, 5)

    kk = N._get_adjacent_nodes_moebius('Alice', limit = 5, depth = 2)
    oo = json.loads(kk)
    assert type(oo) == dict and len(oo) == 2
    kk_nodes = oo['nodes']
    assert type(kk_nodes) == list and len(kk_nodes) < 7

    N._get_one_level_subgraph_graphframes('Alice', _testing = True)


# test_moebius()
# test_moebius_callbacks()

# print('Done.')
