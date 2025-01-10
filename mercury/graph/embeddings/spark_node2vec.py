import logging

from mercury.graph.core import Graph
from mercury.graph.core.base import BaseClass

from mercury.graph.core.spark_interface import (
    SparkInterface,
    pyspark_installed,
    graphframes_installed,
)

if pyspark_installed:
    import pyspark.sql.functions as f
    from pyspark.sql import Window

    from pyspark.sql.types import ArrayType
    from pyspark.sql.types import StringType

    from pyspark.ml.feature import Word2Vec
    from pyspark.ml.feature import Word2VecModel

    def _add_new_element_2(acc_path, next_node):
        return (
            acc_path + [next_node]
            if ((next_node is not None) and (acc_path is not None))
            else acc_path
        )

    udf_select_element_2 = f.udf(_add_new_element_2, ArrayType(StringType()))

    if graphframes_installed:
        from graphframes import GraphFrame
        from graphframes.lib import AggregateMessages


class SparkNode2Vec(BaseClass):

    def __init__(
        self,
        dimension=None,
        sampling_ratio=1.0,
        num_epochs=10,
        num_paths_per_node=1,
        batch_size=1000000,
        w2v_max_iter=1,
        w2v_num_partitions=1,
        w2v_step_size=0.025,
        w2v_min_count=5,
        path_cache=None,
        use_cached_rw=False,
        n_partitions_cache=10,
        load_file=None,
    ):
        """
        Create or reload a SparkNode2Vec embedding mapping the nodes of a graph.

        Args:
            dimension (int): The number of columns in the embedding. See note the notes in `Embeddings` for details. (This parameter will be
                ignored when `load_file` is used.)
            sampling_ratio (float): The proportion from the total number of nodes to be used in parallel at each step (whenever possible).
            num_epochs (int): Number of epochs. This is the total number of steps the iteration goes through. At each step, sampling_ratio
                times the total number of nodes paths will be computed in parallel.
            num_paths_per_node (int): The amount of random walks to source from each node.
            batch_size (int): This forces caching the random walks computed so far and breaks planning each time this number of epochs
                is reached. The default value is a high number to avoid this entering at all. In really large jobs, you may want to
                set this parameter to avoid possible overflows even if it can add some extra time to the process. Note that with a high
                number of epochs and nodes resource requirements for the active part of your random walks can be high. This allows to
                "cache a continue" so to say.
            w2v_max_iter (int): This is the Spark Word2Vec parameter maxIter, the default value is the original default value.
            w2v_num_partitions (int): This is the Spark Word2Vec parameter numPartitions, the default value is the original default value.
            w2v_step_size (float): This is the Spark Word2Vec parameter stepSize, the default value is the original default value.
            w2v_min_count (int): This is the Spark Word2Vec parameter minCount, the default value is the original default value (5). Is the
                minimum number of times that a node has to appear to generate an embedding.
            path_cache (str): Folder where random walks will be stored, the default value is None which entails that random walks will not
                be stored.
            use_cached_rw (bool): Flag that indicates if random walks should be read from disk (hence, they will not be computed again).
                Setting this parameter to True requires a valid path_cache.
            n_partitions_cache (int): Number of partitions that will be used when storing the random walks, to optimize read access.
                The default value is 10.
            load_file (str): (optional) The full path to a parquet file containing a serialized SparkNode2Vec object. This file must be created
                using SparkNode2Vec.save().
        """
        self.dimension = dimension
        self.sampling_ratio = sampling_ratio
        self.num_epochs = num_epochs
        self.num_paths_per_node = num_paths_per_node
        self.batch_size = batch_size
        self.w2v_max_iter = w2v_max_iter
        self.w2v_num_partitions = w2v_num_partitions
        self.w2v_step_size = w2v_step_size
        self.w2v_min_count = w2v_min_count
        self.path_cache = path_cache
        self.use_cached_rw = use_cached_rw
        self.n_partitions_cache = n_partitions_cache
        self.load_file = load_file

        if self.load_file is not None:
            self._load(self.load_file)
            return

    def __str__(self):
        base_str = super().__str__()

        # Check if the object has been fitted (fitting creates `node2vec_` model)
        if hasattr(self, "node2vec_"):
            extra_str = [
                f"",
                f"Random walk paths are available in attribute `paths_`.",
                f"Spark's Word2Vec model fitted on paths_ is available in attribute `node2vec_` through method `model()`.",
            ]
            return "\n".join([base_str] + extra_str)
        else:
            return base_str

    def fit(self, G: Graph):
        """
        Train the embedding by doing random walks.

        Random walk paths are available in attribute `paths_`.

        Args:
            G (mercury.graph.core.Graph): A `mercury.graph` Graph object. The embedding will be created so that each row in the embedding maps
                a node ID in G. (This parameter will be ignored when `load_file` is used.)

        Returns:
            (self): Fitted self (or raises an error)
        """

        if self.path_cache is None:
            if self.use_cached_rw:
                logging.warning(
                    "Wrong options (use_cached_rw and no path_cache). "
                    "Paths will be recomputed."
                )
            self.use_cached_rw = False

        if not self.use_cached_rw:
            paths = (
                self._run_rw(G)
                .withColumn("size", f.size("random_walks"))
                .where(f.col("size") > 1)
                .drop("size")
            )

            if self.path_cache is not None:
                (
                    paths.repartition(self.n_partitions_cache)
                    .write.mode("overwrite")
                    .parquet("%s/block=0" % self.path_cache)
                )

            if self.num_paths_per_node > 1:
                for block_id in range(1, self.num_paths_per_node):
                    new_paths = (
                        self._run_rw(G)
                        .withColumn("size", f.size("random_walks"))
                        .where(f.col("size") > 1)
                        .drop("size")
                    )
                    if self.path_cache is None:
                        paths = paths.unionByName(new_paths)
                    else:
                        (
                            new_paths.repartition(self.n_partitions_cache)
                            .write.mode("overwrite")
                            .parquet("%s/block=%d" % (self.path_cache, block_id))
                        )
                        # With this, we clear the persisted dataframe
                        new_paths.unpersist()

        if self.path_cache is None:
            self.paths_ = paths.persist()
        else:
            self.paths_ = (
                SparkInterface()
                .read_parquet(self.path_cache)
                .drop("block")
                .repartition(self.n_partitions_cache)
                .persist()
            )

        w2v = Word2Vec(
            vectorSize=self.dimension,
            maxIter=self.w2v_max_iter,
            numPartitions=self.w2v_num_partitions,
            stepSize=self.w2v_step_size,
            inputCol="random_walks",
            outputCol="model",
            minCount=self.w2v_min_count,
        )

        self.node2vec_ = w2v.fit(self.paths_)

        return self

    def embedding(self):
        """
        Return all embeddings.

        Returns:
            (DataFrame): All embeddings as a `DataFrame[word: string, vector: vector]`.
        """
        if not hasattr(self, "node2vec_"):
            return

        return self.node2vec_.getVectors()

    def model(self):
        """
        Returns the Spark Word2VecModel object.

        Returns:
            (pyspark.ml.feature.Word2VecModel): The Spark Word2VecModel of the embedding to use its API directly.
        """
        if not hasattr(self, "node2vec_"):
            return

        return self.node2vec_

    def get_most_similar_nodes(self, node_id, k=5):
        """
        Returns the k most similar nodes and a similarity measure.

        Args:
            node_id (str): Id of the node we want to search.
            k (int): Number of most similar nodes to return

        Returns:
            (DataFrame): A list of k most similar nodes (using cosine similarity) as a `DataFrame[word: string, similarity: double]`
        """
        if not hasattr(self, "node2vec_"):
            return

        return self.node2vec_.findSynonyms(node_id, k)

    def save(self, file_name):
        """
        Saves the internal Word2VecModel to a human-readable (JSON) model metadata as a Parquet formatted data file.

        The model may be loaded using SparkNode2Vec(load_file='path/file')

        Args:
            file_name (str): The name of the file to which the Word2VecModel will be saved.
        """
        if not hasattr(self, "node2vec_"):
            return

        return self.node2vec_.save(file_name)

    def _load(self, file_name):
        """
        This method is internal and should not be called directly. Use the constructor's `load_file` argument instead.
        E.g., `snv = SparkNode2Vec(load_file = 'some/stored/embedding')`
        """

        self.node2vec_ = Word2VecModel.load(file_name)

    def _start_rw(self, G: Graph):
        aux_vert = (
            G.graphframe.vertices.groupBy(f.col("id"))
            .agg(f.collect_list(f.col("id")).alias("tmp_rw_aux_acc_path"))
            .withColumn("tmp_rw_init_p", f.rand())
            .withColumn(
                "new_rw_acc_path",
                f.when(
                    f.col("tmp_rw_init_p") <= self.sampling_ratio,
                    f.col("tmp_rw_aux_acc_path"),
                ).otherwise(f.lit(None)),
            )
            .withColumn("new_rw_curr_id", f.col("id"))
            .drop("tmp_rw_aux_acc_path", "tmp_rw_init_p")
        ).filter(f.col("new_rw_acc_path").isNotNull())

        w_ind = (
            Window.partitionBy("src")
            .orderBy("dst")
            .rangeBetween(Window.unboundedPreceding, 0)
        )
        w_ind_edge = Window.partitionBy("src")

        df_edges_cumsum = G.graphframe.edges.withColumn(
            "new_rw_cum_sum", f.sum("weight").over(w_ind)
        ).withColumn("new_rw_total_sum", f.sum("weight").over(w_ind_edge))

        aux_edges = (
            df_edges_cumsum.withColumn(
                "new_rw_norm_cumsum",
                f.col("new_rw_cum_sum") / f.col("new_rw_total_sum"),
            ).select(
                f.col("src"),
                f.col("dst"),
                f.col("weight"),
                f.col("new_rw_norm_cumsum"),
            )
        )

        self.gx = GraphFrame(aux_vert, aux_edges)

    def _update_state_with_next_step(self, i):
        candidate_vert_col = self.gx.vertices.columns

        candidate_vert = self.gx.vertices.withColumnRenamed(
            "new_rw_curr_id", "new_rw_prev_id"
        ).withColumn("rand_p_step", f.rand())

        candidate_vert_with_edges = candidate_vert.join(
            self.gx.edges,
            f.col("new_rw_prev_id") == f.col("src"),
            "left",
        ).filter(
            (f.col("rand_p_step") <= f.col("new_rw_norm_cumsum"))
            | (f.isnull(f.col("new_rw_norm_cumsum")))
        )

        win_steps = Window.partitionBy("id").orderBy(f.col("new_rw_norm_cumsum").asc())

        selected_next_step = candidate_vert_with_edges.withColumn(
            "row_number", f.row_number().over(win_steps)
        ).filter(f.col("row_number") <= 1)

        selected_next_step = (
            selected_next_step.withColumn(
                "new_rw_acc_path",
                udf_select_element_2(f.col("new_rw_acc_path"), f.col("dst")),
            )
            .withColumn("new_rw_curr_id", f.col("new_rw_acc_path").getItem(i + 1))
            .select(candidate_vert_col)
        )

        return selected_next_step

    def _run_rw(self, G: Graph):
        self._start_rw(G)

        for i in range(self.num_epochs):

            aux_vert = self._update_state_with_next_step(i)
            aux_vert = aux_vert.checkpoint()
            self.gx = GraphFrame(aux_vert, self.gx.edges)

            if (i + 1) % self.batch_size == 0:
                old_aux_vert = aux_vert
                aux_vert = AggregateMessages.getCachedDataFrame(aux_vert)
                old_aux_vert.unpersist()

        paths = self.gx.vertices.select(
            f.col("new_rw_acc_path").alias("random_walks")
        ).filter(f.col("random_walks").isNotNull())

        self.gx.vertices.unpersist()
        self.gx.edges.unpersist()

        return paths
