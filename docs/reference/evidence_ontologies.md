# Ontologies in EvidenceGraph


## Intention

An ontology defines what an EvidenceGraph can know about: the **types of things** (concepts) and the **types of relationships**
between them that matter for a given problem. Anything that is not described in the ontology cannot be extracted from text and does
not become part of the graph.

The ontology is meant to be **small and supervised by a human**. The world is complex, but a problem such as money laundering or
fraud involves relatively few types of entities (persons, companies, accounts, payments…) and even fewer types of relationships. An
owner of the EvidenceGraph decides what is in scope and should be able to read and understand the whole ontology. The number of
*instances* can be very large; the number of *types* should not.

An EvidenceGraph uses three ontologies, each of them an [`AgenticGraph`](evidence.md#mercury.graph.evidence.AgenticGraph):

| Ontology        | Contains                                        | Example                                  |
|-----------------|-------------------------------------------------|------------------------------------------|
| `entities`      | The hierarchy of concepts that can be instantiated. | `person`, `person|student`           |
| `relationships` | The hierarchy of relationships between concepts. | `works_on`, `works_on|leads`            |
| `known_ids`     | The indexed instances of both.                  | `person|student|Noah Kim`               |

The examples on this page come from the ontology created by the `mge` command line tool for a new endpoint (a small school with
students, teachers, clubs and projects). You can find its files in `ontology_source/` inside any new endpoint.


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
exposes (see [How agents explore an ontology](#how-agents-explore-an-ontology)). Because `|` separates levels, it cannot be used
inside a name.


## Entities: the concepts that can be instantiated

The `entities` ontology lists the concepts. Each one has an `id` and a `definition`:

```
id                      definition
person                  A human being.
person|student          A person who studies at a school.
person|teacher          A person who teaches a subject at a school.
place                   A physical location, such as a building or a room.
place|room              A room inside a building.
place|room|laboratory   A room equipped for scientific work.
```

The definitions are not just documentation. The [`Formalizer`](evidence.md#mercury.graph.evidence.Formalizer) gives every concept and
its definition to the extraction model, so a clear definition directly improves what is found in the text.


## Relationships

The `relationships` ontology lists the types of relationship. Besides its `id` and `definition`, each one declares the concepts it
connects: `src` (where the relationship starts) and `dst` (where it ends). Both are IDs from `entities`:

```
id               src              dst                  definition
teaches_at       person|teacher   organization|school  A teacher teaches at a school.
works_on         person           project              A person works on a project.
works_on|leads   person           project              A person leads a project.
```

Relationships are hierarchical too: `works_on|leads` is a more specific way of working on a project. As with entities, the hierarchy is
optional, but it is available so that relationships do not have to be modeled differently from entities.


## Known IDs: the indexed instances of both

The `known_ids` ontology is the index of every instance that has been identified. It holds IDs only; everything that is known about an
instance (the sources that mention it, the evidence and its confidence) lives in the
[`EvidenceGraph`](evidence.md#mercury.graph.evidence.EvidenceGraph).

**Instances of entities** are nodes. Their ID is the ID of their concept followed by a name:

```
id
person|student|Noah Kim
person|teacher|Elena Ruiz
organization|school|Riverside High School
place|room|laboratory|science laboratory
```

**Instances of relationships** are edges between two of those nodes. Each edge has its own `id` and a `relation` attribute with the ID
of its type in `relationships`:

```
src                         dst                                         relation         id
person|teacher|Elena Ruiz   organization|school|Riverside High School   teaches_at       id_elena_teaches_rhs
person|student|Noah Kim     project|Helios Solar Car                    works_on|leads   id_noah_leads_helios
```

Note that this is where the hierarchy pays off: `person|student|Noah Kim` tells you, without looking anything up, that Noah Kim is a
student and therefore a person.


## Configuration and persistence

Ontologies are configured in the `ontologies` section of an endpoint (`ontologies.jsonc` in a new endpoint). Each one is an
`AgenticGraph` with this configuration:

```jsonc
"entities": {
	"name": "entities",
	"extra_args": {
		"description": "This ontology holds all the entities that can be used in the Evidence Graph. ...",
		"file_format": {"src": "src", "dst": "dst", "id": "id", "directed": true, "sep": "\t"},
		"initial_nodes": {"type": "csv", "$path": "ontology_source/entities_concepts.csv"},
		"persistence": {"type": "pickle", "$path": "graphs/entities.pickle"}
	},
	"tools": []
}
```

- `initial_nodes` and `initial_edges` are the tab separated files above. Any column other than `id` (or `src`, `dst` and `id` for edges)
  becomes an attribute.
- `file_format` is optional and changes the column names and the separator.
- `persistence` is where the graph is saved, as a pickle, when the endpoint closes. **If that file exists, it is loaded and the .csv
  files are ignored.** After editing the .csv files, delete the pickle so that the ontology is built again.
- `description` is what agents read about the ontology.

The [`Formalizer`](evidence.md#mercury.graph.evidence.Formalizer) connects to the three ontologies by name in its own configuration:

```jsonc
"ontologies": {"entities": "entities", "relationships": "relationships", "known_ids": "known_ids"}
```

Only `entities` is required. Setting `relationships` or `known_ids` to `null` disables the Formalizer capabilities that need them.


## Validation

When the [`Formalizer`](evidence.md#mercury.graph.evidence.Formalizer) is piloted, it checks that its three ontologies are coherent:
every concept and relationship has its parent defined, relationships only connect existing concepts, and every known instance and
edge is of an existing type. An edge must also connect instances of the types declared by its relationship or of their descendants:
`person|student|Noah Kim` can be the `src` of `works_on|leads`, declared from `person`, but not of `teaches_at`, declared from
`person|teacher`.

If anything is wrong, every problem is logged and the Formalizer does not become ready. See
[`validate_ontologies()`](#mercury.graph.evidence.formalizer.validate_ontologies) for the details.


## How agents explore an ontology

Through the agent interface, an `AgenticGraph` is navigated by index, just like a `Source`. Every index starts with the name of the
ontology, so the root of `entities` is `entities` and the concept `place|room` is `entities|place|room`. From there, an agent can
list the children of an index or read the properties of a node. For example, the children of `known_ids|person|student` are
`known_ids|person|student|Noah Kim` and `known_ids|person|student|Priya Shah`.

Relationship instances are found under `known_ids|_edge_`, organized by the ID of their source entity.

The exact capabilities are listed in the [`AgenticGraph`](evidence.md#mercury.graph.evidence.AgenticGraph) reference.


## Known limitations

- Agents can only navigate the hierarchy one level at a time. Reaching a relationship instance takes many steps, and there is no way to
  find all instances of a relationship type, the relationships a concept can take part in, or an instance by its name.
- [`Formalizer.is_a()`](evidence.md#mercury.graph.evidence.Formalizer.is_a), which should score whether something is a type of a
  given concept, is not implemented yet.


## Reference

::: mercury.graph.evidence.formalizer.validate_ontologies
