# Evaluation of match_node

`match_node` asks whether a mention is a known instance: the Formalizer gives its Decider the mention (with its type, the definition of
the type and the texts where it is found) and a known instance (its id and description), and the Decider answers a score and `same`.
This evaluation runs a Decider on a dataset of such pairs, saves its scores and scores its answers.

It is not part of the unit tests: it may download a model and its scores measure the model, they do not pass or fail. It needs Python
3.8 or later (Laya needs 3.10 or later).

- `data.py`: the datasets, in a common format.
- `deciders.py`: the Deciders that can be evaluated.
- `run.py`: runs a Decider on a dataset, saves the run and prints its scores.
- `score.py`: scores saved runs again, without running any model: with another threshold, another breakdown, their errors or the
  history of the runs.
- `metrics.py`: the scores.

Run them from the root of the repository:

```bash
python -m evaluation.match_node.run hard_cases --decider laya -v
python -m evaluation.match_node.score evaluation/match_node/runs/<run>.jsonl --threshold 0.45 --errors
python -m evaluation.match_node.score --history
```

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

`cases` and `hard_cases` are the cases of the Formalizer (see [its README](../formalizer/README.md)), with the ontology and the known
graph of the `mge new` template:

- every mention of a case that is `known` or `new` is paired with every known instance (the known graph and the `extra_known_nodes`
  of the case) of the same root type, e.g., every `person|...` for a `person|teacher`. The pair is positive if the instance is the
  expected `id` of the mention. `ambiguous` and `unresolved` mentions and pronouns are left out: a pronoun needs coreference, which
  `match_node` does not resolve,
- the mention is given with the type the text gives it (its `text_type` or, by default, the type of its `id`), so that the errors of
  `extract_nodes` do not count here, and with the text of the case,
- every pair has a `group`: a positive written as the name of the instance (`positive exact`) or not (`positive different`), and a
  negative that shares a word with the name of the instance (`negative homonym`) or not (`negative other`).

## Deciders

- `names`: `NamesDecider`, a baseline defined in `deciders.py`. The score is the share of the words of the mention that are in the
  name of the instance (the last level of its id). It reads neither the texts nor the description.
- `laya`: `MatchNodeLayaDecider` with the model `convaiinnovations/laya` (it needs `pip install laya`).
- `laya/<subfolder>`: the same with another checkpoint of that model (e.g., `laya/typed-decisions`).

The mention is the same instance if the score reaches the threshold (`--threshold`, 0.5 by default).

## Runs

`run.py` saves every run as a `.jsonl` file, by default in `runs/` (which is not committed) as `<dataset>__<decider>__<date>.jsonl`:

- the first line describes the run: the dataset (its name, its file and the SHA-256 of that file, so that runs on different versions
  of a dataset are not compared), the Decider and its configuration, the commit of the repository (and whether it had uncommitted
  changes), the versions of Laya and Python, the time, how many pairs the model cut because they did not fit and how many calls
  failed,
- every other line is a mention with the `score` of every candidate, its `gold` and its `meta` (and `"truncated": true` if the model
  cut the pair). A failed call has no score and is left out of the scores.

The scores of the run are saved next to it (`<run>.metrics.json`) and added to the history of the runs (`runs/results.jsonl`), one line
per run with its main scores. `score.py` prints them again from the scores of the Decider, with any threshold or breakdown; with
`--save`, it keeps them as `run.py` does.

## Scores

- `same`: precision, recall and F1 of the answer `same`, which depends on the threshold,
- `AUC`: the probability that a positive pair gets a higher score than a negative one, whatever the threshold (1 orders every pair
  right, 0.5 is chance): it tells whether the score is useful before it is calibrated,
- `best threshold`: the threshold with the highest F1 on these pairs, and that F1,
- `top-1`: the share of the mentions with an expected candidate whose expected candidate is the only one with the highest score.

They are also broken down by the fields of `meta` of the dataset (`group` for `cases` and `hard_cases`) or of `--by` (e.g., `--by
case`): how many pairs there are and get the right answer and, when there are both positives and negatives, `same` and `AUC`.

## Results

With Laya 0.4.31, zero-shot, threshold 0.5:

| Dataset | Decider | Pairs | Precision | Recall | F1 | AUC | Best threshold (F1) | Top-1 |
|---|---|---|---|---|---|---|---|---|
| `cases` | `names` | 384 | 0.93 | 1.00 | 0.96 | 1.00 | 1.000 (0.97) | 0.99 |
| `cases` | `laya` | 384 | 0.73 | 0.62 | 0.67 | 0.89 | 0.408 (0.74) | 0.89 |
| `cases` | `laya/typed-decisions` | 384 | 0.62 | 0.70 | 0.66 | 0.84 | 0.479 (0.67) | 0.86 |
| `hard_cases` | `names` | 158 | 0.70 | 0.79 | 0.74 | 0.85 | 1.000 (0.78) | 0.70 |
| `hard_cases` | `laya` | 158 | 0.81 | 0.74 | 0.78 | 0.92 | 0.444 (0.82) | 0.94 |
| `hard_cases` | `laya/typed-decisions` | 158 | 0.78 | 0.85 | 0.82 | 0.92 | 0.524 (0.83) | 0.96 |
