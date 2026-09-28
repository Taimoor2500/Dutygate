# Building a real evaluation set

The bundled datasets are synthetic. Before relying on DutyGate, measure it on messages that
look like your own traffic.

## 1. Get permission first

Use messages you are allowed to process for this purpose: consented, or covered by your
privacy notice and a legitimate-interest assessment. Anonymize before labeling:
- remove names, emails, phone numbers, addresses and account ids
- replace them with placeholders like `[NAME]`

## 2. Sample

Aim for **at least 100 positive** messages, with a similar number of clean ones.
- **Positives are rare.** A random sample will contain very few, so pull likely candidates
  from escalations, complaint tags, keyword hits and agent notes.
- **Clean messages** should include hard near-misses: "stop" about an app crash, "lawyer" in
  passing, refund requests with no bank involved.
- **Cover** each language and channel you support.

## 3. Label

Each row takes this shape:

```json
{"id": "r-0001", "message": "...", "labels": ["opt_out"], "tags": ["typo"], "lang": "en", "channel": "sms"}
```

- **Labels** are the pack's categories. A message can have several. Leave `labels` empty for
  clean messages.
- **Label the obligation, not the mood.** An angry message with no request is clean.
- **Two labelers per message**, working independently. Resolve disagreements with a third
  person (ideally someone from compliance) and record the rules you agree on.
- **Tags** help slice results: `typo`, `slang`, `implicit`, `non-english`, `multi-flag`,
  `near-miss`, `adversarial`.

## 4. Measure

```console
dutygate eval packs/legal-triggers.yaml my-set.jsonl --save-answers answers.jsonl \
  --baseline evals/legal-triggers/keywords.yaml --report report.json
dutygate eval packs/legal-triggers.yaml my-set.jsonl --replay answers.jsonl --sweep
```

Acceptance targets from the design, as a starting point:
- **Caught** (routed or reviewed): at least 95% of true triggers.
- **False review rate** on clean messages: no higher than 10%.
- **Beats the keyword baseline** on non-English, typo, slang and implicit rows.

Read the misses. Most fixes are wording changes to a question's `criteria`. Bump the pack's
`version` whenever you change it, and re-record the answers, because the questions digest
changes.
