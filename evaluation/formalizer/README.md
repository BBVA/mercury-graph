# Formalizer evaluation

A small, hand-written set of texts with the expected output of a Formalizer that links what it finds to what is already known. It is
meant to compare versions of the Formalizer (or other models) on the same cases, not to claim a general accuracy: it is far too small.

It is not part of the unit tests: it downloads the GLiNER2 model and its scores measure the model, they do not pass or fail.

- `cases.json`: 30 short texts about a school, with the ontology and the initial graph of the `mge new` template. The texts are
  synthetic: they come from (or are variations of) the Markdown documents of the template.
- `check_cases.py`: checks that every expected id and edge is valid against the ontology of the template (run it after editing the
  cases).
- `run_eval.py`: runs the GLiNER2 Formalizer on every case as the EvidenceGraph will (`hint_nodes`, `link_mention`, `hint_edges`)
  and scores its output against the expected one.

Run them from the root of the repository:

```bash
python evaluation/formalizer/check_cases.py
python evaluation/formalizer/run_eval.py -v
```

`-v` lists what is missing and what is extra in every case. Both scripts take another dataset of this directory as an argument (e.g.,
`python evaluation/formalizer/run_eval.py my_cases.json`).

## Scores

Precision, recall and F1, micro-averaged over all cases, of:

- `mentions`: the mention, whatever its id, i.e., whether the text was found,
- `entities`: (mention, id, status), i.e., whether it was also linked to the right instance,
- `edges`: (src, relation, dst).

## Context of every case

Unless a case says otherwise, the Formalizer works with:

- **the ontology** of the `mge new` template (`ontology_source/entities_concepts.csv` and `relationships_concepts.csv`),
- **the known graph**: the initial graph of the template (`initial_graph/nodes.csv` and `edges.csv`), 9 instances and 4 edges.

A case can add to that context:

- `extra_known_nodes`: instances that are also known in that case (e.g., a second person called Noah).

## What is expected for a text

**Entities**: every named mention of an instance of a type of the ontology, with:

- `mention`: the text exactly as it appears,
- `id`: the id of the instance (a known id, or the id to create: its type followed by the full name),
- `status`:
  - `known`: it is an instance of the known graph (even when written differently, e.g., "Ms. Ruiz"),
  - `new`: it is not any known instance,
  - `ambiguous`: it could be several known instances and the text does not say which (`candidates` lists them; `id` is null),
  - `unresolved`: a pronoun or a generic mention that is an end of a relationship the text states, but the text does not say who
    or what it is (`id` is null),
- `type_conflict` (optional, true): the text gives the instance a type that contradicts the known one.

Named mentions are always listed. Pronouns ("She") and generic mentions ("the team", "the club" when it is not named) are listed only
when they are an end of a relationship the text states: with their id if the text says who they are, as `unresolved` otherwise.
`ambiguous` and `unresolved` tell the caller that more context could complete the output.

**Edges**: every relationship of the ontology that the text **states** (not that it suggests or that is common sense), between
instances, with:

- `src`, `relation`, `dst`: ids of instances and of the relationship (its id, not its definition).

Whether an edge is already in the known graph is not part of the output: that is a lookup the EvidenceGraph does.

**Out of scope**: things the ontology cannot express (e.g., "next to the library", "builds the car body") produce no entity or edge.
Those cases are useful to check that nothing is invented.

## Cases with context (C01–C05)

These cases describe a second call: when the output of a text has `ambiguous` or `unresolved` entries, the caller (the EvidenceGraph)
calls again with the same `text` and more `context` (e.g., the section title and the previous paragraph).

- `entities` and `edges` are the expected output of the first call, with the text alone.
- `with_context` has the expected output of the second call, with the text and its `context`.

The context is only used to resolve mentions of the text: nothing is extracted from the context itself, so every mention is still in
`text`. What is still unresolved after the second call is left for a supervisor. `run_eval.py` only scores the first call.

## Notes for the review

Every case has a `notes` field explaining what it tests and the judgment calls made. The judgment calls are where a review is most
useful: if you disagree, change the case and its note.
