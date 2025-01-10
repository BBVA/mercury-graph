from mercury.graph.core import Graph
from mercury.graph.core.base import BaseClass
from mercury.graph.core.spark_interface import pyspark_installed

from pandas import DataFrame
from networkx import normalized_laplacian_matrix
from networkx.algorithms.community import modularity as nx_modularity

from sklearn.cluster import KMeans
from numpy.linalg import eigh
from numpy import asarray
import numpy as np

if pyspark_installed:
    from pyspark.sql import functions as F
    from pyspark.ml.clustering import PowerIterationClustering

class SpectralClustering(BaseClass):
    """
    Implementation of the spectral clustering algorithm which detect communities inside a graph.

    Contributed by Gibran Gabriel Otazo Sanchez.

    Args:
        n_clusters (int): The number of clusters that you want to detect.
        random_state (int): Seed for reproducibility
        mode (str): Calculation mode. Pass 'networkx' for using pandas + networkx or
                    'spark' for spark + graphframes
        max_iterations (int): Max iterations parameter (only used if mode==spark)
    """

    def __init__(
        self, n_clusters=2, mode="networkx", max_iterations=10, random_state=0
    ):
        self.n_clusters = n_clusters
        self.mode = mode
        self.max_iterations = max_iterations
        self.random_state = random_state

        if self.mode not in ("networkx", "spark"):
            raise ValueError("Error: Mode must be either 'networkx' or 'spark'")

    def __str__(self):
        base_str = super().__str__()

        # Check if the object has been fitted (fitting creates the `labels_` attribute)
        if hasattr(self, "labels_"):
            extra_str = [
                f"",
                f"Cluster assignments are available in attribute `labels_`",
                f"Modularity: {self.modularity_}",
            ]
            return "\n".join([base_str] + extra_str)
        else:
            return base_str

    def fit(self, graph: Graph):
        """
        Find the optimal clusters of a given graph. The function returns nothing, but saves the clusters and
        the modularity in the object self.

        Args:
            graph (Graph): A mercury graph structure.

        Returns:
            (self): Fitted self (or raises an error)

        """
        if self.mode == "networkx":
            self._fit_networkx(graph)
        else:
            self._fit_spark(graph)

        return self

    def _fit_networkx(self, graph: Graph):
        """
        Spectral clustering but using networkx (local mode implementation)

        Args:
            graph (Graph): A mercury graph structure.

        Returns:
            (self): Fitted self (or raises an error)
        """
        gnx = graph.networkx.to_undirected()

        L = normalized_laplacian_matrix(gnx).todense()

        if not np.allclose(L, L.T):
            raise ValueError("Normalized Laplacian matrix of the undirected graph should be symmetric")

        w, v = eigh(L)

        U = v[:, : self.n_clusters]
        U = asarray(U)

        kmeans = KMeans(
            n_clusters=self.n_clusters, random_state=self.random_state, n_init="auto"
        ).fit(U)

        self.labels_ = DataFrame({"node_id": gnx.nodes(), "cluster": kmeans.labels_})

        cluster_nodes = self.labels_.groupby("cluster")["node_id"].apply(list)
        self.modularity_ = nx_modularity(gnx, cluster_nodes)

    def _fit_spark(self, graph: Graph):
        """
        Spectral clustering but using pyspark

        Args:
            graph (Graph): A mercury graph structure.

        Returns:
            (self): Fitted self (or raises an error)
        """

        graph_frames_graph = graph.graphframe

        pic = PowerIterationClustering(k=self.n_clusters, weightCol="weight")
        pic.setMaxIter(self.max_iterations)

        # Node ids can be strings, with this we ensure IDs are always converted to
        # integers (needed by PowerIterationClustering)
        vertices_mapping = graph_frames_graph.vertices.withColumn(
            "idx", F.monotonically_increasing_id()
        )

        mapped_node_ids = (
            graph_frames_graph.edges.join(
                vertices_mapping, graph_frames_graph.edges.src == vertices_mapping.id
            )
            .withColumnRenamed("idx", "src_mapped")
            .drop("id", "src")
        )

        mapped_node_ids = (
            mapped_node_ids.join(
                vertices_mapping, mapped_node_ids.dst == vertices_mapping.id
            )
            .withColumnRenamed("idx", "dst_mapped")
            .drop("id", "dst")
            .withColumnRenamed("src_mapped", "src")
            .withColumnRenamed("dst_mapped", "dst")
        )
        assignments = pic.assignClusters(mapped_node_ids)

        self.labels_ = (
            vertices_mapping.join(assignments, vertices_mapping.idx == assignments.id)
            .drop(assignments.id)
            .selectExpr(["id as node_id", "cluster"])
        )

        self.modularity_ = self._spark_modularity(
            graph_frames_graph.edges, graph_frames_graph.degrees
        )

    def _spark_modularity(self, edges, degrees, resolution=1):
        """Computes modularity using the same approximation as networkx:
        https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.community.quality.modularity.html
        """

        edge_nb = edges.count()
        q = []

        for i in range(self.n_clusters):
            nids = self.labels_[self.labels_.cluster == i]
            nodeids = [row["node_id"] for row in nids.select("node_id").collect()]

            l_c = edges.filter(
                edges.src.isin(nodeids) & edges.dst.isin(nodeids)
            ).count()

            k_c = (
                nids.join(degrees.withColumnRenamed("id", "node_id"), on="node_id")
                .select(F.sum("degree"))
                .collect()[0][0]
            )

            qi = (l_c / edge_nb) - resolution * (k_c / (2 * edge_nb)) ** 2
            q.append(qi)

        return np.sum(q)
