# Proposal -- EvidenceGraph: Structured, Traceable Knowledge Graphs from Text

## Core Idea

EvidenceGraph is a framework for converting text into structured, traceable knowledge graphs that can be incrementally aggregated
and queried by LLM agents.

- The graphs are built using already existent open source (SIE) Structured Information Extracting Tools (E.g. GLiNER2).
- Each subgraph corresponding to a text fragment, is aggregated into a global graph where equivalent entities are merged, relations
accumulate evidence, and contradictions weaken its weight.
- Each text fragment becomes traceable, gets indexed for retrieval from a separate store.
- The LLM agent has access to both the graph and, importantly, the SIE tool which allows connecting queries in text to a known graph.
- Mercury graph stores the graph and provides the architectural framework for incremental updates, evidence tracking, and querying.

### Why?

- This is a step forward compared to the current RAG architectures, since it provides a knowledge representation mechanism that
goes beyond vector similarity. You cannot expect a static embedding of a chunk to represent by similarity a structure that answers
questions. Embeddings composed by functions try to fix that at the price of not being findable in logarithmic time.
- It does not have to be perfect to be useful.
- Even in failure, the system is more explainable and debuggable than RAG systems.
- It has great potential for open source. Ambitious, exploring ideas, that has potential for engaging and is good for the narrative.
- We can deliver in months, have a first version in September/October.

#### This is not only "better retrieval"

The graph structure enables capabilities that are difficult in standard RAG systems:

- Finding relevant answers to questions that are not similar to any single chunk.
- Connecting entities and relations.
- Evidence weighting, making sense of contradictions and reinforcements.
- It does not replace RAG, it can be used in combination.

### How?

Each text fragment (one or several sentences) is converted into a small graph:

- Entities become nodes.
- Extracted relations become edges.
- The original text becomes traceable evidence attached to those relations.

As more text is processed:

- Equivalent entities are merged.
- Relations accumulate evidence.
- Confidence evolves.
- Contradictions can be represented explicitly.

The graph becomes a continuously evolving structured memory.

An LLM agent then interacts with this graph as an external reasoning tool:

- Querying entities and relations.
- Retrieving evidence.
- Disambiguating ambiguous references.
- Grounding responses in traceable sources.

### Improves Explainability and Debuggability

A major operational weakness of current LLM systems is that retrieval failures are difficult to inspect and diagnose.

In this architecture:

- Every extracted relation is analyzable.
- Every entity merge is explicit.
- Every answer can be traced back to supporting text.

Even when the system is wrong, the misunderstanding becomes observable and debuggable.

## Project Scope and Deliverables

### Incremental Value

The project does not need perfect extraction or reasoning to become useful.

Even early versions can provide:

- traceable knowledge extraction
- entity-centric retrieval
- evidence inspection
- graph-based querying

The system can improve iteratively over time (e.g. better resolution, aggregation logic, ...).
This reduces delivery risk and avoids “all-or-nothing” outcomes.

### Why This Is Feasible

This project is ambitious, but it stays in "what can be done with current tools" territory, it does not require new AI technology.
It is about putting together existing components in a novel architecture.

The ecosystem needed to build an initial version already exists:

- small local LLMs, open source models operated via APIs
- structured extraction models (e.g. GLiNER2)
- mercury graph
- agent tooling
- appropriate storage (graph, tensor and key-value)
