import inspect

import pandas as pd
import networkx as nx

from mercury.graph.core.spark_interface import SparkInterface, pyspark_installed, graphframes_installed, dgl_installed


class NodeIterator:
    """
    Iterator class for iterating over the nodes in a `mercury.graph.core.Graph`.

    This is returned by the `nodes` property of the `mercury.graph.core.Graph` class.

    Args:
        graph: The `mercury.graph.core.Graph` object to iterate over.

    Usage:

    ```python
    g = mg.Graph(data)
    for node in g.nodes:
        print(node)
    ```
    """

    def __init__(self, graph):
        self.graph = graph
        self.ix = -1
        if graph._as_networkx is not None:
            self.key_list = list(graph._as_networkx.nodes.keys())
        else:
            self.key_list = [row['id'] for row in graph.graphframe.vertices.select('id').collect()]


    def __iter__(self):
        return self


    def __next__(self):
        self.ix += 1

        if self.ix >= len(self.key_list):
            raise StopIteration

        ky = self.key_list[self.ix]

        if self.graph._as_networkx is not None:
            d = self.graph._as_networkx.nodes[ky].copy()
            d['id'] = ky

            return d

        g = self.graph.graphframe
        return g.vertices.filter(g.vertices.id == ky).first().asDict()


class EdgeIterator:
    """
    Iterator class for iterating over the edges in a `mercury.graph.core.Graph`.

    This is returned by the `edges` property of the `mercury.graph.core.Graph` class.

    Args:
        graph: The `mercury.graph.core.Graph` object to iterate over.

    Usage:

    ```python
    g = mg.Graph(data)
    for edge in g.edges:
        print(edge)
    ```
    """

    def __init__(self, graph):
        self.graph = graph
        self.ix = -1
        if graph._as_networkx is not None:
            self.key_list = list(graph._as_networkx.edges.keys())
        else:
            self.key_list = [(row['src'], row['dst']) for row in graph.graphframe.edges.collect()]


    def __iter__(self):
        return self


    def __next__(self):
        self.ix += 1

        if self.ix >= len(self.key_list):
            raise StopIteration

        ky = self.key_list[self.ix]

        if self.graph._as_networkx is not None:
            d = self.graph._as_networkx.edges[ky].copy()
            d['src'] = ky[0]
            d['dst'] = ky[1]

            return d

        g = self.graph.graphframe
        return g.edges.filter((g.edges.src == ky[0]) & (g.edges.dst == ky[1])).first().asDict()


class Graph:
    """ This is the main class in mercury.graph.

    This class seamlessly abstracts the underlying technology used to represent the graph. You can create a graph passing the following
    objects to the constructor:

    - A pandas DataFrame containing edges (with a keys dictionary to specify the columns and possibly a nodes DataFrame)
    - A pyspark DataFrame containing edges (with a keys dictionary to specify the columns and possibly a nodes DataFrame)
    - A networkx graph
    - A graphframes graph

    Bear in mind that the graph object is immutable. This means that you can't modify the graph object once it has been created. If you
    want to modify it, you have to create a new graph object.

    The graph object provides:

    - Properties to access the graph in different formats (networkx, graphframes, dgl)
    - Properties with metrics and summary information that are calculated on demand and technology independent.
    - It is inherited by other graph classes in mercury-graph providing ML algorithms such as graph embedding, visualization, etc.

    Using this class from the other classes in mercury-graph:

    The other classes in mercury-graph define models or functionalities that are based on graphs. They use a Scikit-learn-like API to
    interact with the graph object. This means that the graph object is passed to the class constructor and the class follow the
    Scikit-learn conventions. It is recommended to follow the same conventions when creating your own classes to work with mercury-graph.

    The conventions can be found here:

    - [Scikit API](https://scikit-learn.org/stable/developers/develop.html#apis-of-scikit-learn-objects)
    - [On scikit conventions](https://scikit-learn.org/stable/glossary.html)

    Args:
        data (pd.DataFrame, nx.Graph or pyspark.sql.DataFrame): The data to create the graph from. 
            It can be a pandas DataFrame, a networkx Graph, a pyspark DataFrame, or a Graphframe. 
            In case it already contains a graph (networkx or graphframes), the keys and nodes arguments are ignored.
        keys (dict): A dictionary with keys to specify the columns in the data DataFrame. The keys are:

            - 'src': The name of the column with the source node.
            - 'dst': The name of the column with the destination node.
            - 'id': The name of the column with the node id.
            - 'weight': The name of the column with the edge weight.
            - 'directed': A boolean to specify if the graph is directed. (Only for pyspark DataFrames)

            When the keys argument is not provided or the key is missing, the default values are:

            - 'src': 'src'
            - 'dst': 'dst'
            - 'id': 'id'
            - 'weight': 'weight'
            - 'directed': True

        nodes (pd.DataFrame): A pandas DataFrame or a pyspark DataFrame with the nodes data. (Only when `data` is pandas or pyspark DataFrame and with the
            same type as `data`) If not given, the nodes are inferred from the edges DataFrame.
    """
    def __init__(self, data = None, keys = None, nodes = None):
        self._as_networkx = None
        self._as_graphframe = None
        self._as_dgl = None
        self._degree = None
        self._in_degree = None
        self._out_degree = None
        self._closeness_centrality = None
        self._betweenness_centrality = None
        self._pagerank = None
        self._connected_components = None
        self._nodes_colnames = None
        self._edges_colnames = None

        self._number_of_nodes = 0
        self._number_of_edges = 0
        self._node_ix = 0
        self._is_directed = False
        self._is_weighted = False

        self._init_values = {k: v for k, v in locals().items() if k in inspect.signature(self.__init__).parameters}

        if type(data) == pd.core.frame.DataFrame:
            self._from_pandas(data, nodes, keys)
            return

        if isinstance(data, nx.Graph):      # This is the most general case, including: ...Graph, ...DiGraph and ...MultiGraph
            self._from_networkx(data)
            return

        spark_int = SparkInterface()

        if pyspark_installed and graphframes_installed:
            if type(data) in spark_int.type_spark_dataframe:
                self._from_dataframe(data, nodes, keys)
                return

            if type(data) == spark_int.type_graphframe:
                self._from_graphframes(data)
                return

        raise ValueError('Invalid input data. (Expected: pandas DataFrame, a networkx Graph, a pyspark DataFrame, a graphframes Graph.)')


    def __str__(self):
        txt = []
        txt.append('mercury.graph.core.Graph with %d nodes and %d edges.' % (self._number_of_nodes, self._number_of_edges))
        txt.append('  is_directed:    %s' % self._is_directed)
        txt.append('  is_weighted:    %s' % self._is_weighted)
        txt.append('  has_networkx:   %s' % (self._as_networkx is not None))
        txt.append('  has_graphframe: %s' % (self._as_graphframe is not None))
        txt.append('  has_dgl:        %s' % (self._as_dgl is not None))

        return '\n'.join(txt)


    def __repr__(self):
        return 'Graph(%s)' % ', '.join('%s = %s' % (k, v) for k, v in self._init_values.items())


    @property
    def nodes(self):
        """
        Returns an iterator over all the nodes in the graph.

        Returns:
            (NodeIterator): An iterator that yields each node in the graph.
        """
        return NodeIterator(self)


    @property
    def edges(self):
        """
        Returns an iterator over the edges in the graph.

        Returns:
            (EdgeIterator): An iterator object that allows iterating over the edges in the graph.
        """
        return EdgeIterator(self)


    @property
    def networkx(self):
        """
        Returns the graph representation as a NetworkX graph.

        If the graph has not been converted to NetworkX format yet, it will be converted and cached for future use.

        Returns:
            (networkx.Graph): The graph representation as a NetworkX graph.
        """
        if self._as_networkx is None:
            self._as_networkx = self._to_networkx()

        return self._as_networkx


    @property
    def graphframe(self):
        """
        Returns the graph as a GraphFrame.

        If the graph has not been converted to a GraphFrame yet, it will be converted and cached for future use.

        Returns:
            (GraphFrame): The graph represented as a GraphFrame.
        """
        if self._as_graphframe is None:
            self._as_graphframe = self._to_graphframe()

        return self._as_graphframe


    @property
    def dgl(self):
        """
        Returns the graph as a DGL graph.

        If the graph has not been converted to a DGL graph yet, it will be converted and cached for future use.

        Returns:
            (dgl.DGLGraph): The graph represented as a DGL graph.
        """
        if self._as_dgl is None:
            self._as_dgl = self._to_dgl()

        return self._as_dgl


    @property
    def degree(self):
        """
        Returns the degree of each node in the graph as a Python dictionary.
        """
        if self._degree is None:
            self._degree = self._calculate_degree()
        return self._degree


    @property
    def in_degree(self):
        """
        Returns the in-degree of each node in the graph as a Python dictionary.
        """
        if self._in_degree is None:
            self._in_degree = self._calculate_in_degree()
        return self._in_degree


    @property
    def out_degree(self):
        """
        Returns the out-degree of each node in the graph as a Python dictionary.
        """
        if self._out_degree is None:
            self._out_degree = self._calculate_out_degree()
        return self._out_degree


    @property
    def closeness_centrality(self):
        """
        Returns the closeness centrality of each node in the graph as a Python dictionary.
        """
        if self._closeness_centrality is None:
            self._closeness_centrality = self._calculate_closeness_centrality()
        return self._closeness_centrality


    @property
    def betweenness_centrality(self):
        """
        Returns the betweenness centrality of each node in the graph as a Python dictionary.
        """
        if self._betweenness_centrality is None:
            self._betweenness_centrality = self._calculate_betweenness_centrality()
        return self._betweenness_centrality


    @property
    def pagerank(self):
        """
        Returns the PageRank of each node in the graph as a Python dictionary.
        """
        if self._pagerank is None:
            self._pagerank = self._calculate_pagerank()
        return self._pagerank


    @property
    def connected_components(self):
        """
        Returns the connected components of each node in the graph as a Python dictionary.
        """
        if self._connected_components is None:
            self._connected_components = self._calculate_connected_components()
        return self._connected_components


    @property
    def nodes_colnames(self):
        """
        Returns the column names of the nodes DataFrame.
        """
        if self._nodes_colnames is None:
            self._nodes_colnames = self._calculate_nodes_colnames()
        return self._nodes_colnames


    @property
    def edges_colnames(self):
        """
        Returns the column names of the edges DataFrame.
        """
        if self._edges_colnames is None:
            self._edges_colnames = self._calculate_edges_colnames()
        return self._edges_colnames


    @property
    def number_of_nodes(self):
        """
        Returns the number of nodes in the graph.

        Returns:
            (int): The number of nodes in the graph.
        """
        return self._number_of_nodes


    @property
    def number_of_edges(self):
        """
        Returns the number of edges in the graph.

        Returns:
            (int): The number of edges in the graph.
        """
        return self._number_of_edges


    @property
    def is_directed(self):
        """
        Returns True if the graph is directed, False otherwise.

        Note: 
            Graphs created using graphframes are always directed. The way around it is to add the reverse edges to the graph.
            This can be done by creating the Graph with pyspark DataFrame() and defining a key 'directed' set as False in the `dict`
            argument. Otherwise, the graph will be considered directed even if these reversed edges have been created by other means
            this class cannot be aware of.
        """
        return self._is_directed


    @property
    def is_weighted(self):
        """
        Returns True if the graph is weighted, False otherwise.

        A graph is considered weight if it has a column named 'weight' in the edges DataFrame or the column has a different name and that
        name is passed in the `dict` argument as the 'weight' key.
        """
        return self._is_weighted


    def nodes_as_pandas(self):
        """
        Returns the nodes as a pandas DataFrame.

        If the graph is represented as a networkx graph, the nodes are extracted from it. Otherwise, the graphframes graph will be used.
        This dataset may differ from possible pandas DataFrame passed to the constructor in the column names and order. The column used
        as the node id is always named 'id'.
        """
        if self._as_networkx is not None:
            nodes_data = self._as_networkx.nodes(data = True)
            nodes_df   = pd.DataFrame([(node, attr) for node, attr in nodes_data], columns = ['id', 'attributes'])

            attrs_df = pd.json_normalize(nodes_df['attributes'])

            return pd.concat([nodes_df.drop('attributes', axis = 1), attrs_df], axis = 1)

        return self.graphframe.vertices.toPandas()


    def edges_as_pandas(self):
        """
        Returns the edges as a pandas DataFrame.

        If the graph is represented as a networkx graph, the edges are extracted from it. Otherwise, the graphframes graph will be used.
        This dataset may differ from possible pandas DataFrame passed to the constructor in the column names and order. The columns used
        as the source and destination nodes are always named 'src' and 'dst', respectively.
        """
        if self._as_networkx is not None:
            edges_data = self._as_networkx.edges(data = True)
            edges_df   = pd.DataFrame([(src, dst, attr) for src, dst, attr in edges_data], columns = ['src', 'dst', 'attributes'])

            attrs_df   = pd.json_normalize(edges_df['attributes'])

            return pd.concat([edges_df.drop('attributes', axis = 1), attrs_df], axis = 1)

        return self.graphframe.edges.toPandas()


    def nodes_as_dataframe(self):
        """
        Returns the nodes as a pyspark DataFrame.

        If the graph is represented as a graphframes graph, the nodes are extracted from it. Otherwise, the nodes are converted from the
        pandas DataFrame representation. The column used as the node id is always named 'id', regardless of the original column name passed
        to the constructor.
        """
        if self._as_graphframe is not None:
            return self._as_graphframe.vertices

        return SparkInterface().spark.createDataFrame(self.nodes_as_pandas())


    def edges_as_dataframe(self):
        """
        Returns the edges as a pyspark DataFrame.

        If the graph is represented as a graphframes graph, the edges are extracted from it. Otherwise, the edges are converted from the
        pandas DataFrame representation. The columns used as the source and destination nodes are always named 'src' and 'dst',
        respectively, regardless of the original column names passed to the constructor.
        """
        if self._as_graphframe is not None:
            return self._as_graphframe.edges

        return SparkInterface().spark.createDataFrame(self.edges_as_pandas())


    def _from_pandas(self, edges, nodes, keys):
        """ This internal method extends the constructor to accept a pandas DataFrame as input.

        It takes the constructor arguments and does not return anything. It sets the internal state of the object.
        """
        if keys is None:
            src = 'src'
            dst = 'dst'
            id  = 'id'
            weight = 'weight'
            directed = True
        else:
            src = keys.get('src', 'src')
            dst = keys.get('dst', 'dst')
            id  = keys.get('id', 'id')
            weight = keys.get('weight', 'weight')
            directed = keys.get('directed', True)

        if directed:
            g = nx.DiGraph()
        else:
            g = nx.Graph()

        if weight in edges.columns:
            edges = edges.rename(columns = {weight: 'weight'})

        for _, row in edges.iterrows():
            attr = row.drop([src, dst]).to_dict()
            g.add_edge(row[src], row[dst], **attr)

        if nodes is not None:
            for _, row in nodes.iterrows():
                attr = row.drop([id]).to_dict()
                g.add_node(row[id], **attr)

        self._from_networkx(g)


    def _from_dataframe(self, edges, nodes, keys):
        """ This internal method extends the constructor to accept a pyspark DataFrame as input.

        It takes the constructor arguments and does not return anything. It sets the internal state of the object.
        """
        if keys is None:
            src = 'src'
            dst = 'dst'
            id  = 'id'
            weight = 'weight'
            directed = True
        else:
            src = keys.get('src', 'src')
            dst = keys.get('dst', 'dst')
            id  = keys.get('id', 'id')
            weight = keys.get('weight', 'weight')
            directed = keys.get('directed', True)

        edges = edges.withColumnRenamed(src, 'src').withColumnRenamed(dst, 'dst')

        if weight in edges.columns:
            edges = edges.withColumnRenamed(weight, 'weight')

        if nodes is not None:
            nodes = nodes.withColumnRenamed(id, 'id').dropDuplicates(['id'])
        else:
            src_nodes = edges.select('src').distinct().withColumnRenamed('src', 'id')
            dst_nodes = edges.select('dst').distinct().withColumnRenamed('dst', 'id')
            nodes = src_nodes.union(dst_nodes).distinct()

        g = SparkInterface().graphframes.GraphFrame(nodes, edges)

        if not directed:
            edges = g.edges

            other_columns = [col for col in edges.columns if col not in ('src', 'dst')]
            reverse_edges = edges.select(edges['dst'].alias('src'), edges['src'].alias('dst'), *other_columns)
            all_edges     = edges.union(reverse_edges).distinct()

            g = SparkInterface().graphframes.GraphFrame(nodes, all_edges)

        self._from_graphframes(g, directed)


    def _from_networkx(self, graph):
        """ This internal method extends the constructor to accept a networkx graph as input.

        It takes the constructor arguments and does not return anything. It sets the internal state of the object.
        """
        self._as_networkx = graph
        self._number_of_nodes = len(graph.nodes)
        self._number_of_edges = len(graph.edges)
        self._is_directed = nx.is_directed(graph)
        self._is_weighted = 'weight' in self.edges_colnames


    def _from_graphframes(self, graph, directed = True):
        """ This internal method extends the constructor to accept a graphframes graph as input.

        It takes the constructor arguments and does not return anything. It sets the internal state of the object.
        """
        self._as_graphframe = graph
        self._number_of_nodes = graph.vertices.count()
        self._number_of_edges = graph.edges.count()
        self._is_directed = directed
        self._is_weighted = 'weight' in self.edges_colnames


    def _to_networkx(self):
        """ This internal method handles the logic of a property. It returns the networkx graph that already exists
        or converts it from the graphframes graph if not."""

        if self._is_directed:
            g = nx.DiGraph()
        else:
            g = nx.Graph()

        for _, row in self.edges_as_pandas().iterrows():
            attr = row.drop(['src', 'dst']).to_dict()
            g.add_edge(row['src'], row['dst'], **attr)

        for _, row in self.nodes_as_pandas().iterrows():
            attr = row.drop(['id']).to_dict()
            g.add_node(row['id'], **attr)

        return g


    def _to_graphframe(self):
        """ This internal method handles the logic of a property. It returns the graphframes graph that already exists
        or converts it from the networkx graph if not."""

        nodes = self.nodes_as_dataframe()
        edges = self.edges_as_dataframe()

        return SparkInterface().graphframes.GraphFrame(nodes, edges)


    def _to_dgl(self):
        """ This internal method handles the logic of a property. It returns the dgl graph that already exists
        or converts it from the networkx graph if not."""

        if dgl_installed:
            dgl = SparkInterface().dgl

            edge_attrs = [c for c in self.edges_colnames if c not in ['src', 'dst']]
            if len(edge_attrs) == 0:
                edge_attrs = None

            node_attrs = [c for c in self.nodes_colnames if c not in ['id']]
            if len(node_attrs) == 0:
                node_attrs = None

            self._as_dgl = dgl.from_networkx(self.networkx, edge_attrs = edge_attrs, node_attrs = node_attrs)

        return self._as_dgl


    def _calculate_degree(self):
        """ This internal method handles the logic of a property. It returns the degree of each node in the graph."""

        if self._as_networkx is not None:
            return dict(self._as_networkx.degree())

        return self._fill_node_zeros({row['id']: row['degree'] for row in self.graphframe.degrees.collect()})


    def _calculate_in_degree(self):
        """ This internal method handles the logic of a property. It returns the in-degree of each node in the graph."""

        if self._as_networkx is not None:
            return dict(self._as_networkx.in_degree())

        return self._fill_node_zeros({row['id']: row['inDegree'] for row in self.graphframe.inDegrees.collect()})


    def _calculate_out_degree(self):
        """ This internal method handles the logic of a property. It returns the out-degree of each node in the graph."""

        if self._as_networkx is not None:
            return dict(self._as_networkx.out_degree())

        return self._fill_node_zeros({row['id']: row['outDegree'] for row in self.graphframe.outDegrees.collect()})


    def _fill_node_zeros(self, d):
        """
        This internal method fills the nodes that are not in the dictionary with a zero value. This make the output obtained from
        graphframes consistent with the one from networkx.
        """
        for node in self.nodes:
            if node['id'] not in d:
                d[node['id']] = 0

        return d


    def _calculate_closeness_centrality(self):
        """
        This internal method handles the logic of a property. It returns the closeness centrality of each node in the graph as
        a Python dictionary.
        """
        if self._as_networkx is not None:
            return nx.closeness_centrality(self._as_networkx)

        nodes = [row['id'] for row in self.graphframe.vertices.select('id').collect()]
        paths = self.graphframe.shortestPaths(landmarks = nodes)
        expr  = SparkInterface().pyspark.sql.functions.expr
        sums  = paths.withColumn('sums', expr('aggregate(map_values(distances), 0, (acc, x) -> acc + x)'))

        cc = sums.withColumn('cc', (self.number_of_nodes - 1)/sums['sums']).select('id', 'cc')

        return {row['id']: row['cc'] for row in cc.collect()}


    def _calculate_betweenness_centrality(self):
        """
        This internal method handles the logic of a property. It returns the betweenness centrality of each node in the graph as a Python
        dictionary. NOTE: This method converts the graph to a networkx graph to calculate the betweenness centrality since the algorithm
        is too computationally expensive to use on large graphs.
        """
        return nx.betweenness_centrality(self.networkx)


    def _calculate_pagerank(self):
        """
        This internal method handles the logic of a property. It returns the PageRank of each node in the graph as a Python dictionary.
        """
        if self._as_networkx is not None:
            return nx.pagerank(self._as_networkx)

        pr = self.graphframe.pageRank(resetProbability = 0.15, tol = 0.01).vertices

        return {row['id']: row['pagerank'] for row in pr.collect()}


    def _calculate_connected_components(self):
        """
        This internal method handles the logic of a property. It returns the connected components of each node in the graph as a Python
        dictionary.
        """
        if self._as_networkx is not None:
            if self._is_directed:
                G = self._as_networkx.to_undirected()
            else:
                G = self._as_networkx

            graphs = (G.subgraph(c) for c in nx.connected_components(G))
            cc = dict()
            for i, graph in enumerate(graphs):
                n = graph.number_of_nodes()
                for nid in graph.nodes:
                    cc[nid] = {'cc_id' : i, 'cc_size' : n}

            return cc

        graphs = self.graphframe.connectedComponents(algorithm = 'graphx')
        cc_size = graphs.select('id', 'component').groupBy('component').count()
        cc_all = graphs.select('id', 'component').join(cc_size, 'component', how = 'left_outer')

        cc = dict()
        for row in cc_all.collect():
            cc[row['id']] = {'cc_id' : row['component'], 'cc_size' : row['count']}

        return cc


    def _calculate_nodes_colnames(self):
        """ This internal method returns the column names of the nodes DataFrame. """

        if self._as_networkx is not None:
            l = ['id']
            l.extend(list(self._as_networkx.nodes[list(self._as_networkx.nodes.keys())[0]].keys()))

            return l

        return self.graphframe.vertices.columns


    def _calculate_edges_colnames(self):
        """ This internal method returns the column names of the edges DataFrame. """

        if self._as_networkx is not None:
            l = ['src', 'dst']
            l.extend(list(self._as_networkx.edges[list(self._as_networkx.edges.keys())[0]].keys()))
            return l

        return self.graphframe.edges.columns
