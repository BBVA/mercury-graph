import bz2
import pickle

import numpy as np
import networkx as nx

from mercury.graph.core import Graph, njit, graph_i4
from mercury.graph.embeddings import Embeddings


@njit
def _random_node_weighted(r_sum, TotW):
    r = TotW*np.random.random() - 1e-8
    i = 0
    while r > r_sum[i]:
        r -= r_sum[i]
        i += 1

    return i


@njit
def _random_walks(r_ini, r_len, r_sum, r_col, r_wgt, TotW, n_jmp, max_jpe):
    N = len(r_ini)

    convrge = np.zeros((n_jmp, 2), dtype=graph_i4)
    diverge = np.zeros((n_jmp, 2), dtype=graph_i4)

    ori = _random_node_weighted(r_sum, TotW)
    njm = 0

    for t in range(n_jmp):

        while r_len[ori] == 0 or njm >= max_jpe:
            ori = _random_node_weighted(r_sum, TotW)
            njm = 0

        njm += 1

        rnd = r_sum[ori]*np.random.random()
        rst = r_ini[ori]
        for ic in range(r_len[ori]):
            nxt = r_col[rst + ic]
            wei = r_wgt[rst + ic]

            if wei >= rnd:
                break

            rnd -= wei

        convrge[t, 0] = ori
        convrge[t, 1] = nxt

        oth = int(N*np.random.random())
        while oth == ori or oth == nxt:
            oth = int(N*np.random.random())

        diverge[t, 0] = ori
        diverge[t, 1] = oth

        ori = nxt

    return (convrge, diverge)


class GraphEmbedding:
    """
    Create an embedding mapping the nodes of a graph.

    Args:
        G (mercury.graph Graph asset): A `mercury.graph` Graph object. The embedding will be created so that each row in the embedding maps
            a node ID in G. (This parameter will be ignored when `load_file` is used.)
        dimension (int): The number of columns in the embedding. See note the notes in `Embeddings` for details. (This parameter will be
            ignored when `load_file` is used.)
        edge_index (int): If G is a multigraph, what edge class should be used in the graph embedding. This index is zero-based. To see what
            edge classes G has, you can `print(G.summary(detailed = True))` and note that `'edges'` is a list. It's the position in that
            list.
        load_file (str): (optional) The full path to a binary file containing a serialized GraphEmbedding object. This file must be created
            using GraphEmbedding.save().
    """

    FILE_HEAD = 'mercury.graph.GraphEmbedding.1.0'
    FILE_END = 'end'

    def __init__(self, G=None, dimension=None, edge_index=0, load_file=None):
        """GraphEmbedding class constructor"""
        if load_file is not None:
            self._load(load_file)
            return

        g = G.as_networkx(edge_index=edge_index)

        self.node_ids = list(g.nodes)

        j_matrix = nx.adjacency_matrix(g)

        N = j_matrix.shape[1]
        M = j_matrix.getnnz()

        self.r_ini = np.zeros(N, dtype=int)
        self.r_len = np.zeros(N, dtype=int)
        self.r_sum = np.zeros(N, dtype=float)
        self.r_col = np.zeros(M, dtype=int)
        self.r_wgt = np.zeros(M, dtype=float)

        i = 0
        for r in range(N):
            self.r_ini[r] = i

            i_col = j_matrix[[r], :].nonzero()[1]
            L = len(i_col)

            self.r_len[r] = L

            for k in range(L):
                c = i_col[k]
                w = j_matrix[r, c]

                self.r_sum[r] += w
                self.r_col[i] = c
                self.r_wgt[i] = w

                i += 1

        self.TotW = sum(self.r_sum)

        self.gr_embed = Embeddings(dimension, len(self.node_ids))


    def __getitem__(self, arg):
        """
        Method to access rows in the embedding by ID.

        Args:
            arg (same as node ids in the graph): A node ID in the graph

        Returns:
            (numpy.matrix): A numpy matrix of one row

        """
        return self.gr_embed.em[self.node_ids.index(arg)]


    def random_walks(self, n_jumps, max_per_epoch=None, learn_step=3, bidirectional=False):
        """
        Train the embedding by doing random walks.

        Args:
            n_jumps (int): Number of random jumps from node to node.
            max_per_epoch (int): Maximum number Number of consecutive random jumps without randomly jumping outside the edges. Note
                that normal random jumps are not going to explore outside a connected component.
            learn_step (float): The size of the learning step elements get approached or moved away. Units are hexadecimal degrees in along
                an ellipse.
            bidirectional (bool): Should the changes apply only to the elements of first column (False) or to both.

        Returns:
            None (or raises an error)

        This does a number of random walks starting from a random node and selecting the edges with a probability that is proportional to
        the weight of the edge. If the destination node also has outgoing edges, the next step will start from it, otherwise, a new random
        node will be selected. The edges visited (concordant pairs) will get some reinforcement in the embedding while a randomly selected
        non-existent edges will get divergence instead (discordant pairs).

        Internally, this stores the node IDS of the node visited and calls Embeddings.learn() to transfer the structure to the embedding.
        Of course, it can be called many times on the same GraphEmbedding.

        """
        if max_per_epoch is None:
            max_per_epoch = n_jumps

        converge, diverge = _random_walks(self.r_ini, self.r_len, self.r_sum, self.r_col, self.r_wgt, self.TotW, n_jumps, max_per_epoch)
        self.gr_embed.learn(converge, diverge, learn_step, bidirectional)


    def embedding(self):
        """
        Return the internal Embeddings object.

        Returns:
            The embedding which is a dense matrix of `float` that can be used with `numpy` functions.
        """
        return self.gr_embed


    def get_most_similar_nodes(self, node_id, k=5, metric='cosine', return_as_indices=False):
        """
        Returns the k most similar nodes and the similarities

        Args:
            node_id (object): Id of the node that we want to search the similar nodes.
            k (int): Number of most similar nodes to return
            metric (str): metric to use as a similarity.
            return_as_indices (bool): if return the nodes as indices(False), or as node ids (True)

        Returns:
            (list): list of k most similar nodes and list of similarities of the most similar nodes
        """
        node_index = self.node_ids.index(node_id)

        ordered_indices, ordered_similarities = self.gr_embed.get_most_similar_embeddings(node_index, k, metric)

        if not return_as_indices:
            nodes = list(np.array(self.node_ids)[ordered_indices])
        else:
            nodes = list(ordered_indices)

        return nodes, ordered_similarities


    def save(self, file_name, save_embedding=False):
        """
        Saves a GraphEmbedding to a compressed binary file with or without the embedding itself. It saves the graph's node names
        and the adjacency matrix as a sparse matrix.

        Args:
            file_name (str): The name of the file to which the GraphEmbedding will be saved.
            save_embedding (bool): Since the embedding can be big and, if not trained, it is just a matrix of uniform random numbers it is
                possible avoiding saving it. In case it is not saved, loading the file will create a new random embedding. This parameter
                controls if the embedding is saved or not (the default value).
        """
        with bz2.BZ2File(file_name, 'w') as f:
            pickle.dump(GraphEmbedding.FILE_HEAD, f)
            pickle.dump(save_embedding, f)
            pickle.dump(self.gr_embed.dimension, f)

            pickle.dump(self.node_ids, f)

            np.save(f, self.r_ini)
            np.save(f, self.r_len)
            np.save(f, self.r_sum)
            np.save(f, self.r_col)
            np.save(f, self.r_wgt)

            pickle.dump(self.TotW, f)

            if save_embedding:
                np.save(f, self.gr_embed.em)

            pickle.dump(GraphEmbedding.FILE_END, f)


    def _load(self, file_name):
        """
        This method is internal and should not be called directly. Use the constructor's `load_file` argument instead.
        E.g., `ge = GraphEmbedding(load_file = 'some/stored/embedding')`
        """
        with bz2.BZ2File(file_name, 'r') as f:
            head = pickle.load(f)

            if head != GraphEmbedding.FILE_HEAD:
                raise ValueError('Unsupported file format!')

            has_emb = pickle.load(f)
            dimension = pickle.load(f)

            self.node_ids = pickle.load(f)

            self.r_ini = np.load(f)
            self.r_len = np.load(f)
            self.r_sum = np.load(f)
            self.r_col = np.load(f)
            self.r_wgt = np.load(f)

            self.TotW = pickle.load(f)

            self.gr_embed = Embeddings(dimension, len(self.node_ids))

            if has_emb:
                self.gr_embed.em = np.load(f)

            end = pickle.load(f)

            if end != GraphEmbedding.FILE_END:
                raise ValueError('Unsupported file format!')
