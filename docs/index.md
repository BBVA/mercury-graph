# mercury-graph

**`mercury-graph`** is a Python library that offers **graph analytics capabilities with a technology-agnostic API**, enabling users
to apply a curated range of performant and scalable algorithms and utilities regardless of the underlying data framework.

The consistent, scikit-like interface abstracts away the complexities of internal transformations, allowing users to effortlessly switch
between different graph representations to leverage optimized algorithms implemented using pure Python,
[**numba**](https://numba.pydata.org/), [**networkx**](https://networkx.org/) and
PySpark [**GraphFrames**](https://graphframes.github.io/graphframes/docs/_site/index.html).


## Agentic Graphs and Evidence Graphs

Since version 3.3.1, `mercury-graph` can build and serve Evidence Graphs: structured, traceable representations of knowledge extracted
from text that can be queried by both humans and LLM agents.

The library includes a very lightweight **Agentic framework** that provides an Agentic API to any class derived from it. It is intended
to operate with OSS LLMs that can run locally, but also works with any LLM that can be accessed through litellm, including: AWS Bedrock,
OpenAI, Anthropic and Google's models.

As a first example, any Mercury Graph can be exposed through the **AgenticGraph** class, which simply adds the Agentic interface to an
existing graph. This allows graphs to be queried directly, either programmatically or in natural language through an **Agent**. The
framework provides **Agents** that can communicate in natural language and use the **AgenticGraph** as a tool. Everything can be
contained inside an **Endpoint** and maintained and served to the outside world by a cli via REST API.

Furthermore, the library provides an **EvidenceGraph** class that represents a graph of evidence extracted from the text contained in
a **Source**. An **EvidenceGraph** is built from a **Source**, which manages and indexes documents as chunks, together with a
**Formalizer**, which extracts entities and relationships from the text.

**Agents** within an **Endpoint** containing an **EvidenceGraph** can interact with any Agentic object in the Endpoint—including the **EvidenceGraph**, the **Source**, and the **Formalizer**—to answer questions about the underlying documents while providing precise,
traceable references to the relevant source passages.

(See [`evidence`](reference/evidence.md) for submodule reference, [`mge`](reference/evidence_cli.md) for the cli and
[`evidence_how`](reference/evidence_how.md) for usage guidelines.)


## Reference

Currently implemented **submodules** in `mercury.graph` include:

- [**`mercury.graph.core`**](reference/core.md), with the main classes of the library that create and store the graphs' data and properties.

- [**`mercury.graph.embeddings`**](reference/embeddings.md), with classes that calculate graph embeddings in different ways, such as
following the Node2Vec algorithm.

- [**`mercury.graph.evidence`**](reference/evidence.md), anything related with evidence graphs using agents.

- [**`mercury.graph.ml`**](reference/ml.md), with graph theory and machine learning algorithms such as Louvain community detection,
spectral clustering, Markov chains, spreading activation-based diffusion models and graph random walkers.

- [**`mercury.graph.viz`**](reference/viz.md), with capabilities for graph visualization.

### Repository

The website for the GitHub repository can be found [here](https://github.com/BBVA/mercury-graph).
