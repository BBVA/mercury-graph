# Reading text into an EvidenceGraph


## Summary

When an [`EvidenceGraph`](evidence.md#mercury.graph.evidence.EvidenceGraph) crawls a source, it receives one paragraph at a time and
turns it into nodes and edges, either new ones or more evidence for ones it already knows. Its existing `crawl` capability already
calls `read_text` once per paragraph. This proposal describes what `read_text` does.

**For each paragraph:**

1. **Nodes.** The Formalizer extracts the mentions of the paragraph (`extract_nodes`). For each mention:
	1. The EvidenceGraph **searches for candidates** among its known nodes with a vector index (`search_candidates`).
	2. The Formalizer **compares the mention with each candidate** (`match_node`, one binary question per candidate).
	3. Depending on the result:
		- No candidate matches: the EvidenceGraph **creates a node** (`create_node`).
		- One candidate matches: the EvidenceGraph **merges the mention into it** (`merge_node`).
		- Several candidates match: the candidate with the highest score is chosen. A later version asks the Formalizer one
		  multiple-choice question instead (`decide_node`).
2. **Edges.** The Formalizer extracts the edges between the nodes found in step 1 (`extract_edges`, which already receives their
   ids). For each edge, the EvidenceGraph looks for a known edge with the same `src`, `relation` and `dst`. If there is one, it
   **merges the edge** into it (`merge_edge`); otherwise it **creates the edge** (`create_edge`).

**The design follows one rule:** every decision that needs a model or configurable rules is a question that the
[`Formalizer`](evidence.md#mercury.graph.evidence.Formalizer) answers through a [`Decider`](evidence.md#mercury.graph.evidence.Decider).
The EvidenceGraph stores the graph, orchestrates the steps and does not guess anything itself. Following this rule, this design adds
three questions:

- `describe_node`: write the first description of a node from a mention and its paragraph.
- `update_description`: update the description of a known node with a new mention and its paragraph.
- `decide_node` (later): choose among several candidates that match a mention.

Each question can be answered by a rule-based Decider (e.g., returning the paragraph as the description) or by a model (e.g., Laya),
and the configuration chooses which one.

**A known node** has an id, a type, a description, other names, and the sources (paragraphs) that mention it. Its description can be
**locked** (e.g., when it was written by an expert) so that merges add evidence but do not rewrite it.

**Searching for candidates** compares the embedding of the paragraph with the embeddings of the descriptions of the known nodes,
filtered by a compatible type. The embedding to search with can be configured, and we will choose it by measuring recall@k.

**Steps to get there:** (1) model and deterministic operations of nodes and edges, (2) vector index and `search_candidates`, (3)
measure the recall of the search, (4) `describe_node` and `update_description`, (5) `read_text` for nodes, (6) `read_text` for edges,
(7) configuration, template and end-to-end example, (8) `decide_node`. Steps 1 and 2 are independent of each other.


## Concepts

| Term | Meaning |
|------|---------|
| **Paragraph** | A chunk of a Source, sent by the crawl to `read_text` with its `id`. For now, paragraphs are disjoint: a paragraph is read without the previous ones. |
| **Mention** | Something extracted from a paragraph that may become part of the graph: the text as it appears (`"profesor Juan"`), a proposed type (`person\|professional\|teacher`) and a confidence. |
| **Known node** | A node already in the EvidenceGraph, from the initial graph or created while reading. |
| **Candidate** | A known node that the search returns as possibly being the same as a mention. Candidates are a small subset of the known nodes. |
| **Evidence** | The link between a node or an edge and a paragraph that mentions it. |


## How it fits in the crawl

The [`Crawl`](evidence.md#mercury.graph.evidence.Crawl) does not change. It walks the tree of a Source breadth-first and, for each
object, calls a capability of the target with `{id, text}`. `EvidenceGraph.crawl()` already sets the Source as the domain and
`read_text_<name>` as the target. `read_text` is a placeholder today, and this design is its body:

```
crawl_source ──► Crawl ──(for each paragraph)──► read_text(id, text)
                                                    │
                                                    ├── nodes: extract_nodes ► search_candidates ► match_node ► create / merge
                                                    │
                                                    └── edges: extract_edges ► lookup (src, relation, dst) ► create / merge
```

Some consequences:

- **The source of every piece of evidence is the `id` of the paragraph** that `read_text` receives.
- **Paragraphs are read one after another.** Each paragraph sees the graph as the previous one left it, so there is no concurrency to
  handle.
- **Errors.** If `read_text` fails, the Crawl sets its error flag and stops the whole crawl. See [Open points](#open-points).
- **Headers.** The crawl serializer also sends the description of a `SourceEntity` (e.g., a header) as text. We have to decide whether
  headers are read or filtered out with `accept`.


## Nodes

### Extracting mentions

`extract_nodes` (Formalizer) already exists: it returns one dictionary per mention with `mention`, `type` and `confidence`.

### Searching for candidates

`search_candidates` is a capability of the EvidenceGraph, because only the EvidenceGraph has the nodes. It returns the top `k`
candidates for a mention.

**Index.** A vector index (ChromaDB) with one entry per known node:

- The embedding of the **description** of the node. Indexing the description rather than the names finds candidates whose names are
  very different from the mention (e.g., "POTUS" and "Donald Trump", before "POTUS" is one of its names).
- The **type** of the node as metadata, to filter the search.

The index must always be up to date:

- When the EvidenceGraph is piloted, it indexes the initial graph, or loads the index persisted next to the graph.
- `create_node` and `merge_node` update the index right away, not in a batch. Otherwise, a paragraph that mentions the same person
  twice ("Juan Escanciano… profesor Juan…") would create two nodes, because the second mention would not find the node the first one
  has just created.
- When a description changes, its embedding is computed again (one embedding per merge).

**Query.** The default query is the embedding of the **whole paragraph**, filtered to the types compatible with the type of the
mention (the same type, its ancestors or its descendants in the ontology):

- It is cheap: one embedding per paragraph, shared by all its mentions. It may already exist in the chunks collection of the Source.
- It carries the context that a bare name does not have.
- The embedding of a paragraph mixes everything it talks about, so every mention of the paragraph gets the same ranking. The filter
  by type removes most of this problem (a school is not a candidate for a person). Two mentions of the same type in the same paragraph
  still share a ranking, but with a large enough `k`, telling them apart is the job of `match_node`, not of the search.

The query is configurable:

| Query | Pros | Cons |
|-------|------|------|
| The paragraph (default) | Cheap, no model needed | Mixes all the mentions of the paragraph |
| The mention, its type and the paragraph | Specific to the mention | One embedding per mention |
| The description of the mention (`describe_node`) | Compares a description with descriptions | Needs a description before knowing if the node is new |

We will choose the query and `k` by measuring the **recall@k** of the search on the ZESHEL match_node dataset: how often the correct
node is among the `k` candidates. This measures the search on its own, independently of the Decider of `match_node`.

### Comparing a mention with its candidates

`match_node` (Formalizer) already exists. It is asked once per candidate and returns `score` (0..1) and `same` (bool).

| Candidates that match | Action |
|------------------------|--------|
| None (or no candidates at all, e.g., an empty graph) | `create_node` |
| One | `merge_node` into that candidate |
| Several | First version: `merge_node` into the one with the highest `score`. Later: `decide_node` |

`decide_node` is a new multiple-choice question: given a mention and several candidates, which one is it (or none). We will add it
when the evaluation shows that the highest score is not reliable enough. For example, a Decider that often gives the same score to
similar candidates makes "the highest score" close to random.

### Creating a node

`create_node` (EvidenceGraph, deterministic):

1. Asks the Formalizer for a description: `describe_node(mention, text)`.
2. Builds the id from the type and the mention (`type|name`, as in the initial graph).
3. Stores the node with its first evidence (the id of the paragraph) and adds it to the index.

### Merging a mention into a node

`merge_node` (EvidenceGraph, deterministic):

1. Adds the evidence (the id of the paragraph) to the node.
2. Adds the mention to the names of the node if it is a new name.
3. If the description is not locked, asks the Formalizer for an updated one with `update_description(description, mention, text)`,
   stores it and updates the index.

The type is kept (see [Open points](#open-points)).

### Descriptions

Descriptions grow as the EvidenceGraph reads more about a node:

```
"A teacher."
  ► "A geography teacher."
    ► "A geography teacher at the school El Ciprés."
      ► "A geography teacher at the school El Ciprés. He has taught there for 25 years and smokes cigars."
```

Both questions are answered by configurable Deciders, so the cost is chosen per EvidenceGraph:

| Decider | `describe_node` | `update_description` |
|---------|-----------------|----------------------|
| Rules | Returns the paragraph, or a template with the type and the mention | Appends the new paragraph, or keeps the description |
| Model (e.g., Laya, an LLM) | Writes a short description from the paragraph | Rewrites the description with what the paragraph adds |

Rewriting a description over and over can lose or invent information. Because every piece of evidence keeps the id of its paragraph,
a description can always be written again from its sources.

A description can be **locked** (e.g., the nodes of an initial graph written by an expert). A merge into a node with a locked
description still adds evidence and names but does not change the description.

The importance of a node (e.g., whether it deserves a better description) does not need a stored field: it follows from the number of
its sources.


## Edges

`extract_edges` (Formalizer) already exists. It receives the nodes of the paragraph with their resolved ids, so it runs **after** the
nodes of the same paragraph are resolved.

For each edge returned:

1. **Search:** deterministic, a known edge with the same `src`, `relation` and `dst`.
2. **Found:** `merge_edge` adds the evidence (the id of the paragraph).
3. **Not found:** `create_edge` stores the edge with its first evidence.


## The data of the graph

**Known node:**

| Field | Description |
|-------|-------------|
| `id` | `type\|name`, e.g., `person\|professional\|teacher\|Juan Escanciano` |
| `type` | A type of the ontology |
| `description` | What we know about the node |
| `locked` | Whether merges may change the description |
| `names` | Other names it has been mentioned by, e.g., "profesor Juan" |
| `sources` | The ids of the paragraphs that mention it |

**Known edge:** `src`, `relation`, `dst` and `sources`.


## New capabilities

| Capability | Where | Kind |
|------------|-------|------|
| `search_candidates` | EvidenceGraph | Deterministic (vector index) |
| `create_node`, `merge_node` | EvidenceGraph | Deterministic, ask the Formalizer for descriptions |
| `create_edge`, `merge_edge` | EvidenceGraph | Deterministic |
| `read_text` (implemented) | EvidenceGraph | Orchestration |
| `describe_node` | Formalizer | Question, answered by a Decider |
| `update_description` | Formalizer | Question, answered by a Decider |
| `decide_node` (later) | Formalizer | Question, answered by a Decider |

The configuration keys of the EvidenceGraph (`agentics`: `id_nodes`, `id_edges`, `is_same`) date from an earlier design and have to be
aligned with these capabilities, together with the configuration of the index.


## Open points

- **The type in a merge.** If a mention of type `person` matches a node of type `person|professional|teacher`, or the other way round,
  is the type refined? Since the id contains the type, refining it changes the id of the node. It could be one more question with
  several Deciders (rules, a binary question to Laya…). Until then, a merge keeps the type of the node.
- **Edges.** Symmetric relations (is A–B the same edge as B–A?) and edges whose `src` or `dst` is not among the resolved nodes of the
  paragraph (discard them?).
- **Errors in `read_text`.** Does a paragraph that fails (e.g., a Decider returns `None`) stop the crawl, or is it logged and skipped?
- **Where the index lives.** In the EvidenceGraph, or in a component of its own shared with the Source, which already uses ChromaDB.
- **Context between paragraphs.** Paragraphs are disjoint for now. Giving context from previous paragraphs (e.g., a summary) would
  belong to the Source, in how it splits a text into chunks.


## Steps

1. **Model and deterministic operations.** The fields of known nodes and edges, `create_node` / `merge_node` / `create_edge` /
   `merge_edge` without descriptions, and their tests.
2. **Vector index and `search_candidates`.** Indexing on pilot, updates on every create and merge, persistence, the filter by type and
   the configurable query.
3. **Recall of the search.** Measure recall@k on ZESHEL for the three queries and choose the default query and `k`.
4. **`describe_node` and `update_description`.** The two questions, a rule-based Decider for each and the `locked` field.
5. **`read_text` for nodes.** `extract_nodes` → `search_candidates` → `match_node` → create or merge, with the highest score when
   several match, and the policy for errors.
6. **`read_text` for edges.** `extract_edges` with the resolved ids → create or merge.
7. **Configuration and end-to-end.** The `agentics` keys, headers, the endpoint template and an end-to-end example in the tutorial
   notebook.
8. **Model Deciders for descriptions.** Laya or an LLM for `describe_node` and `update_description`.
9. **`decide_node`.** If the evaluation shows that the highest score is not reliable enough.

Steps 1 and 2 are independent and can be done in parallel.
