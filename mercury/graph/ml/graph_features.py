# Imports
import warnings
from itertools import product
from typing import Union, List
from mercury.graph.core.base import BaseClass
from mercury.graph.core import Graph
from mercury.graph.core.spark_interface import pyspark_installed

# Pyspark imports
if pyspark_installed:
    from pyspark.sql import (
        functions as F,
        Window as W,
        DataFrame,
        SparkSession
    )
    from pyspark.sql.types import (
        ByteType, ShortType, IntegerType, LongType,
        FloatType, DoubleType, DecimalType
    )


# Main class to be fitted
class GraphFeatures(BaseClass):
    """Generate features from neighboring nodes.

        Args:
            attributes (str or List[str], optional):
                The node attributes used to generate features. These strings
                must be valid column names in the graph's vertices'. If None,
                all columns except for 'id' are used. Default is None.
            agg_funcs (str or List[str], optional):
                The aggregation function(s) to apply. Supported values are:
                - "sum"
                - "min"
                - "max"
                - "avg"
                - "wavg"
                Default is "avg".
            order (int, optional):
                The order of neighbors to compute (e.g., 1 for immediate
                neighbors, 2 for neighbors of neighbors, etc.). It must be a
                positive integer. Default is 1.
            verify (bool, optional):
                Whether to validate the provided parameters before executing
                the algorithm. Default is False.
            checkpoint (bool, optional):
                Whether to use Spark checkpointing to persist intermediate
                results. Default is False.
            checkpoint_dir (str, optional):
                The directory to store checkpoint files if checkpointing is
                enabled. Required if `checkpoint=True`. Default is None.
            spark (SparkSession, optional):
                The active Spark session. Required if `checkpoint=True`.
                Default is None.

        Notes:
            - The `order` parameter specifies the depth of the neighborhood
            considered  during aggregation.
            - If `wavg` is specified in `agg_funcs`, the `edges` DataFrame must
            include a 'weight' column. Weighted averages are computed as the
            product of attribute values and edge weights, normalized by the
            total weight.
            - Loops back to oneself are excluded (e.g., 0 -> 1 -> 0).

        Examples:
            >>> g = Graph(data=edges, nodes=vertices, keys={"directed": False})
            >>> gf = GraphFeatures(
            ...     attributes=["feature1", "feature2"],  # Valid names in `vertices`
            ...     agg_funcs=["min", "max", "avg"]
            ... )
            >>> gf.fit(g)  # Adds `node_features_` attribute to `gf`
            >>> gf.node_features_.show(5)  # Display new graph features
        """

    def __init__(
            self,
            attributes: Union[str, List[str]] = None,
            agg_funcs: Union[str, List[str]] = 'avg',
            order: int = 1,
            verify: bool = False,
            checkpoint: bool = False,
            checkpoint_dir: str = None,
            spark: SparkSession = None,
    ):
        self.attributes = attributes
        self.agg_funcs = agg_funcs
        self.order = order
        self.verify = verify
        self.checkpoint = checkpoint
        self.checkpoint_dir = checkpoint_dir
        self.spark = spark

    def __str__(self):
        pass

    # Aggregate messages from neighbors
    def fit(self, g: Graph):
        """Fit the GraphFeatures object to generate graph-based features.

        Args:
            g (Graph): A mercury graph object (mercury.graph.core.graph.Graph).

        Returns:
            (self): Fitted self with 'node_features_' attribute (or raises an
                error).
        """

        # Get parameters
        edges = g.graphframe.edges
        vertices = g.graphframe.vertices
        attributes = self.attributes
        agg_funcs = self.agg_funcs
        order = self.order
        verify = self.verify
        checkpoint = self.checkpoint
        checkpoint_dir = self.checkpoint_dir
        spark = self.spark

        # Dictionary that maps agg_funcs to sql functions
        _agg_dict = {
            'sum': F.sum,
            'min': F.min,
            'max': F.max,
            'avg': F.avg,
            'wavg': F.sum
        }

        # Verify attributes
        if attributes is None:
            attributes = [col for col in vertices.columns if col != 'id']
        elif isinstance(attributes, str):
            attributes = [attributes]
        else:
            msg = 'attributes must be a list of strings.'
            assert isinstance(attributes, list), msg
            msg = 'All items in attributes must be strings.'
            assert all(isinstance(item, str) for item in attributes), msg
            msg = 'All items in attributes must exist in vertices.'
            assert all(item in vertices.columns for item in attributes), msg
            msg = 'attributes must only contain attributes ("id" was detected).'
            assert 'id' not in attributes, msg

        # Verify aggregation functions
        agg_funcs = [agg_funcs] if isinstance(agg_funcs, str) else agg_funcs
        msg = (
            'Invalid aggregation function. Please provide one or more of the following '
            'valid options: "sum", "min", "max", "avg" or "wavg".'
        )
        assert all([func in _agg_dict.keys() for func in agg_funcs]), msg

        # Verify vertices
        verify and self._verify_vertices(vertices)

        # Verify edges
        verify and self._verify_edges(edges)

        # Verify checkpoint configuration and Spark session integrity
        if checkpoint:
            assert checkpoint_dir is not None, (
                'checkpoint_dir must be provided when checkpoint is True.'
            )
            assert spark is not None, (
                'spark must be provided when checkpoint is True.'
            )
            assert isinstance(checkpoint_dir, str), (
                'Invalid type for checkpoint_dir: expected str (a valid path), but got'
                f' {type(checkpoint_dir).__name__} instead.'
            )
            assert isinstance(spark, SparkSession), (
                'Invalid type for spark: expected SparkSession instance, but got '
                f'{type(spark).__name__} instead.'
            )

        # Fetch neighbors
        neighs = self._get_neighbors(
            edges,
            order,
            checkpoint,
            checkpoint_dir,
            spark
        )

        # Fetch neighbors' attributes
        ret = (
            neighs
            .join(
                other=(
                    vertices
                    .select(
                        F.col('id').alias('neigh'),
                        *attributes
                    )
                ),
                on='neigh',
                how='left'
            )
        )

        # Temporarily assign columns if user is calculating weighted averages
        if 'wavg' in agg_funcs:
            ret = ret.select(
                F.expr('*'),
                *[(F.col(x) * F.col('weight')).alias('w_' + x)
                  for x in attributes]
            )

        # Combine functions and attributes
        _agg = list(product(agg_funcs, attributes))

        # Apply all functions to all attributes
        ret = (
            ret
            .groupBy('id')
            .agg(
                *[
                    _agg_dict[k](x).alias('_'.join([x, k]))
                    for (k, x) in _agg if k != 'wavg'
                ],
                *[
                    _agg_dict[k]('w_' + x).alias('_'.join([x, 'wavg']))
                    for (k, x) in _agg if k == 'wavg'
                ]
            )
        )

        # Return result
        self.node_features_ = ret
        return self

    # Check vertices integrity
    def _verify_vertices(self, vertices: DataFrame):
        """Validates the integrity of the 'vertices' DataFrame for graph
           processing. This function verifies the presence of an 'id' column,
           ensures that the 'id' column contains unique values, checks that
           all other columns contain numeric data types only, and identifies
           any null values in non-'id' columns.

        Args:
            vertices : DataFrame
                A PySpark DataFrame representing vertices in a graph.

        Returns:
            None
        """

        # Check type
        msg = 'vertices must be a PySpark DataFrame.'
        assert isinstance(vertices, DataFrame), msg

        # Check if id column exists
        msg = "Column 'id' not listed in vertices."
        assert 'id' in vertices.columns, msg

        # Assert unique IDs
        ids_duplicated = (
            vertices
            .select(
                F.count('id').over(
                    W.partitionBy('id')
                ).alias('count')
            )
            .where(F.col('count') > 1)
            .limit(1)
            .count()
        )
        msg = 'vertices contains duplicated IDs.'
        assert ids_duplicated == 0, msg

        # Numeric Types
        numeric_types = (
            ByteType, ShortType,
            IntegerType, LongType,
            FloatType, DoubleType, DecimalType
        )

        # Check for nulls (dict where key=col_name and value=null_count)
        nulls_dict = (
            vertices
            .select(
                *[
                    F.count(F.when(F.col(c).isNull(), c)).alias(c)
                    for c in vertices.columns if c != 'id'
                ]
            )
            .collect()[0]
            .asDict()
        )

        # Check for nulls and data types every column in the DataFrame
        for field in vertices.schema.fields:
            col_name = field.name

            # Skip column with IDs
            if col_name == 'id':
                continue
            col_type = type(field.dataType)
            col_nulls = nulls_dict[col_name]

            # Data type check
            assert (
                col_type in numeric_types
            ), f"Non-numeric values found in column '{col_name}'."

            # Nulls check
            if col_nulls > 0:
                warnings.warn(
                    f"Column '{col_name}' contains {col_nulls} null values"
                )

    # Check edges' integrity
    def _verify_edges(self, edges: DataFrame):
        """Validates the integrity of the 'edges' DataFrame for graph
           processing. This function verifies the presence of 'src' and 'dst'
           columns, ensures that each pair (src, dst) is unique, confirms the
           graph is undirected, and if a 'weight' column exists, verifies it
           has a numeric data type.

        Args:
            edges : DataFrame
                A PySpark DataFrame representing edges in a graph.

        Returns:
            None
        """

        # Check type
        msg = 'edges must be a PySpark DataFrame.'
        assert isinstance(edges, DataFrame), msg

        # Assert edges
        msg = 'Expected column "{}" not in edges'
        assert 'src' in edges.columns, msg.format('src')
        assert 'dst' in edges.columns, msg.format('dst')

        # Assert unique pairs
        pairs_duplicated = (
            edges
            .groupBy('src', 'dst')
            .count()
            .where(F.col('count') > 1)
            .count()
        )
        msg = 'edges contains {} duplicated src-dst pairs.'
        assert pairs_duplicated == 0, msg.format(pairs_duplicated)

        # Assert undirected
        pairs_mirrored = (
            edges
            .select('src', 'dst')
            .unionByName(
                edges
                .where(F.col('src') != F.col('dst'))  # Drop self-loops
                .select(
                    F.col('dst').alias('src'),
                    F.col('src').alias('dst')
                )
            )
            .groupBy('src', 'dst')
            .count()
            .where(F.col('count') > 1)
            .count()
        )
        msg = 'edges has mirrored edges. Directed graphs are not yet supported!'
        assert pairs_mirrored == 0, msg

        # Assert weight dtype
        if 'weight' in edges.columns:
            msg = 'Column "weight" must be a float or an int. Received {} instead.'
            dtype = dict(edges.dtypes)['weight']
            assert dtype in (
                'float', 'double', 'tinyint', 'smallint', 'int', 'bigint'
            ), msg.format(dtype)

    # Fetches all the neighbors of each node in edges
    def _get_neighbors(
        self,
        edges: DataFrame,
        order: int = 1,
        checkpoint: bool = False,
        checkpoint_dir: str = None,
        spark: SparkSession = None,
    ):
        """Fetch all the neighbors of each node in a graph up to specific
           order.

        Args:
            edges : DataFrame
                A Spark DataFrame containing the edges of the graph. It must
                contain the columns 'src' and 'dst' corresponding to source
                and destination nodes, respectively. An optional 'weight'
                column can be included; if not present, it is assumed to be 1.
            order : int, optional
                The order of neighbors to compute (e.g., 1 for immediate
                neighbors, 2 for neighbors of neighbors, etc.). It must be a
                positive integer. Default is 1.
            checkpoint : bool, optional
                Whether to use Spark checkpointing to persist intermediate
                results. Default is False.
            checkpoint_dir : str, optional,
                The directory to store checkpoint files if checkpointing is
                enabled. Required if `checkpoint=True`. Default is None.
            spark : SparkSession, optional
                The active Spark session. Required if `checkpoint=True`.
                Default is None.

        Returns:
            DataFrame
                A Spark DataFrame with the columns:
                - 'id': The node ID.
                - 'neigh': The ID of a neighboring node.
                - 'weight': The computed weight of the edge connecting 'id' to
                'neigh', normalized by the total weight of all edges
                originating from 'id'.

        Notes:
            - Self-loops are removed when calculating weighted aggregations.
        """
        # Add weight column if necessary
        if 'weight' not in edges.columns:
            edges = edges.withColumn('weight', F.lit(1))

        # Assert order
        assert isinstance(order, int), 'order must be an integer.'
        assert order > 0, 'order must be an integer greater than 0.'
        if order > 2:
            warnings.warn(
                f"order={order} may cause the process to be slow."
            )

        # Fetch 1st-degree neighbors (preserve self-loops for weighted degree)
        ret = (
            edges
            .unionByName(
                edges
                .select(
                    F.col('dst').alias('src'),
                    F.col('src').alias('dst'),
                    'weight'
                )
            )
            # Get weights (accounting for self-loops)
            .select(
                F.col('src').alias('id'),
                F.col('dst').alias('neigh'),
                (
                    F.col('weight')
                    / F.sum('weight').over(
                        W.partitionBy(F.col('src'))
                    )
                ).alias('weight')
            )
            # Drop self-loops AFTER calculating weights
            .where(F.col('id') != F.col('neigh'))
        )

        # checkpoint result
        if checkpoint:
            spark.sparkContext.setCheckpointDir(checkpoint_dir)
            ret = ret.checkpoint()

        # Fetch n-degree neighbors
        for _ in range(1, order):
            ret_tmp = (
                ret.select(
                    F.col('id'),
                    F.col('neigh').alias('o1_neigh'),
                    F.col('weight').alias('o1_weight')
                )
                .join(
                    other=ret.select(
                        F.col('id').alias('o1_neigh'),
                        F.col('neigh').alias('o2_neigh'),
                        F.col('weight').alias('o2_weight')
                    ),
                    on='o1_neigh',
                    how='left'
                )
                # Drop paths back to self
                .where(F.col('id') != F.col('o2_neigh'))
                .select(
                    F.col('id'),
                    F.col('o2_neigh').alias('neigh'),
                    (
                        F.col('o1_weight') * F.col('o2_weight')
                    ).alias('weight')
                )
            )
            # checkpoint result
            if checkpoint:
                ret = ret_tmp.checkpoint()
            else:
                ret = ret_tmp
        # Return
        return ret
