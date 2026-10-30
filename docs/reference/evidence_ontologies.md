# Ontologies in EvidenceGraph


## Intention

An ontology defines what an EvidenceGraph can know about: the **types of things** (entities) and the **types of relationships**
between them that matter for a given problem. Anything that is not described in the ontology cannot be extracted from text and does
not become part of the graph.

The ontology is meant to be **small and supervised by a human**. The world is complex, but a problem such as money laundering or
fraud involves relatively few types of entities (persons, companies, accounts, payments…) and even fewer types of relationships. An
owner of the EvidenceGraph decides what is in scope and should be able to read and understand the whole ontology. The number of
*instances* can be very large; the number of *types* should not.

Two pieces describe what an EvidenceGraph works with:

- **The ontology** says what *can* exist. It is a single [`AgenticGraph`](evidence.md#mercury.graph.evidence.AgenticGraph) whose
  nodes are the types of entities (e.g., `person`, `person|student`) and whose edges are the types of relationships between them
  (e.g., `works_on`, from `person` to `project`).
- **The initial graph** says what is *already known* before reading any document: instances (e.g., `person|student|Noah Kim`) and the
  relationships between them. It is the starting point of the [`EvidenceGraph`](evidence.md#mercury.graph.evidence.EvidenceGraph).

The examples on this page come from the endpoint created by the `mge` command line tool (a small school with students, teachers, clubs
and projects). You can find the files of its ontology in `ontology_source/` and those of its initial graph in `initial_graph/` inside
any new endpoint.


## Hierarchical IDs

Everything in an ontology is identified by a hierarchical ID whose levels are separated by `|`. Each level refines its parent:

```
place
place|room
place|room|laboratory
```

A hierarchy is natural in many domains. In banking, a specific credit card is not an isolated concept: it is a credit card, which is a
credit product, which is a financial product. Using a hierarchy is optional: an ontology where every ID has a single level is valid.

This is the same mechanism [`Source`](evidence.md#mercury.graph.evidence.Source) uses to index text, and it is what the agent interface
exposes (see [How agents explore the ontology](#how-agents-explore-the-ontology)). Because `|` separates levels, it cannot be used
inside a name.


## Entities: the nodes of the ontology

The types of entities are listed in `entities_concepts.csv`. Each one has an `id` and a `definition`:

```
id                      definition
person                  A human being.
person|student          A person who studies at a school.
person|teacher          A person who teaches a subject at a school.
place                   A physical location, such as a building or a room.
place|room              A room inside a building.
place|room|laboratory   A room equipped for scientific work.
```

The definitions are not just documentation. The [`Formalizer`](evidence.md#mercury.graph.evidence.Formalizer) gives every type of
entity and its definition to the extraction model, so a clear definition directly improves what is found in the text.


## Relationships: the edges of the ontology

The types of relationships are listed in `relationships_concepts.csv`. Each one is an edge that goes from a type of entity (`src`) to
another one (`dst`), and has an `id` and a `definition`:

```
id               src                 dst                   definition
teaches_at       person|teacher      organization|school   A teacher teaches at a school.
belongs_to       organization|club   organization|school   A club belongs to a school.
works_on         person              project               A person works on a project.
works_on|leads   person              project               A person leads a project.
```

Relationships are hierarchical too: `works_on|leads` is a more specific way of working on a project. A relationship connects the same
types as its parent or descendants of them: `works_on|leads` could go from `person|student`, but not from `organization`.

**The id of a relationship is unique.** Two relationships cannot have the same id and different types: a name is one meaning. When the
same word seems to fit two pairs of types, they usually mean different things and deserve different names. For example, a person
*belonging to* an organization is being a member of it (`member_of`), while a club *belonging to* a school is being a part of it
(`part_of`). When they really mean the same, declare the relationship once between the most general types and let the hierarchy do the
rest: `part_of` from `organization` to `organization` already covers a club that is part of a school.


## The initial graph

The initial graph holds the instances known beforehand. It is not part of the ontology: it is the first version of the graph that the
[`EvidenceGraph`](evidence.md#mercury.graph.evidence.EvidenceGraph) builds, before reading any document.

**Instances** are its nodes, listed in `initial_graph/nodes.csv`. The id of an instance is its type of entity followed by a name, so
`person|student|Noah Kim` tells you, without looking anything up, that Noah Kim is a student and therefore a person. Every instance
also has a `description`, which tells it apart from other instances of the same type when a mention is compared with it:

```
id                                          description
person|student|Noah Kim                     A student at Riverside High School who leads the Helios project of the Riverside Robotics Club.
person|teacher|Elena Ruiz                   A science teacher at Riverside High School who advises the Riverside Robotics Club.
organization|school|Riverside High School   A public high school in Brookdale.
project|Helios Solar Car                    A solar car built by the Riverside Robotics Club for the Brookdale Science Fair.
```

**Relationships between instances** are its edges, listed in `initial_graph/edges.csv`. Each edge has its own `id` and a `relation`
with the id of its type of relationship in the ontology:

```
src                         dst                                         relation         id
person|teacher|Elena Ruiz   organization|school|Riverside High School   teaches_at       id_elena_teaches_rhs
person|student|Noah Kim     project|Helios Solar Car                    works_on|leads   id_noah_leads_helios
```

The initial graph must match the ontology. This is where the hierarchy pays off: Noah Kim can lead a project because `works_on|leads`
goes from `person`, and a student is a person.


## Configuration and persistence

The ontology is configured in the `ontologies` section of an endpoint (`ontologies.jsonc` in a new endpoint) as an `AgenticGraph`:

```jsonc
"ontology": {
	"name": "ontology",
	"extra_args": {
		"description": ["This ontology holds the types of entities and of relationships that can be used in the Evidence Graph.", "..."],
		"file_format": {"src": "src", "dst": "dst", "id": "id", "directed": true, "sep": "\t"},
		"nodes": {"type": "csv", "$path": "ontology_source/entities_concepts.csv"},
		"edges": {"type": "csv", "$path": "ontology_source/relationships_concepts.csv"},
		"persistence": {"type": "pickle", "$path": "graphs/ontology.pickle"},
		"max_results": 50
	},
	"tools": []
}
```

- `nodes` and `edges` are the tab separated files above. Any column other than `id` (or `src`, `dst` and `id` for edges) becomes an
  attribute.
- `file_format` is optional and changes the column names and the separator. Any key left out takes its default value.
- `persistence` is where the graph is saved, as a pickle, when the endpoint closes. **If that file exists, it is loaded and the .csv
  files are ignored.** After editing the .csv files, delete the pickle so that the ontology is built again. A message is logged for
  every .csv file modified after the pickle was saved.
- `max_results` limits the entries of every answer given to agents.
- `description` is what agents read about the ontology.

The [`Formalizer`](evidence.md#mercury.graph.evidence.Formalizer) names the ontology it uses in its own configuration (in
`formalizers.jsonc`). The key is the role and the value is the `name` of the `AgenticGraph`, which must also be one of its `tools`:

```jsonc
"ontology": "ontology"
```

The initial graph is configured in the [`EvidenceGraph`](evidence.md#mercury.graph.evidence.EvidenceGraph) (in
`evidence_graphs.jsonc`), with the same format of files:

```jsonc
"initial_nodes": {"type": "csv", "$path": "initial_graph/nodes.csv"},
"initial_edges": {"type": "csv", "$path": "initial_graph/edges.csv"},
"persistence": {"type": "pickle", "$path": "graphs/e_graph.pickle"}
```

The names of the keys tell the difference: `nodes` and `edges` define the ontology, while `initial_nodes` and `initial_edges` are only
the starting point of a graph that grows. Both are only read when their pickle does not exist.

## Validation

The ontology and the initial graph are checked at three moments. If anything is wrong, every problem is logged and the object does not
become ready.

1. **When any graph is loaded** from its files (see [`graph_from_files()`](#mercury.graph.evidence.agentic_graph.graph_from_files)):
   ids are unique, edges cannot be loaded without a file of nodes, and the `src` and `dst` of every edge are declared nodes. A typo
   such as `projec` as the `dst` of a relationship is reported instead of becoming a new node.
2. **When the Formalizer is piloted** (see [`validate_ontology()`](#mercury.graph.evidence.formalizer.validate_ontology)): every type
   of entity and relationship has its parent defined, and every relationship connects the types of its parent or descendants of them.
   For example, `works_on|leads` from `organization` is rejected when `works_on` goes from `person`.
3. **When the EvidenceGraph is piloted** with its initial graph (see
   [`validate_initial_graph()`](#mercury.graph.evidence.formalizer.validate_initial_graph)): every instance is of a type of entity of
   the ontology, every instance has a `description` that is not empty, and every edge has a relationship of the ontology between
   instances of its types or of descendants of them. For example, `person|student|Noah Kim` can be the `src` of `works_on|leads`, but
   not of `teaches_at`, which goes from `person|teacher`. An initial graph that fails is not saved, so the next start checks it again.


## How agents explore the ontology

Through the agent interface, the ontology is navigated by id, in a similar way to a `Source`. Unlike in a `Source`, ids are used
exactly as they are written in the .csv files, without the name of the ontology in front, and an empty id is the root. Entities and
relationships are navigated separately, in two trees:

- `children_entities_by_idx_<ontology>`: the types of entities under an id, with their definitions, one or several levels down.
- `entity_by_idx_<ontology>`: a type of entity with its definition and its ancestors, to know what something is.
- `search_entities_<ontology>`: the types of entities whose id or definition contains a text.
- `children_relationships_by_idx_<ontology>`, `relationship_by_idx_<ontology>` and `search_relationships_<ontology>`: the same for
  the types of relationships, which also come with the types of entities they connect (`src` and `dst`).
- `relations_for_<ontology>`: the types of relationships a type of entity can take part in, as `src`, `dst` or both, including those
  declared for its ancestors. A `person|student` can take part in `studies_at` and also in `works_on`, declared for `person`.

The capabilities of relationships only appear when the ontology has relationships. Entries with `"more": true` have children of their
own, and every answer is limited to `max_results` entries and says when it has been cut. The exact capabilities are listed in the
[`AgenticGraph`](evidence.md#mercury.graph.evidence.AgenticGraph) reference.


## Known limitations

- There is no graph query language: agents explore the ontology through the capabilities above, one question at a time.
- The initial graph is loaded into the EvidenceGraph, but it cannot be explored through capabilities yet.
- The ontology cannot be edited at runtime: it is defined by its .csv files (deleting its pickle to apply changes).
- [`Formalizer.is_same_node()`](evidence.md#mercury.graph.evidence.Formalizer.is_same_node), which scores whether a mention is a
  known instance, is answered by [`RulesDecider`](evidence.md#mercury.graph.evidence.RulesDecider), the only Decider so far: it only
  compares their names and does not read the texts that mention them.


## Reference

::: mercury.graph.evidence.agentic_graph.graph_from_files

::: mercury.graph.evidence.formalizer.validate_ontology

::: mercury.graph.evidence.formalizer.validate_initial_graph

::: mercury.graph.evidence.formalizer.validate_instances
