# Reading text into an EvidenceGraph

*This page describes the proposed design of how the EvidenceGraph reads text. It is not implemented yet.*


## Summary

When an [`EvidenceGraph`](evidence.md#mercury.graph.evidence.EvidenceGraph) crawls a source, it receives one paragraph at a time and
turns it into nodes and edges, either new ones or more evidence for ones it already knows. Its existing `crawl` capability already
calls `read_text` once per paragraph. This proposal describes what `read_text` does.

**For each paragraph:**

1. **Nodes.** The Formalizer extracts the mentions of the paragraph (`extract_nodes`). For each mention:
	1. The EvidenceGraph **searches for candidates** among its known nodes with a vector index and returns the top N
	   (`search_candidates`).
	2. The Formalizer **compares the mention with each candidate** (`match_node`, one binary question per candidate).
	3. Depending on the result:
		- No candidate matches: the EvidenceGraph **creates a node** (`create_node`).
		- One candidate matches: the EvidenceGraph **adds the evidence to that node** (`merge_node`).
		- Several candidates match: the candidate with the highest score is chosen. A later version asks the Formalizer one
		  multiple-choice question instead (`decide_node`).
2. **Edges.** The Formalizer receives the resolved nodes of the paragraph (`extract_edges`). It lists every ordered pair of nodes whose
   types can be related by the ontology, and for each pair and each possible relation it asks a Decider a binary question: does this
   text state this relation between these two nodes (`match_edge`)? For each edge found, the EvidenceGraph **adds the evidence** to the
   known edge with the same `src`, `relation` and `dst` (`merge_edge`), or **creates the edge** (`create_edge`).

**The design follows one rule:** every decision that needs a model or configurable rules is a question that the
[`Formalizer`](evidence.md#mercury.graph.evidence.Formalizer) answers through a configurable
[`Decider`](evidence.md#mercury.graph.evidence.Decider). The EvidenceGraph stores the graph and its evidence, orchestrates the steps
and does not guess anything itself. Following this rule, this design adds these questions:

- `match_edge`: whether a text states a relation between two nodes.
- `describe_node`: write the first description of a node from a mention and its paragraph.
- `adds_information`: whether a paragraph states something about a known node that its description does not contain.
- `update_description`: update the description of a known node with a new paragraph, only when `adds_information` says it adds
  something.
- `decide_node` (later): choose among several candidates that match a mention.

The binary questions are answered by a classifier (e.g., Laya, JEV), and the descriptions are written by a generative model. The
configuration chooses the Decider of each question.

**The EvidenceGraph stores evidence; it does not aggregate it.** Every node and edge keeps a list of evidence: the paragraph it comes
from, the confidence score of the source and the confidence score of the model. Whoever uses the graph combines them as they need.

**A known node** has an id, a type, a description, aliases, a status (e.g., a description locked by an expert) and its evidence.
**A known edge** is identified by its `src`, `relation` and `dst`, and has nothing else but its evidence.

**Searching for candidates** compares the embedding of the paragraph with the embeddings of the descriptions of the known nodes,
filtered by a compatible type. The vector index (ChromaDB) belongs to the EvidenceGraph, and the same search will later serve
queries.

**Steps to get there:** (1) data and deterministic operations of nodes and edges, (2) vector index and `search_candidates`, (3)
recall of the search, (4) `match_edge` and the new `extract_edges`, (5) model Deciders for descriptions, (6) `adds_information` with
Laya, (7) `read_text`, (8) configuration, template and end-to-end example, (9) `decide_node`. Steps 1, 2 and 4 are independent of
each other.


## Concepts

| Term | Meaning |
|------|---------|
| **Paragraph** | A chunk of a Source, sent by the crawl to `read_text` with its `id`. For now, paragraphs are disjoint: a paragraph is read without the previous ones. |
| **Mention** | Something extracted from a paragraph that may become a node: the text as it appears (`"profesor Juan"`), a proposed type (`person\|professional\|teacher`) and a confidence. |
| **Known node** | A node already in the EvidenceGraph, from the initial graph or created while reading. |
| **Candidate** | A known node that the search returns as possibly being the same as a mention. Candidates are a small subset of the known nodes. |
| **Possible relation** | A relation of the ontology whose `src` and `dst` types are those of two nodes of a paragraph, or ancestors of them. |
| **Evidence** | The record that a paragraph supports a node or an edge, with the confidence scores of its source and of the model. |


## How it fits in the crawl

The [`Crawl`](evidence.md#mercury.graph.evidence.Crawl) does not change. It walks the tree of a Source breadth-first and, for each
object, calls a capability of the target with `{id, text}`. `EvidenceGraph.crawl()` already sets the Source as the domain and
`read_text_<name>` as the target. `read_text` is a placeholder today, and this design is its body:

```
crawl_source ──► Crawl ──(for each paragraph)──► read_text(id, text)
                                                    │
                                                    ├── nodes: extract_nodes ► search_candidates ► match_node ► create / merge
                                                    │
                                                    └── edges: extract_edges (match_edge per pair and relation) ► create / merge
```

Some consequences:

- **The source of every piece of evidence is the `id` of the paragraph** that `read_text` receives.
- **Paragraphs are read one after another.** Each paragraph sees the graph as the previous one left it, so there is no concurrency to
  handle.
- **Errors.** If `read_text` fails, the Crawl sets its error flag and stops the whole crawl. See [Open points](#open-points).
- **Headers.** The crawl serializer also sends the description of a `SourceEntity` (e.g., a header) as text. We have to decide whether
  headers are read or filtered out with `accept`.


## Evidence

Every node and edge has a list of evidence. One piece of evidence has:

| Field | Description |
|-------|-------------|
| `source_id` | The id of the paragraph |
| `source_confidence_score` | How much the source is trusted, from the configuration of the Source |
| `model_confidence_score` | How sure the model is that the paragraph supports the node or the edge |

**The confidence score of a source** is set in its configuration (e.g., the user manuals of a product are fully trusted; a forum
less). A Source without it gets a default value.

**The confidence score of the model** is, for now:

| Evidence of | Score |
|-------------|-------|
| An edge | The score of `match_edge` |
| A known node | The score of `match_node` |
| A new node | The confidence of `extract_nodes` |

These scores come from different models and are not on comparable scales. They can be changed later without affecting the rest of
the design.

**No aggregation.** The EvidenceGraph appends evidence to the list and does not combine it into a single number. How much a node or
an edge is worth for a given problem is decided by whoever uses the graph.

**Size.** The list keeps all the evidence by default. The configuration can limit it to the top K by confidence. The top K of a node
is a snapshot: as its description evolves, evidence that was decisive early may matter less later.

**Thresholds.** The configuration has a threshold to create a node or an edge and another one to add evidence to a known one. A
threshold above 1 disables the action: e.g., a creation threshold of 2 makes an EvidenceGraph that only adds evidence to what it
already knows.


## Nodes

### Extracting mentions

`extract_nodes` (Formalizer) already exists: it returns one dictionary per mention with `mention`, `type` and `confidence`.

### Searching for candidates

`search_candidates` is a capability of the EvidenceGraph, because only the EvidenceGraph has the nodes. It returns the top N
candidates for a mention. The same capability, connecting text to the nodes of the graph, will be the entry point of queries.

**Index.** A vector index (ChromaDB), owned by the EvidenceGraph, with one entry per known node:

- The embedding of the **description** of the node. Indexing the description rather than the names finds candidates whose names are
  very different from the mention (e.g., "POTUS" and "Donald Trump", before "POTUS" is one of its aliases).
- The **type** of the node as metadata, to filter the search.

The index must always be up to date:

- When the EvidenceGraph is piloted, it indexes the initial graph, or loads the index persisted next to the graph.
- `create_node` and `merge_node` update the index right away, not in a batch. Otherwise, a paragraph that mentions the same person
  twice ("Juan Escanciano… profesor Juan…") would create two nodes, because the second mention would not find the node the first one
  has just created.
- When a description changes, its embedding is computed again (one embedding per merge).

**Query.** The default query is the embedding of the **whole paragraph**, filtered to the types compatible with the type of the
mention (the same type, its ancestors or its descendants in the ontology):

- It is cheap: one embedding per paragraph, shared by all its mentions.
- It carries the context that a bare name does not have.
- The embedding of a paragraph mixes everything it talks about, so every mention of the paragraph gets the same ranking. The filter
  by type removes most of this problem (a school is not a candidate for a person). Two mentions of the same type in the same paragraph
  still share a ranking, but with a large enough N, telling them apart is the job of `match_node`, not of the search.

N is chosen by measuring the **recall@N** of the search on a dataset of mentions in their paragraphs, each one linked to a known
entity with a description.

**Improving the search.** Asking `match_node` about candidates far beyond the top N (e.g., the top 50) shows where the right node was
ranked when it was not in the top N. Spending tokens this way builds a dataset to improve the embeddings of the search.

### Comparing a mention with its candidates

`match_node` (Formalizer) already exists. It is asked once per candidate and returns `score` (0..1) and `same` (bool). A binary
question per candidate keeps every question short enough for Laya, even when a description is long.

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
3. Stores the node with its first evidence and adds it to the index.

### Merging a mention into a node

`merge_node` (EvidenceGraph, deterministic):

1. Appends the evidence to the node.
2. Adds the mention to the aliases of the node if it is a new name.
3. Unless the status of the node locks its description, asks the Formalizer for an updated one with
   `update_description(description, mention, text)`. If the description has changed, it stores it and updates the index.

The type is kept (see [Open points](#open-points)).

### Descriptions

Descriptions grow as the EvidenceGraph reads more about a node:

```
"A teacher."
  ► "A geography teacher."
    ► "A geography teacher at the school El Ciprés."
      ► "A geography teacher at the school El Ciprés. He has taught there for 25 years and smokes cigars."
```

Writing a first description and updating one are different tasks, so they are different questions, each answered by its own
configurable Decider. Updating is split in two: a decision, and a generation only when the decision is positive.

| Question | Kind | Input → output |
|----------|------|----------------|
| `describe_node` | Generative | mention, type and paragraph → description |
| `adds_information` | Binary | description, mention and paragraph → `{score, same}`: whether the paragraph states a fact about the node that the description does not contain |
| `update_description` | Generative | description, mention and paragraph → new description |

The Formalizer exposes `describe_node` and `update_description` as capabilities. `update_description` asks `adds_information` first
and only generates a new description when the answer is positive; otherwise it returns the description unchanged. If no Decider is
configured for `adds_information`, it always generates.

`adds_information` is answered by a classifier (Laya), and `describe_node` and `update_description` by a generative model.

Every description has a **maximum length** (in the configuration), whatever the Decider: a node must have a bounded size, and long
descriptions dilute their embedding.

#### Deciding whether a paragraph adds information

`adds_information` asks whether the paragraph states something **new** about the node, not whether it is useful: how useful a fact
is depends on the problem the graph is used for, and is decided by whoever uses it.

It is a classification, so a classifier answers it and no text is generated. Most paragraphs about a known node add nothing new to
its description, so most merges end here, cheaply, without generating text or computing the embedding again.

Its two errors do not cost the same:

- Answering "no" when the paragraph adds a fact leaves the fact out of the description. It is not lost: the evidence keeps the
  paragraph, and rewriting the description from its evidence recovers it.
- Answering "yes" when the paragraph adds nothing costs a generation that returns almost the same description.

So its threshold leans towards "yes".

There are no labelled examples for it yet. They can be generated from a dataset of paragraphs about known entities and their
descriptions, labelled by a large LLM as a teacher, to fine-tune Laya.

#### Generative Deciders

The Deciders of `describe_node` and `update_description` call a generative model through `litellm`, as
[`Agent`](evidence.md#mercury.graph.evidence.Agent) already does. The model is chosen in their configuration:

- **A small local model**: an instruction-tuned model of 1 to 4 billion parameters, served locally (e.g., with Ollama or vLLM). Writing
  a short description from a paragraph is a summarization task well within the reach of these models, it runs without sending the
  sources outside, and its cost is fixed.
- **A remote LLM**: better quality and no infrastructure, at a cost per call and sending the paragraphs to a provider.

Both use greedy decoding (temperature 0), so that the same input always gives the same description.

**`describe_node`** receives the mention, its type and the definition of the type, and the paragraph. The instructions ask for:

- one or two sentences about that mention only, not about the other things the paragraph talks about,
- only facts stated in the paragraph, with no knowledge of the model (a small model tends to fill gaps with plausible facts),
- the maximum length, and the language of the configuration.

**`update_description`** receives the current description, the mention, its type and the paragraph, and is only asked once
`adds_information` has decided that the paragraph adds something. The instructions ask for:

- every fact of the current description kept, merged with the new ones, and shortened only when the maximum length requires it,
- only facts stated in the description or in the paragraph,
- the newer fact kept and the older one dropped when they contradict each other.

Rewriting a description over and over can lose or invent information. Because every piece of evidence keeps the id of its paragraph,
a description can always be **written again from its evidence** instead of updated: `describe_node` on the K paragraphs of highest
confidence. It costs more than an update but does not drift, so it can be run from time to time (e.g., every M merges) rather than
on every merge.

**Evaluation.** A description is good if it helps to find and match its node. Instead of scoring the text, we measure the recall@N of
the search and the accuracy of `match_node` with the generated descriptions instead of the original ones, on the dataset used to
choose N.


## Edges

### Extracting edges

`extract_edges` (Formalizer) keeps its contract: it receives the text and the resolved nodes of the paragraph (`{mention, id}`) and
returns `[{src, relation, dst, confidence}]`. It runs **after** the nodes of the same paragraph are resolved.

What changes is how it answers:

1. **Pairs.** It lists every ordered pair (A, B) of different nodes of the paragraph.
2. **Possible relations.** For each pair, it takes the relations of the ontology whose `src` type is the type of A or an ancestor of
   it, and whose `dst` type is the type of B or an ancestor of it. Pairs without any possible relation are skipped; most pairs are
   expected to have none, or very few.
3. **Binary questions.** For each pair and possible relation, it asks `match_edge` to a configurable Decider (Laya, JEV…).
4. **Edges.** Every positive answer is an edge, with the score of the Decider as its confidence.

`match_edge` is a new question, with the same shape as `match_node`:

```
text:     "...el profesor Juan llegó tarde a la clase de geografía de la escuela El Ciprés..."
src:      person|professional|teacher|Juan Escanciano   (mention: "profesor Juan")
relation: works_at — "A person works at a school."
dst:      place|school|El Ciprés                         (mention: "escuela El Ciprés")

►  {score: 0.93, same: true}
```

The Decider receives the id and the mention of each node, but not their descriptions. The question is whether **this text** states
the relation; what the graph already knows about the nodes must not make the answer positive. It also keeps the question short. The
descriptions can be added later if the evaluation shows they help.

**Cost.** A paragraph with 5 nodes has 20 ordered pairs; with 2 possible relations per pair on average, that is 40 questions. Many
questions replace the single call of the GLiNER2 Decider, but each one is concrete enough to be answered reliably. Later versions can
reduce the number of questions, e.g., by asking, for each relation, which nodes of the paragraph it may involve.

Because the nodes are given and never extracted again, there is no need to match the text extracted by a model to the mentions of
the nodes. Relations whose two ends have the same type need no special handling, since the pairs are ordered.

**Data.** The cases of `evaluation/formalizer/` have the expected nodes and edges of each text. Every pair and possible relation of a
case that is not an expected edge is a negative example, so they give a dataset for `match_edge` (to evaluate it, and later to
fine-tune Laya) without writing new cases.

### Creating or merging edges

An edge is identified by its triple: `src`, `relation` and `dst`. Its definition is that of its relation in the ontology, so it has no
description of its own. The graph is a multigraph: two nodes can be connected by edges of several relations.

For each edge returned by `extract_edges`:

1. **Search:** deterministic, a known edge with the same `src`, `relation` and `dst`. There is either one or none.
2. **Found:** `merge_edge` appends the evidence.
3. **Not found:** `create_edge` stores the edge with its first evidence.

Edges whose `src` or `dst` is not a node of the graph (e.g., a node that was not created because of the creation threshold) are
discarded.


## The data of the graph

**Known node:**

| Field | Description |
|-------|-------------|
| `id` | `type\|name`, e.g., `person\|professional\|teacher\|Juan Escanciano` |
| `type` | A type of the ontology |
| `description` | What we know about the node |
| `aliases` | Other names it has been mentioned by, e.g., "profesor Juan" |
| `status` | E.g., whether the description is locked (written by an expert). It may later also say where the node comes from (the initial graph or a text) |
| `evidence` | The list of evidence (see [Evidence](#evidence)) |

**Known edge:**

| Field | Description |
|-------|-------------|
| `src`, `relation`, `dst` | Its identity: two nodes and a relation of the ontology between their types |
| `evidence` | The list of evidence (see [Evidence](#evidence)) |


## New capabilities

| Capability | Where | Kind |
|------------|-------|------|
| `search_candidates` | EvidenceGraph | Deterministic (vector index) |
| `create_node`, `merge_node` | EvidenceGraph | Deterministic, ask the Formalizer for descriptions |
| `create_edge`, `merge_edge` | EvidenceGraph | Deterministic |
| `read_text` (implemented) | EvidenceGraph | Orchestration |
| `extract_edges` (new implementation) | Formalizer | Lists pairs and possible relations, asks `match_edge` |
| `match_edge` | Formalizer | Question, answered by a Decider |
| `describe_node` | Formalizer | Question, answered by a Decider |
| `update_description` | Formalizer | Asks `adds_information`, then the question `update_description` if it adds something |
| `adds_information` | Formalizer | Question, answered by a Decider |
| `decide_node` (later) | Formalizer | Question, answered by a Decider |

The GLiNER2 Decider of `extract_edges` (`XEdgesGl2Decider`) is no longer needed.

The configuration keys of the EvidenceGraph (`agentics`: `id_nodes`, `id_edges`, `is_same`) date from an earlier design and have to be
aligned with these capabilities, together with the configuration of the index, the thresholds and the top K of the evidence. Each
Source gets an optional `confidence_score`.


## Open points

- **The hierarchy of relations.** With one question per relation, both `works_on` and `works_on|leads` can be positive for the same
  pair. Are both kept, or only the most specific one? And across paragraphs, if the graph has `works_on` and a paragraph gives
  `works_on|leads`, is the edge refined or is a second edge created?
- **The type in a merge.** If a mention of type `person` matches a node of type `person|professional|teacher`, or the other way round,
  is the type refined? Since the id contains the type, refining it changes the id of the node. Until then, a merge keeps the type of
  the node.
- **The scores of the model.** They come from different models (`extract_nodes`, `match_node`, `match_edge`) and are not comparable.
  Which score the thresholds apply to (the model, or a combination with the source) is not decided.
- **Symmetric relations.** Is A–B the same edge as B–A for relations such as "knows"? For now, every relation is directed.
- **Errors in `read_text`.** Does a paragraph that fails (e.g., a Decider returns `None`) stop the crawl, or is it logged and skipped?
- **Context between paragraphs.** Paragraphs are disjoint for now. Giving context from previous paragraphs (e.g., a summary) would
  belong to the Source, in how it splits a text into chunks.


## Steps

1. **Data and deterministic operations.** The fields of known nodes and edges, the evidence, `create_node` / `merge_node` /
   `create_edge` / `merge_edge` without descriptions, the thresholds and the top K, and their tests.
2. **Vector index and `search_candidates`.** ChromaDB in the EvidenceGraph, indexing on pilot, updates on every create and merge,
   persistence and the filter by type.
3. **Recall of the search.** A dataset of mentions linked to known entities, and recall@N on it to choose N.
4. **`match_edge` and the new `extract_edges`.** The question, a Decider for it, the new implementation of `extract_edges`, its dataset
   from `evaluation/formalizer/`, and a comparison with the GLiNER2 Decider with `run_eval.py`.
5. **Model Deciders for descriptions.** The questions `describe_node` and `update_description`, generative Deciders for them through
   `litellm`, the maximum length, the `status` of the node, rewriting from the evidence, and their evaluation.
6. **`adds_information` with Laya.** The question, its place in `update_description`, a dataset labelled by a large LLM, and a Laya
   Decider fine-tuned on it.
7. **`read_text`.** Nodes (`extract_nodes` → `search_candidates` → `match_node` → create or merge) and edges (`extract_edges` → create
   or merge), with the policy for errors.
8. **Configuration and end-to-end.** The `agentics` keys, the `confidence_score` of the Sources, headers, the endpoint template and an
   end-to-end example in the tutorial notebook.
9. **`decide_node`.** If the evaluation shows that the highest score is not reliable enough.

Steps 1, 2 and 4 are independent and can be done in parallel.
