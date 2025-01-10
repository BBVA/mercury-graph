import importlib.util, json, os

import anywidget
import pathlib
import traitlets

import pandas as pd

from mercury.graph.core.spark_interface import SparkInterface

display, HTML = None, None
if importlib.util.find_spec('IPython.display') is not None:
    from IPython.display import display, HTML


class MoebiusAnywidget(anywidget.AnyWidget):
    """
    MoebiusAnywidget class for visualizing graphs creating an anywidget that uses JavaScript and HTML.
    Note: It is recommended to use wrapper class Moebius.

    Args:
        G (Graph):          The graph to be visualized.
        initial_id (str): The id of the node to start the visualization.
        initial_depth (int): The initial depth of the graph (starting with `initial_id` as 0) to be shown.
        node_config (dict): A node configuration dictionary created by `node_config()`.
        edge_config (dict): An edge configuration dictionary created by `edge_config()`.

    Attributes:
        use_spark (bool):   Flag indicating if Spark is used.
        front_pat (str):    Path to the frontend resources.
        _int_id_map (dict): A dictionary mapping node IDs to integer IDs.
    """

    def __init__(self, G, initial_id = None, initial_depth = 1, node_config = None, edge_config = None):
        if display is None or HTML is None:
            raise ImportError('IPython is not installed')

        self.G = G
        self.use_spark = self.G._as_networkx is None
        self.front_pat = os.path.dirname(os.path.dirname(os.path.realpath(__file__))) + '/frontend'
        self._int_id_map = {node['id'] : i for i, node in enumerate(self.G.nodes)}

        if initial_id is None:
            initial_id = next(iter(self._int_id_map))

        initial_json = self._get_adjacent_nodes_moebius(initial_id, depth = initial_depth)

        if node_config is None:
            node_config = self.node_or_edge_config()

        if edge_config is None:
            edge_config = self.node_or_edge_config()

        logo_svg = "`" + pathlib.Path(self.front_pat + '/moebius.svg.html').read_text() + "`"

        js_moebius_call = f"""
            (function(el) {{
                moebius({initial_json}, {node_config}, {edge_config}, {str(self.G.is_directed).lower()}, {logo_svg});
            }})(el);
        """

        self._esm = f"""
            import {{ min, max }} from 'https://esm.sh/d3-array@3';
            import {{ drag }} from 'https://esm.sh/d3-drag@3';
            import {{ forceX, forceY, forceCollide, forceSimulation, forceLink, forceManyBody, forceCenter }} from 'https://esm.sh/d3-force@3';
            import {{ scaleOrdinal, scaleLinear, scalePow, scaleSqrt, scaleLog }} from 'https://esm.sh/d3-scale@4';
            import {{ schemeCategory10 }} from 'https://esm.sh/d3-scale-chromatic@3';
            import {{ select, selectAll }} from 'https://esm.sh/d3-selection@3';
            import {{ transition }} from 'https://esm.sh/d3-transition@3';
            import {{ zoom }} from 'https://esm.sh/d3-zoom@3';
            const d3 = {{ min, max, select, selectAll, forceSimulation, forceLink, forceManyBody, forceCenter, drag, scaleOrdinal, schemeCategory10, scaleOrdinal, scaleLinear, scalePow, scaleSqrt, scaleLog, zoom, forceX, forceY, forceCollide, transition }};

            export default {{
                initialize({{ model }}) {{
                    // Set up shared state or event handlers.
                    return () => {{
                    // Optional: Called when the widget is destroyed.
                    }} 
                }},
                render({{ model, el }}) {{
                    // Render the widget's view into the el HTMLElement.
                    {pathlib.Path(self.front_pat + '/moebius.js').read_text()}
                    {js_moebius_call}
                    return () => {{
                    // Optional: Called when the view is destroyed.
                    }}
                }}
            }}
            """

        self._css = pathlib.Path(self.front_pat + '/moebius.css').read_text()

        super().__init__()


    expandNode_params = traitlets.Dict({}).tag(sync=True)
    searchNewNode_params = traitlets.Dict({}).tag(sync=True)

    # Observers that trigger Python code execution when frontend registers calls to expandNode and searchNewNode
    @traitlets.observe("expandNode_params")
    def _on_change_expandNode_params(self, change):
        try:
            my_value = self._get_adjacent_nodes_moebius(change["new"]["nodeID"], change["new"]["nodeLimit"], change["new"]["depth"])
            self.send({"result": my_value})
        except:
            self.send({"result": ""})

    @traitlets.observe("searchNewNode_params")
    def _on_change_searchNewNode_params(self, change):
        try:
            my_value = self._get_adjacent_nodes_moebius(change["new"]["nodeID"], change["new"]["nodeLimit"], change["new"]["depth"])
            self.send({"result": my_value, "searched_nodeID": change["new"]["nodeID"]})
        except:
            self.send({"result": ""})


    def __str__(self):
        """
        Convert the object via str()
        """

        return 'Moebius(%s)' % str(self.G)


    def __getitem__(self, item):
        """
        Add support for the [] operator.
        """

        return self._get_adjacent_nodes_moebius(item)


    def node_or_edge_config(self, text_is = None, color_is = None, colors = None, size_is = None, size_range = None, size_scale = 'linear'):
        """
        Create a `node_config` or `edge_config` configuration dictionary for `show()` in an understandable way.

        Args:
            text_is (str): The node/edge attribute to be displayed as text. Use the string `ìd` to draw the node id (regardless of the
                column having another name) or any valid node attribute name.
            color_is (str): A categorical node/edge attribute that can be represented as a color. This will also enable a legend interface
                where categories can be individually shown or hidden.
            colors (dict): The colors for each category defined as a dictionary. The keys are possible outcomes of category.
                The values are html RGB strings. E.g., .draw(category = 'size', colors = {'big' : '#c0a080', 'small' : '#a0c080'})
                where 'big' and 'small' are possible values of the category 'size'.
            size_is (str): The node attribute to be displayed as the size of the nodes. Use the string `id` to set the node id (regardless
                of the column having another name) or any valid node attribute name. See the options in the Moebius configuration menu to
                set minimum, maximum sizes, linear or logarithmic scale, etc.
            size_range (List of two numbers): Combined with edge_label, this parameter controls the values in the variable that
                correspond to the minimum and maximum displayed sizes. The values below or equal the first value will be displayed with the
                base radius (that depends on the zoom) and the values above or equal to the second value will be shown with the maximum
                radius.
            size_scale ('linear', 'power', 'sqrt' or 'log'): Combined with edge_label, the scale used to convert the value in the variable
                to the displayed radius.

        Returns:
            (dict): The node configuration dictionary
        """

        config = {}

        if text_is is not None:
            config['label'] = text_is

        if color_is is not None:
            config['color'] = color_is

        if colors is not None:
            config['color_palette'] = colors
        else:
            config['color_palette'] = {}

        if size_is is None:
            config['size_thresholds'] = []
        else:
            config['size'] = size_is

            if size_range is None:
                config['size_thresholds'] = []
            else:
                assert type(size_range) == list and len(size_range) == 2
                config['size_thresholds'] = size_range

            if size_scale != 'linear':
                assert size_scale in {'power', 'sqrt', 'log'}

            config['scale'] = size_scale

        return config


    def _get_adjacent_nodes_moebius(self, node_id, limit = 20, depth = 1):
        """
        This is the callback function used to interact with the Moebius JS library. Each time you deploy a node in the graph, this
        function is called to get the adjacent nodes and edges.

        The expected return is a JSON string with the following format:

        json = {
            'nodes': [
                {'id' : ..., 'count' : ..., '_int_id' : ...},
                {'id' : ..., 'count' : ..., '_int_id' : ...}
            ],
            'links': [
                {'source' : ..., 'target' : ..., '_int_id' : ...},
                {'source' : ..., 'target' : ..., '_int_id' : ...}
            ]
        },
        where 'count' is the degree of the given node, and '_int_id' is a
        unique integer identifier for the given node or edge.

        Args:
            node_id (str): The id of the node to get the adjacent nodes.
            limit (int): The maximum number of nodes to be returned.
            depth (int): The depth of the graph to be returned.

        Returns:
            A JSON string with the adjacent nodes and edges.
        """

        if self.use_spark:
            nodes_df, edges_df = self._get_one_level_subgraph_graphframes(node_id)
            N = nodes_df.count()

        else:
            nodes_df, edges_df = self._get_one_level_subgraph_networkx(node_id)
            N = len(nodes_df)

        d = 1
        expanded = set([node_id])

        while N < limit and d < depth:
            if self.use_spark:
                next = set(nodes_df.select('id').rdd.flatMap(lambda x: x).collect())
                for id in next:
                    if id not in expanded:
                        expanded.add(id)

                        next_nodes, next_edges = self._get_one_level_subgraph_graphframes(id)
                        nodes_df = nodes_df.union(next_nodes).distinct()
                        edges_df = edges_df.union(next_edges).distinct()

                        N = nodes_df.count()
                        if N >= limit:
                            break
            else:
                next = set(nodes_df.id)
                for id in next:
                    if id not in expanded:
                        expanded.add(id)

                        next_nodes, next_edges = self._get_one_level_subgraph_networkx(id)
                        nodes_df = pd.concat([nodes_df, next_nodes]).drop_duplicates().reset_index(drop = True)
                        edges_df = pd.concat([edges_df, next_edges]).drop_duplicates().reset_index(drop = True)

                        N = len(nodes_df)
                        if N >= limit:
                            break

            d += 1

        if self.use_spark:
            json_final = {
                'nodes': json.loads(nodes_df.toPandas().to_json(orient = 'records')),
                'links': json.loads(edges_df.toPandas().to_json(orient = 'records'))
            }

        else:
            json_final = {
                'nodes': json.loads(nodes_df.to_json(orient = 'records')),
                'links': json.loads(edges_df.to_json(orient = 'records'))
            }

        return json.dumps(json_final)


    def _get_one_level_subgraph_graphframes(self, node_id, _testing=False):
        """
        Get the one-level subgraph for a given node ID using GraphFrames.

        Args:
            node_id (str): The ID of the node for which to get the one-level subgraph.

        Returns:
            tuple: A tuple containing two Spark DataFrames:
                - nodes_df: DataFrame with columns 'id', 'count', '_int_id', and any other node attributes.
                - edges_df: DataFrame with columns 'source', 'target', '_int_id' the edges connecting the nodes in the subgraph.
        """

        sql      = SparkInterface().pyspark.sql
        spark    = SparkInterface().spark
        F        = sql.functions
        LongType = sql.types.LongType

        graph = self.G.graphframe

        edges_df = graph.edges.filter((graph.edges.src == node_id) | (graph.edges.dst == node_id))

        N = len(self._int_id_map)
        int_id_map_broadcast = spark.sparkContext.broadcast(self._int_id_map)

        def edge_int_id(src, dst):
            int_id_map = int_id_map_broadcast.value
            return int_id_map[src] + N*(int_id_map[dst] + 1)

        edge_int_id_udf = F.udf(edge_int_id, LongType())

        edges_df = edges_df.withColumn('_int_id', edge_int_id_udf(F.col('src'), F.col('dst')))
        edges_df = edges_df.withColumnRenamed('src', 'source').withColumnRenamed('dst', 'target')

        order = ['source', 'target', '_int_id']
        for col in edges_df.columns:
            if col not in order:
                order.append(col)
        edges_df = edges_df.select(order)

        node_ids = edges_df.select('source').union(edges_df.select('target')).distinct()
        nodes_df = node_ids.join(graph.vertices, node_ids.source == graph.vertices.id, 'inner').select(graph.vertices['*'])

        degrees  = graph.degrees
        # Edges are duplicated in undirected graphframes -> Fix degree
        if not self.G.is_directed:
            degrees = degrees.withColumn('degree', F.ceil(F.col('degree') / 2))
        nodes_df = nodes_df.join(degrees, on = 'id', how = 'left').withColumnRenamed('degree', 'count')

        def node_int_id(id):
            int_id_map = int_id_map_broadcast.value
            return int_id_map[id]

        if _testing:
            key, val = next(iter(self._int_id_map.items()))
            assert node_int_id(key) == val
            assert edge_int_id(key, key) == N*val + N + val

        node_int_id_udf = F.udf(node_int_id, LongType())

        nodes_df = nodes_df.withColumn('_int_id', node_int_id_udf(F.col('id')))

        order = ['id', 'count', '_int_id']
        for col in nodes_df.columns:
            if col not in order:
                order.append(col)
        nodes_df = nodes_df.select(order)

        return nodes_df, edges_df


    def _get_one_level_subgraph_networkx(self, node_id):
        """
        Get the one-level subgraph for a given node ID using Networkx.

        Args:
            node_id (str): The ID of the node for which to get the one-level subgraph.

        Returns:
            tuple: A tuple containing two Pandas DataFrames:
                - nodes_df: DataFrame with columns 'id', 'count', '_int_id', and any other node attributes.
                - edges_df: DataFrame with columns 'source', 'target', '_int_id' the edges connecting the nodes in the subgraph.
        """

        graph = self.G.networkx

        if self.G.is_directed:
            neighbors = set(graph.neighbors(node_id)) | set(graph.predecessors(node_id))
        else:
            # Undirected graphs are symmetric: predecessors == successors (or neighbors)
            neighbors = set(graph.neighbors(node_id))

        neighbors.add(node_id)

        subgraph = graph.subgraph(neighbors)

        # Create nodes DataFrame
        nodes_data = []
        for node in subgraph.nodes(data = True):
            node_id = node[0]
            attributes = node[1].copy()
            attributes['id'] = node_id
            attributes['count'] = graph.degree[node_id]
            attributes['_int_id'] = self._int_id_map[node_id]
            nodes_data.append(attributes)
        nodes_df = pd.DataFrame(nodes_data)

        order = ['id', 'count', '_int_id']
        for col in nodes_df.columns:
            if col not in order:
                order.append(col)
        nodes_df = nodes_df[order]

        # Create edges DataFrame
        edges_data = []
        N = len(self._int_id_map)
        for edge in subgraph.edges(data = True):
            src, dst, attributes = edge
            attributes = attributes.copy()
            attributes['source'] = src
            attributes['target'] = dst
            attributes['_int_id'] = self._int_id_map[src] + N*(self._int_id_map[dst] + 1)
            edges_data.append(attributes)
        edges_df = pd.DataFrame(edges_data)

        order = ['source', 'target', '_int_id']
        for col in edges_df.columns:
            if col not in order:
                order.append(col)
        edges_df = edges_df[order]

        return nodes_df, edges_df


    def _pd_to_json_format(self, df):
        """
        A utility to produced the flavor of JSON expected by the JS library from a pandas DataFrame.

        Usage:
            ```python
            # This simple snippet to convert the whole graph to the expected JSON format.

            edges = self._pd_to_json_format(self.G.edges_as_pandas().rename({'src' : 'source', 'dst' : 'target'}, axis = 1))
            nodes = self._pd_to_json_format(self.G.nodes_as_pandas())

            json_final = {'nodes' : nodes, 'links' : edges}

            return json.dumps(json_final, ensure_ascii=False)
            ```

        Args:
            df (pd.DataFrame): The DataFrame to be converted to JSON.
        """

        df = df.reset_index(drop = True)

        df_json = df.to_json(orient = 'records', force_ascii = True, date_format = 'iso')

        return json.loads(df_json)

class Moebius(MoebiusAnywidget):
    """
    Moebius class for visualizing graphs using an anywidget.

    Usage:
        ```python
        from mercury.graph.viz import Moebius

        G = ... # A graph object
        moebius = Moebius(G)
        moebius.show()
        ```

    Args:
        G (Graph):          The graph to be visualized.
    """

    def __init__(self, G):
        if display is None or HTML is None:
            raise ImportError('IPython is not installed')

        self.G = G


    def _repr_mimebundle_(self, include=None, exclude=None):
        """
        Override display() method to control its execution and avoid errors.
        """
        self.show()


    def show(self, initial_id = None, initial_depth = 1, node_config = None, edge_config = None):
        """
        Start the interactive graph visualization using an anywidget.

        Args:
            initial_id (str): The id of the node to start the visualization.
            initial_depth (int): The initial depth of the graph (starting with `initial_id` as 0) to be shown.
            node_config (dict): A node configuration dictionary created by `node_config()`.
            edge_config (dict): An edge configuration dictionary created by `edge_config()`.
        """
        display(MoebiusAnywidget(self.G, initial_id, initial_depth, node_config, edge_config))
