from mercury.graph.core import Graph
from mercury.graph.core.base import BaseClass
from mercury.graph.embeddings.spark_node2vec import udf_select_element_2

from mercury.graph.core.spark_interface import pyspark_installed, graphframes_installed

if pyspark_installed:
    import pyspark.sql.functions as f
    from pyspark.sql import Window

    if graphframes_installed:
        from graphframes import GraphFrame
        from graphframes.lib import AggregateMessages


class SparkRandomWalker(BaseClass):

    def __init__(self, num_epochs=10, batch_size=1, n_sampling_edges=None):
        """
        Class to perform random walks from a specific source_id node within a given Graph

        Args:
            num_epochs (int): Number of epochs. This is the total number of steps the iteration goes through.
            batch_size (int): This forces caching the random walks computed so far and breaks planning each time this number of epochs
                is reached. The default value is a high number to avoid this entering at all. In really large jobs, you may want to
                set this parameter to avoid possible overflows even if it can add some extra time to the process. Note that with a high
                number of epochs and nodes resource requirements for the active part of your random walks can be high. This allows to
                "cache a continue" so to say.
            n_sampling_edges (int): by setting this parameter you can limit at each timestep the number of new paths opened from each node.
                This is useful when the graph contains nodes with very high out-degree, where running the algorithm several epochs is
                not feasible. When using this parameter, the graph will consider only at most `edge_sampling` outgoing edges at each
                epoch for each path. If the last node of the path contains more than `edge_sampling` the selected edges are sampled
                using its weight.
        """
        self.num_epochs = num_epochs
        self.batch_size = batch_size
        self.n_sampling_edges = n_sampling_edges

    def __str__(self):
        base_str = super().__str__()

        # Check if the object has been fitted (fitting creates `paths` attribute)
        if hasattr(self, "paths_"):
            extra_str = [f"", f"Random walk paths are available in attribute `paths_`."]
            return "\n".join([base_str] + extra_str)
        else:
            return base_str

    def fit(self, G: Graph, source_id):
        """
        Perform random walks from a specific source_id node within a given Graph

        Args:
            G (mercury.graph Graph asset): A `mercury.graph` Graph
            source_id (int/str/list): the source vertex or list for vertices to start the random walks.

        Returns:
            (self): Fitted self (or raises an error)

        Attribute `paths_` contains a Spark Dataframe with a columns `random_walks` containing an array of the elements
        of the path walked and another column with the corresponding weights. The weights represent the probability of
        following that specific path starting from source_id.
        """
        self.paths_ = self._run_rw(G, source_id)

        return self

    def _run_rw(self, G: Graph, source_id):
        self._start_rw(G, source_id)

        for i in range(self.num_epochs):

            aux_vert = self._update_state_with_next_step(i)
            self.gx = GraphFrame(aux_vert, self.gx.edges)

            if (i + 1) % self.batch_size == 0:
                old_aux_vert = aux_vert
                aux_vert = AggregateMessages.getCachedDataFrame(aux_vert)
                old_aux_vert.unpersist()

        paths = (
            self.gx.vertices.select(
                f.col("new_rw_acc_path").alias("random_walks"),
                f.col("new_rw_acc_weight").alias("weights"),
            )
            .filter(f.col("random_walks").isNotNull())
            .persist()
        )

        self.gx.vertices.unpersist()
        self.gx.edges.unpersist()

        return paths

    def _start_rw(self, G: Graph, source_id):
        aux_vert = (
            G.graphframe.vertices.groupBy(f.col("id"))
            .agg(f.collect_list(f.col("id")).alias("tmp_rw_aux_acc_path"))
            .withColumn("in_sample", f.col("id").isin(source_id))
            .withColumn(
                "new_rw_acc_path",
                f.when(f.col("in_sample"), f.col("tmp_rw_aux_acc_path")).otherwise(
                    f.lit(None)
                ),
            )
            .withColumn("new_rw_curr_id", f.col("id"))
            .drop("tmp_rw_aux_acc_path", "in_sample")
        ).filter(f.col("new_rw_acc_path").isNotNull())
        aux_vert = aux_vert.withColumn("new_rw_acc_weight", f.array(f.lit(1.0)))

        w_ind_edge = Window.partitionBy("src")

        df_edges_cumsum = G.graphframe.edges.withColumn(
            "new_rw_total_sum", f.sum("weight").over(w_ind_edge)
        )

        aux_edges = (
            df_edges_cumsum.withColumn(
                "new_rw_norm_sum",
                f.col("weight") / f.col("new_rw_total_sum"),
            ).select(
                f.col("src"),
                f.col("dst"),
                f.col("weight"),
                f.col("new_rw_norm_sum"),
            )
        ).persist()

        self.gx = GraphFrame(aux_vert, aux_edges)

    def _update_state_with_next_step(self, i):
        candidate_vert_col = self.gx.vertices.columns

        candidate_vert = self.gx.vertices.withColumnRenamed(
            "new_rw_curr_id", "new_rw_prev_id"
        )

        if self.n_sampling_edges:
            out_edges = self._sample_edges()
        else:
            out_edges = self.gx.edges

        candidate_vert_with_edges = candidate_vert.join(
            out_edges,
            f.col("new_rw_prev_id") == f.col("src"),
            "left",
        )

        selected_next_step = (
            candidate_vert_with_edges.withColumn(
                "new_rw_acc_path",
                udf_select_element_2(f.col("new_rw_acc_path"), f.col("dst")),
            )
            .withColumn(
                "new_rw_acc_weight",
                udf_select_element_2(
                    f.col("new_rw_acc_weight"),
                    f.col("new_rw_acc_weight")[f.size("new_rw_acc_weight") - f.lit(1)]
                    * f.col("new_rw_norm_sum"),
                ),
            )
            .withColumn("new_rw_curr_id", f.col("new_rw_acc_path").getItem(i + 1))
            .select(candidate_vert_col)
        )

        return selected_next_step

    def _sample_edges(self):

        sampled_edges = self.gx.edges

        # For each edge, Generate random number and multiply by the edge weight
        sampled_edges = sampled_edges.withColumn("rnd_e", f.rand())
        sampled_edges = sampled_edges.withColumn(
            "weighted_rnd", f.col("rnd_e") * f.col("new_rw_norm_sum")
        )

        # Sort by weighted_rnd and select the top edge_sampling edges
        win_steps = Window.partitionBy("src").orderBy(f.col("weighted_rnd").desc())
        sampled_edges = sampled_edges.withColumn(
            "row_number", f.row_number().over(win_steps)
        )
        sampled_edges = sampled_edges.filter(
            f.col("row_number") <= self.n_sampling_edges
        )
        return sampled_edges
