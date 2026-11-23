# Training of match_node

`match_node` asks whether a mention is a known instance, and `MatchNodeLayaDecider` answers it with a Laya model. This folder
fine-tunes Laya on the datasets of [the data of match_node](../../data/match_node/README.md), such as the train split of ZESHEL; the
models it makes are evaluated with [the evaluation of match_node](../../evaluation/match_node/README.md).

- `export.py`: exports a dataset as data to fine-tune Laya on.

Run them from the root of the repository. They need Laya (`pip install laya`, Python 3.10 or later).

## Data to fine-tune Laya

`export.py` writes every pair of a dataset as a row of the JSONL format of `laya.train` (`laya-train --data`), by default in
`laya_data/<dataset>.jsonl` (which is not committed):

```bash
python -m training.match_node.export data/match_node/zeshel_data/zeshel_train.jsonl
python -m training.match_node.export data/match_node/zeshel_data/zeshel_val.jsonl
```

A row has the `state` and the `questions` that `MatchNodeLayaDecider` asks the model, the `expected` answer (`{"same": <gold>}`) and
the pair in `meta`:

```json
{"state": {"known_instance": {...}, "mention": {...}}, "questions": {"same": {...}}, "expected": {"same": true},
 "meta": {"mention_id": "...", "id": "..."}}
```

The state and the questions are created by `MatchNodeLayaPrompter` from the arguments the Formalizer gives the Decider (with the
definition of the type of the mention), as when the Decider is run, so that the model is trained on the same input it is asked.
