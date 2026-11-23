# Data of match_node

`match_node` asks whether a mention is a known instance: the Formalizer gives its Decider the mention (with its type, the definition of
the type and the texts where it is found) and a known instance (its id and description), and the Decider answers a score and `same`.
This folder has the datasets of such pairs, which the evaluation (`evaluation/match_node/`) runs Deciders on, and the code to load
them:

- `dataset.py`: the format of the datasets, how to load them and the Formalizer that gives a Decider the arguments of their pairs.
- `zeshel.py`: converts ZESHEL, a public dataset of entity linking, into datasets (see [ZESHEL](#zeshel)).

Run them from the root of the repository. They need Python 3.8 or later.

## Datasets

A dataset is a list of mentions, each one with the arguments of `match_node` for the mention and its candidates (the known instances
it is compared with), each one with the expected answer (`gold`). A mention and one of its candidates make a pair. The `meta` of the
mention and of the pair hold what the scores can be broken down by:

```json
{
  "mention_id": "H03#1",
  "meta": {"case": "H03", "status": "known"},
  "mention": {"mention": "Ms. Ruiz", "type": "person|teacher", "texts": ["..."]},
  "candidates": [
    {"node": {"id": "person|teacher|Elena Ruiz", "description": "..."}, "gold": true, "meta": {"group": "positive exact"}}
  ]
}
```

A dataset is saved as a `.jsonl` file with a mention per line after a first line that describes it: its `name`, the `types` of its
mentions with their definitions (the ontology the Formalizer is given) and the fields of `meta` its scores are broken down by
(`breakdowns`). Other keys describe how it was made.

## ZESHEL

[ZESHEL](https://github.com/lajanugen/zeshel) (Zero-Shot Entity Linking, Logeswaran et al., 2019) links the mentions in pages of 16
FANDOM wikis ("worlds", such as Star Wars, Star Trek or Lego) to the pages of the entities they refer to. Its train, val and test
splits have different worlds, so that val and test measure entities and domains never seen in training, as a new ontology and known
graph would be. Its text is CC BY-SA 3.0 and it is not included in this repository: download it, extract it and convert it:

```bash
python -m data.match_node.zeshel <folder of ZESHEL, with "documents" and "mentions">
```

It writes `zeshel_train.jsonl` (2,000 mentions, 8 candidates each), `zeshel_val.jsonl` and `zeshel_test.jsonl` (500 mentions, 16
candidates each) in `zeshel_data/` (which is not committed). The same arguments write the same files. In every file:

- the mention is given with a window of 50 words before and after it as its text, and with the type `entity`, since ZESHEL has no
  types,
- the candidates are its entity and other entities of the same world: some whose titles share words with the mention, the title of
  its entity or its text, and some random others. The id of a candidate is the title of its page and its description the first
  sentences of the page, up to 100 words,
- only entities whose page has at most 200 words are used, as expected entities and as candidates, so that the description keeps
  most of the page,
- the mentions are sampled with the same number of each category of ZESHEL, which compares the mention with the title of its entity:
  the same (`HIGH_OVERLAP`), the title followed by a disambiguation phrase (`MULTIPLE_CATEGORIES`), a part of the title
  (`AMBIGUOUS_SUBSTRING`) or anything else (`LOW_OVERLAP`),
- in val and test, 20% of the mentions of every category are `new` (`--new`): their entity is left out of their candidates, so that
  the right decision is that they are none of them. The other mentions are `known` and do not change with `--new`. Train has only
  `known` mentions.

The scores are broken down by `status`, `category` and `group`, and `world` is also in `meta`.

The text of ZESHEL is cleaned (its words and punctuation are joined as usual and the empty references left by removed links are
removed), and what cannot be cleaned is left out: pages that redirect to Wikipedia, code of the wikis, lists of links and removed links
that leave an article or quotes empty ("aboard the, was"). Mentions that are not names are left out too: pronouns, words that work as
one ("someone", "here") and lowercase words ending in "-ed" ("attacked"). The first line of every file says how it was made and how
many mentions every filter removed. `python -m data.match_node.zeshel --help` lists the arguments (the sizes, the lengths and the
candidates).

Its limits: the mentions have no type, the worlds are fiction, games and sports rather than the domain of an ontology, the wikis keep
the titles of their sections in the text ("... the mosque. Activities. Followers of ..."), and almost no mention is a pronoun, since
the mentions are the links of the wikis.
