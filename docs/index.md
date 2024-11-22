# mercury-graph

**`mercury-graph`** is a Python library that offers **graph analytics capabilities with a technology-agnostic API**, enabling users to apply a curated range of performant and scalable algorithms and utilities regardless of the underlying data framework. The consistent, scikit-like interface abstracts away the complexities of internal transformations, allowing users to effortlessly switch between different graph representations to leverage optimized algorithms implemented using pure Python, [**numba**](https://numba.pydata.org/), [**networkx**](https://networkx.org/) and PySpark [**GraphFrames**](https://graphframes.github.io/graphframes/docs/_site/index.html).

Currently implemented **submodules** in `mercury.graph` include:

- [**`mercury.graph.core`**](reference/core.md), with the main classes of the library that create and store the graphs' data and properties.

- [**`mercury.graph.ml`**](reference/ml.md), with graph theory and machine learning algorithms such as Louvain community detection, spectral clustering, Markov chains, spreading activation-based diffusion models and graph random walkers.

- [**`mercury.graph.embeddings`**](reference/embeddings.md), with classes that calculate graph embeddings in different ways, such as following the Node2Vec algorithm.

- [**`mercury.graph.viz`**](reference/viz.md), with capabilities for graph visualization.

### Repository

The website for the GitHub repository can be found [here](https://github.com/BBVA/mercury-graph).