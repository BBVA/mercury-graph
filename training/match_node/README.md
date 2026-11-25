# Training of match_node

`match_node` asks whether a mention is a known instance, and `MatchNodeLayaDecider` answers it with a Laya model. This folder
fine-tunes Laya on the datasets of [the data of match_node](../../data/match_node/README.md), such as the train split of ZESHEL; the
models it makes are evaluated with [the evaluation of match_node](../../evaluation/match_node/README.md).

- `export.py`: exports a dataset as data to fine-tune Laya on.
- `finetune.py`: fine-tunes Laya on that data and saves the checkpoint.
- `curves.py`: scores the model at every epoch of a fine-tune: the curves of the training.

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

## Fine-tuning

`finetune.py` fine-tunes `convaiinnovations/laya` (or `--base`) on the exported data, by default
`laya_data/zeshel_train.jsonl`, and saves the checkpoint in `checkpoints/<data>__<date>/` (which is not committed):

```bash
python -m training.match_node.finetune --epochs 6 --micro-batch 4 --checkpointing --keep-best
```

It follows the steps of `laya.train.finetune` with the same pieces of Laya, so that it trains the same model: it loads the base
model, turns the rows into items, holds out a calibration slice (10% of the items, 400 at most), trains, fits the temperature and
the abstention thresholds on the calibration slice and saves the checkpoint, which `laya.load()` and `MatchNodeLayaDecider` load
(`"model": <the folder>`, or `--decider laya:<folder>` in the evaluation). `--micro-batch 4 --checkpointing` trains on the same 64
rows per update with about 11 GB instead of 19 GB on Apple Silicon.

Before the training and at the end of every epoch, `curves.py` scores the model (temperature 1) on two samples of whole mentions:
500 mentions of the data it is trained on (none of their pairs is in the calibration slice) and 500 of `zeshel_val`, whose worlds it
never sees. The checkpoint keeps:

- `history.json`: for every epoch and sample, the log-loss, the accuracy, the mean confidence, the ECE and the Brier score of the
  pairs, with the training loss of Laya,
- `curves/<sample>__epoch_<n>.jsonl`: the score of every pair, as a run of the evaluation, so that the decisions of every epoch are
  scored with `python -m evaluation.match_node.score <file>`,
- `best/` with `--keep-best`: the checkpoint of the epoch with the lowest log-loss in val, calibrated as the final one,
- `finetune.json`: the arguments, the data, the versions, the time, the summary of the training and the best epoch.
