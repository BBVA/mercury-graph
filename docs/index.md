# mercury-graph

**`mercury-graph`** is a Python library that offers **graph analytics capabilities with a technology-agnostic API**, enabling users
to apply a curated range of performant and scalable algorithms and utilities regardless of the underlying data framework.

The consistent, scikit-like interface abstracts away the complexities of internal transformations, allowing users to effortlessly switch
between different graph representations to leverage optimized algorithms implemented using pure Python,
[**numba**](https://numba.pydata.org/), [**networkx**](https://networkx.org/) and
PySpark [**GraphFrames**](https://graphframes.github.io/graphframes/docs/_site/index.html).


## Agentic Graphs and Evidence Graphs

----
<div class="maturity-warning" role="note" aria-label="Early release warning">
<img
  src="../../images/warning-read-first-reader.svg"
  width="128px"
  alt="Read first"
>
</div>

> **Early release — developer and research preview**
>
> Version **3.3.1** is the first release of **EvidenceGraph**. It is intended for developers and researchers who want to help shape a well-defined idea at an early stage: building traceable, evidence-aware knowledge graphs from text.
>
> This release provides the core structure and enough working code to explore, extend and test that direction. **It does not yet provide settled answers to many of its most important design questions** -- for example, how entities and relations should best be resolved and merged; how agents should use graph tools effectively; and how an EvidenceGraph should be queried reliably through natural language.
>
> **All main classes also have known limitations** that will need to be addressed as the library evolves. EvidenceGraph is therefore **not ready for productive use**. We discourage production deployments at this stage and cannot support them.
>
> If you are interested in experimenting, contributing, challenging assumptions and helping build a community around this approach, this is the right time to join. We will clearly communicate when the library is ready for productive use.
----

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

(See [`evidence`](reference/evidence.md) for submodule reference, [`evidence_source`](reference/evidence_source.md) for the
components of the **Source** class, [`mge`](reference/evidence_cli.md) for the cli and [`evidence_how`](reference/evidence_how.md) for
usage guidelines.)


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
