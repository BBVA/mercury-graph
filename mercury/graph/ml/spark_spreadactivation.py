from typing import Union, List
import itertools

from mercury.graph.core import Graph
from mercury.graph.core.spark_interface import (
    SparkInterface,
    pyspark_installed,
    graphframes_installed,
)
from mercury.graph.core.base import BaseClass

if pyspark_installed:
    import pyspark
    from pyspark.sql import Row
    import pyspark.sql.functions as f
    from pyspark.sql.types import StructField, StructType, StringType, ArrayType

    def _add_new_nodes(acc_nodes, new_nodes):
        if (new_nodes is None) or (len(new_nodes) == 0):
            return acc_nodes
        else:
            new_nodes = list(itertools.chain.from_iterable(new_nodes))
            if acc_nodes is None:
                return new_nodes
            return list(set(acc_nodes + new_nodes))

    udf_add_new_nodes = f.udf(_add_new_nodes, ArrayType(StringType()))

    if graphframes_installed:
        from graphframes import GraphFrame
        from graphframes.lib import AggregateMessages as AM


class SparkSpreadingActivation(BaseClass):
    """
    This class is a model that represents a “word-of-mouth” scenario where a node influences his neighbors, from where
    the influence spreads to other neighbors, and so on.

    At the end of the diffusion process, we inspect the amount of influence received by each node. Using a
    threshold-based technique, a node that is currently not influenced can be declared to be a potential future one,
    based on the influence that has been accumulated.

    The diffusion model is based on Spreading Activation (SPA) techniques proposed in cognitive psychology
    and later used for trust metric computations. For more details, please see paper entitled
    ["Social Ties and their Relevance to Churn in Mobile Telecom Networks"](https://pdfs.semanticscholar.org/3275/3d80adb5ec2d4a974b5d1a872e2c957b263b.pdf)

    Args:
        attribute (str): Column name which will store the amount of influence spread
        spreading_factor (float): Percentage of influence to distribute. Low values favor influence proximity to the source of injection,
            while high values allow the influence to also reach nodes which are further away. It must be a value in the range (0,1).
            Default value is 0.2
        transfer_function (str): Allowed values: "weighted" or "unweighted".
            Once a node decides what fraction of energy to distribute, the next step is to decide what fraction of the energy is transferred
            to each neighbor. This is controlled by the Transfer Function. If "weighted" then the energy distributed along the directed
            edge <X,Y> depends on its relatively weight compared to the sum of weights of all outgoing edges of X. If "unweighted", then
            the energy distributed along the edge <X,Y> is independent of its relatively weight.
        steps (int): Number of steps to perform
        influenced_by (bool): if True, and extra column "influenced_by" is calculated which contains the seed nodes that have spread some
            influence to a given node. When True, the ids of the nodes cannot contain commas ",". Note that seed_nodes will have at least
            their own (remaining) influence
    """

    def __init__(
        self,
        attribute: str = "influence",
        spreading_factor: float = 0.2,
        transfer_function: str = "weighted",
        steps: int = 1,
        influenced_by: bool = False,
    ):
        self.attribute = attribute
        self.spreading_factor = spreading_factor
        self.transfer_function = transfer_function
        self.steps = steps
        self.influenced_by = influenced_by

    def fit(
        self,
        g: Graph,
        seed_nodes: Union[List, "pyspark.sql.DataFrame"],
    ):
        """
        Perform all iterations of spread_activation

        Args:
            g (mercury.graph.core.Graph): A `mercury.graph` Graph object.
            seed_nodes (Union[List, pyspark.sql.DataFrame]): Collection of nodes that are the "seed" or are the source to spread
                the influence. It must be pyspark dataframe with column 'id' or python list

        Returns:
            (self): Fitted self
        """

        # Set seed nodes which are the source of influence
        g = self._set_seed_nodes(g, seed_nodes)

        # Compute degrees
        g = self._compute_degrees(g)

        # Number of iterations specified for spread activation
        for _ in range(0, self.steps, 1):
            g = self._spread_activation_step(
                g,
            )

        # Graph with updated attributes
        self.fitted_graph_ = g
        # Influences as DataFrame
        self.influences_ = self.fitted_graph_.nodes_as_dataframe().select(
            "id", "influence"
        )

        return self

    def _set_seed_nodes(
        self,
        g: Graph,
        seed_nodes: Union[List, "pyspark.sql.DataFrame"] = None,
    ):
        """
        Set seed nodes which are the source of influence using pyspark dataframe.

        Args:
            g (mercury.graph.core.Graph): A `mercury.graph` Graph object.
            seed_nodes (Union[List, pyspark.sql.DataFrame]): Collection of nodes that are the source to spread
                the influence. It must be pyspark dataframe with column 'id' or python list.
        """

        seed_nodes_dataframe = seed_nodes

        # Convert list to dataframe
        if isinstance(seed_nodes, list):
            rdd_list = SparkInterface().spark.sparkContext.parallelize(seed_nodes)
            row_rdd_list = rdd_list.map(lambda x: Row(x))
            field_list = [StructField("id", StringType(), True)]
            schema_list = StructType(field_list)
            seed_nodes_dataframe = SparkInterface().spark.createDataFrame(
                row_rdd_list, schema_list
            )

        # Create column for influence attribute containing 1's
        seed_nodes_dataframe = seed_nodes_dataframe.withColumn(
            self.attribute, f.lit(1.0)
        )
        self.seed_nodes_ = seed_nodes_dataframe

        # Merge to original vertices of graph
        orig_vertices = g.graphframe.vertices.select("id")
        orig_edges = g.graphframe.edges
        new_vertices = orig_vertices.join(
            seed_nodes_dataframe, "id", "left_outer"
        ).na.fill(0)

        # If influenced_by flag is set, then initialize the seed nodes
        if self.influenced_by:
            new_vertices = new_vertices.withColumn(
                "influenced_by",
                f.when(
                    new_vertices[self.attribute] == 1,
                    f.split(new_vertices["id"], pattern=","),
                ).otherwise(f.array().cast("array<string>")),
            )

        # Update graph
        return Graph(GraphFrame(new_vertices, orig_edges))

    def _compute_degrees(self, g: Graph):
        """
        Compute weighted and unweighted in and out degrees in graph. Re-declares graph to add the following
        attributes: inDegree, outDegree, w_inDegree, w_outDegree.

        Args:
            g: graphframe object, network
        """
        g_vertices = g.graphframe.vertices
        g_edges = g.graphframe.edges

        # Get unweighted degrees
        indeg = g.graphframe.inDegrees
        outdeg = g.graphframe.outDegrees

        # Get weighted degrees
        w_indeg = (
            g_edges.groupby("dst").agg(f.sum("weight").alias("w_inDegree"))
        ).selectExpr("dst as id", "w_inDegree as w_inDegree")
        w_outdeg = (
            g_edges.groupby("src").agg(f.sum("weight").alias("w_outDegree"))
        ).selectExpr("src as id", "w_outDegree as w_outDegree")

        # Update vertices attribute
        new_v = g_vertices.join(indeg, "id", "left_outer")
        new_v = new_v.join(outdeg, "id", "left_outer")
        new_v = new_v.join(w_indeg, "id", "left_outer")
        new_v = new_v.join(w_outdeg, "id", "left_outer")
        new_v = new_v.na.fill(0)

        # Update graph
        return Graph(GraphFrame(new_v, g_edges))

    def _spread_activation_step(self, g: Graph):
        """
        One step in the spread activation model.

        Args:
            g: graphframe object, network

        Returns:
            (Graphframe): new network with updated new calculation of attribute in vertices
        """

        # Pass influence/message to neighboring nodes (weighted/unweighted option)
        if self.transfer_function == "unweighted":
            msg_to_src = (AM.src[self.attribute] / AM.src["outDegree"]) * (
                1 - self.spreading_factor
            )
            msg_to_dst = f.when(
                AM.dst["outDegree"] != 0,
                (
                    (AM.src[self.attribute] / AM.src["outDegree"])
                    * self.spreading_factor
                ),
            ).otherwise(
                ((1 / AM.dst["inDegree"]) * AM.dst[self.attribute])
                + (
                    (AM.src[self.attribute] / AM.src["outDegree"])
                    * self.spreading_factor
                )
            )

        elif self.transfer_function == "weighted":
            weight = AM.edge["weight"] / AM.src["w_outDegree"]
            msg_to_src = (AM.src[self.attribute] / AM.src["outDegree"]) * (
                1 - self.spreading_factor
            )
            msg_to_dst = f.when(
                AM.dst["outDegree"] != 0,
                ((AM.src[self.attribute]) * (self.spreading_factor * weight)),
            ).otherwise(
                ((1 / AM.dst["inDegree"]) * AM.dst[self.attribute])
                + ((AM.src[self.attribute]) * (self.spreading_factor * weight))
            )

        # Aggregate messages
        agg = g.graphframe.aggregateMessages(
            f.sum(AM.msg).alias(self.attribute),
            sendToSrc=msg_to_src,
            sendToDst=msg_to_dst,
        )

        # Create a new cached copy of the dataFrame to get new calculated attribute
        cached_new_vertices = AM.getCachedDataFrame(agg)

        if self.influenced_by:
            to_join = g.graphframe.vertices.select(
                "id",
                "inDegree",
                "outDegree",
                "w_inDegree",
                "w_outDegree",
                "influenced_by",
            )
        else:
            to_join = g.graphframe.vertices.select(
                "id", "inDegree", "outDegree", "w_inDegree", "w_outDegree"
            )
        new_cached_new_vertices = cached_new_vertices.join(to_join, "id", "left_outer")
        new_cached_new_vertices = new_cached_new_vertices.na.fill(0)

        # If influenced_by flag is set, compute new seed nodes influencing
        if self.influenced_by:
            new_cached_new_vertices = self._calculate_influenced_by(
                g, new_cached_new_vertices
            )

        # Return graph with new calculated attribute
        return Graph(GraphFrame(new_cached_new_vertices, g.graphframe.edges))

    def _calculate_influenced_by(self, g: Graph, vertices):
        influencing_msg_to_dst = AM.src["influenced_by"]
        agg_influencing = g.graphframe.aggregateMessages(
            f.collect_list(AM.msg).alias("new_influences"),
            sendToDst=influencing_msg_to_dst,
        )
        cached_new_influences = AM.getCachedDataFrame(agg_influencing)

        # Join with current nodes and concatenate new influencing nodes in "influenced_by" column
        vertices = (
            vertices.join(cached_new_influences, "id", "left_outer")
            .withColumn(
                "influenced_by",
                udf_add_new_nodes(f.col("influenced_by"), f.col("new_influences")),
            )
            .drop("new_influences")
        )

        return vertices
