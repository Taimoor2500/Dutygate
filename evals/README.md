# Evaluation data

| dataset | rows | what it covers |
|---|---|---|
| `legal-triggers/dataset.jsonl` | 159 (104 positive, 55 clean) | all six categories, typos, slang, implicit phrasing, multi-flag, near-misses, prompt injection, Spanish, French, German, Arabic, Urdu |
| `outbound-claims/dataset.jsonl` | 66 (40 positive, 26 clean) | bot replies that claim actions, admit liability, state legal positions or promise outcomes |

Each line is `{"id", "message", "labels": [category...], "tags": [...], "lang", "channel"?}`.
An empty `labels` list means the message is clean.

**Caveat.** Both datasets are synthetic: they were written for this project by the same author
who wrote the keyword baselines and the pack questions. Treat them as a sanity check and a
regression suite, not a benchmark. To decide whether DutyGate works for *you*, build a labeled
set from your own (consented, anonymized) traffic. See `docs/labeling.md`.

## Running

```console
# keyword baseline, offline
dutygate eval packs/legal-triggers.yaml evals/legal-triggers/dataset.jsonl \
  --backend keyword --keywords evals/legal-triggers/keywords.yaml

# TypeSafe Jev, saving raw answers, with the baseline side by side
TYPESAFE_API_KEY=... dutygate eval packs/legal-triggers.yaml evals/legal-triggers/dataset.jsonl \
  --save-answers answers.jsonl --baseline evals/legal-triggers/keywords.yaml --report report.json

# tune thresholds offline from the saved answers (no API calls)
dutygate eval packs/legal-triggers.yaml evals/legal-triggers/dataset.jsonl \
  --replay answers.jsonl --sweep
```

## Keyword baseline results (legal-triggers)

Measured with `dutygate 0.1.0` on the bundled dataset:

| metric | keyword baseline |
|---|---|
| caught (routed or reviewed) | 48.1% |
| false review on clean messages | 12.7% |
| route precision | 87.7% |
| caught on non-English rows | 0.0% |
| caught on typo rows | 14.3% |
| caught on implicit rows | 25.0% |
| false review on near-misses | 27.3% |

## Keyword baseline results (outbound-claims)

| metric | keyword baseline |
|---|---|
| caught | 47.5% |
| false review on clean replies | 0.0% |
| route precision | 100.0% |

The acceptance targets from the design (caught ≥ 95%, false review ≤ 10%, and beating the
baseline on non-English, typo, slang and implicit rows) apply to a real, human-labeled set.
Jev results on this dataset have not been published yet: they need a live run with an API key.
