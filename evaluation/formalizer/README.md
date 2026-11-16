# Formalizer evaluation

A small, hand-written set of texts with the expected output of a Formalizer that links what it finds to what is already known. It is
meant to compare versions of the Formalizer (or other models) on the same cases, not to claim a general accuracy: it is far too small.

It is not part of the unit tests: it downloads the GLiNER2 model and its scores measure the model, they do not pass or fail.

- `cases.json`: 70 short texts about a school, with the ontology and the initial graph of the `mge new` template. The texts are
  synthetic: they come from (or are variations of) the Markdown documents of the template.
- `hard_cases.json`: 26 more texts in the same story, written to be hard for `match_node` (see [Writing new cases](#writing-new-cases)).
- `check_cases.py`: checks that every expected id and edge is valid against the ontology of the template (run it after editing the
  cases).
- `run_eval.py`: runs the Formalizer, with the GLiNER2 Deciders, on every case (`extract_nodes` on the text, and `extract_edges`
  given the expected nodes of the case) and scores its extraction against the expected one.
- `run_match_node_eval.py`: runs `match_node` of the Formalizer on pairs of a mention and a known instance and scores its decisions
  (see [Evaluation of match_node](#evaluation-of-match_node)).

Run them from the root of the repository:

```bash
python evaluation/formalizer/check_cases.py
python evaluation/formalizer/run_eval.py -v
python evaluation/formalizer/run_match_node_eval.py -v
```

`-v` lists what is missing and what is extra in every case. Both scripts take another dataset of this directory as an argument (e.g.,
`python evaluation/formalizer/run_eval.py my_cases.json`).

## Scores

Precision, recall and F1, micro-averaged over all cases, of:

- `mentions`: the mention, whatever its id, i.e., whether the text was found,
- `types`: (mention, type) of the mentions whose type the text gives (their `text_type` or, by default, the type of their `id`), i.e.,
  whether the type chosen by `extract_nodes` is the right one. Other mentions are left out, so a mention found with a wrong type is
  both a miss and an extra, and a mention not found is a miss,
- `edges`: (src, relation, dst), found by `extract_edges` given the expected nodes of the case (those with an id), so that they do
  not depend on finding the mentions or linking them.

Linking the mentions to the known instances (their `id` and `status`) is described in the cases and checked by `check_cases.py`, but
it is not scored.

## Evaluation of match_node

`run_match_node_eval.py` builds pairs from the same cases: every mention that is `known` or `new` with every known instance (the known
graph and the `extra_known_nodes` of the case) of the same root type, e.g., every `person|...` for a `person|teacher`. A pair is
positive if the instance is the expected `id` of the mention. `ambiguous` and `unresolved` mentions and pronouns are left out. The
mention is given with the type the text gives it (as in `types` above) and with the text of the case.

The Decider is `NamesDecider`, defined in the script as a baseline: the score is the share of the words of the mention that are in the
name of the instance, and the mention is the same instance from 0.5 on.

Scores:

- `same`: precision, recall and F1 of the answer `same`, which depends on the threshold of the Decider,
- `AUC`: the probability that a positive pair gets a higher score than a negative one, whatever the threshold (1 orders every pair
  right, 0.5 is chance): it tells whether the score is useful before it is calibrated,
- `best threshold`: the threshold with the highest F1 on these pairs, and that F1,
- `top-1`: the share of `known` mentions whose expected instance is the only one with the highest score among their pairs.

The pairs are also counted by group: positives written as the name of the instance (`positive exact`) or not (`positive different`),
and negatives that share a word with the name of the instance (`negative homonym`) or not (`negative other`).

## Context of every case

Unless a case says otherwise, the expected output of a case is written against:

- **the ontology** of the `mge new` template (`ontology_source/entities_concepts.csv` and `relationships_concepts.csv`),
- **the known graph**: the initial graph of the template (`initial_graph/nodes.csv` and `edges.csv`), 9 instances and 4 edges.

A case can add to that context:

- `extra_known_nodes`: instances that are also known in that case, with their `id` and `description` (e.g., a second person called
  Noah).

## What is expected for a text

**Entities**: every named mention of an instance of a type of the ontology, with:

- `mention`: the text exactly as it appears,
- `id`: the id of the instance (a known id, or the id to create: its type followed by the full name),
- `status`:
  - `known`: it is an instance of the known graph (even when written differently, e.g., "Ms. Ruiz"),
  - `new`: it is not any known instance,
  - `ambiguous`: it could be several known instances and the text does not say which (`candidates` lists them; `id` is null),
  - `unresolved`: a pronoun or a generic mention that the text relates to another mention, but neither the text nor the known
    instances say who or what it is (`id` is null),
- `type_conflict` (optional, true): the text gives the instance a type that contradicts the known one.
- `text_type` (optional): the type the text gives the mention, when it is not the type of its `id`: a known instance whose role the
  text does not state (e.g., "Maya Singh gives the award" gives `person`, not `person|principal`), a `type_conflict` (the type that
  contradicts the known one), or a mention with no id (e.g., "She" gives `person`). It is required with `type_conflict`. The text
  gives a type also through the relationships of the ontology it states: "She advises the club" gives `person|teacher`, because only
  teachers advise clubs.

Named mentions are always listed. Pronouns ("She") and generic mentions ("the principal", "the lab", "the club" when it is not named)
are listed only when the text relates them to another mention by a relationship of the ontology, stated or presupposed (see **Edges**):
with their id if the text or the known instances say who they are (e.g., "the principal of Riverside High School" is its only known
principal), as `unresolved` otherwise.
`ambiguous` and `unresolved` tell the caller that more context could complete the output.

**Edges**: every relationship of the ontology that the text **states** between two listed mentions (not one that it suggests or that
is common sense), whether they are named, generic or pronouns. A relationship that the text only uses to **identify** a generic mention
is **presupposed**, not stated, and it is not expected: whoever knows which instance the mention is already knows that relationship.

- When a mention has no name, the words that pick it out are presupposed: a complement ("the principal **of** Riverside High School",
  "the lab **inside** the school", "the fair **at** the school"), a possessive ("Riverside High's robotics club") or a relative clause
  ("the teacher **who advises** the club").
- What the sentence says about a mention is stated, whether the mention is named or not: its verb ("Priya Shah **works on** the club's
  racing car") or, for a named mention, an apposition or a description of it ("Maya Singh, **the principal of** Riverside High
  School, …", "the club is **a student club at** Riverside High School").

| Text | Expected edges | Case |
|---|---|---|
| Maya Singh, the principal of Riverside High School, welcomed Carlos Vega. | Maya Singh `is_principal_of` the school | N25 |
| The principal of Riverside High School welcomed the new students. | none: "of Riverside High School" identifies "The principal" | H01 |
| Riverside High's robotics club won the regional contest. | none: the possessive identifies the club | S07 |
| Priya Shah works on the club's racing car. | Priya Shah `works_on` the Helios Solar Car | H04 |
| The chemistry teacher at Riverside High School advises the Riverside Robotics Club. | Noah Brown `advises` the club, not `teaches_at` | H08 |

Every edge has:

- `src`, `relation`, `dst`: ids of instances and of the relationship (its id, not its definition).

Whether an edge is already in the known graph is not part of the output: that is a lookup the EvidenceGraph does.

**Out of scope**: things the ontology cannot express (e.g., "next to the library", "builds the car body") produce no entity or edge.
Those cases are useful to check that nothing is invented.

## Writing new cases

1. Write a short text in the story of the template (the school, its people, the club, the fair, the projects). Only what the
   ontology can express counts.
2. List every named mention, and the generic mentions and pronouns that the text relates to another mention (see **Entities**).
3. Give every mention its `id` and `status`. An instance known only in that case goes in `extra_known_nodes`, with its `id` and a
   `description`.
4. Add `text_type` when the text does not give the type of the `id` (and always with `type_conflict`).
5. List the stated edges and leave out the presupposed ones (see **Edges**).
6. Explain in `notes` what the case tests and every judgment call.
7. Run `check_cases.py` on the file, then both evaluations.

`hard_cases.json` follows the same rules. Its cases are built to be hard for `match_node`: known instances mentioned without any word of
their name, new instances that share words with a known one, and known instances with the same name that only the text and the
descriptions tell apart.

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
