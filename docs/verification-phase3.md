# Phase 3 verification — extraction integrity audit

Record of the P3-08 integrity pass over the 25 locked development examples.

## Commands

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python scripts/audit_phase3.py

docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python -m unittest discover -s tests -v
```

JSON report: [`results/audit-phase3.json`](../results/audit-phase3.json).

## Results

| Check | Result |
| --- | --- |
| Development examples audited | 25 / 25 passed |
| Status `complete` + artifact/hash validation | ok |
| Base `Bf` / proposed `Bb` / direction `fixed_to_buggy` | ok |
| Trigger classes ⊆ `tests.all` | ok |
| One representation per test class | ok |
| Duplicate test IDs | none |
| Manifest Defects4J commit / seed match | ok |
| Evaluation examples marked complete | **0** (none processed) |
| Cli-30 live patch-direction sample | ok (`-` line in fixed, `+` line in buggy) |
| Model-state pipeline leakage | none in envelopes |

## Leakage policy

Serialized model states audited: patch `representation.txt` and each test
`representations/*.txt`.

- Pipeline envelopes (headers before `PROPOSED CODE CHANGE` /
  `TEST SOURCE`) must not contain bug IDs, checkout dir names, or private
  label field names.
- Full text must not contain trigger method IDs (`Class::method`) or
  `checkouts/fixed` / `checkouts/buggy`.
- Words such as `fixed`, `Defects4J`, or `expected result` inside authentic
  Java source bodies are **not** treated as leakage.

## Defects4J metadata exceptions

**None observed** on this development set. Every triggering class appears in
`tests.all`; no silent inventory patches were required.

## Related

- Dataset prepare summary: [`results/prepare_dataset-development.json`](../results/prepare_dataset-development.json)
- Phase 4 inputs: [`docs/phase4-handoff.md`](phase4-handoff.md)
