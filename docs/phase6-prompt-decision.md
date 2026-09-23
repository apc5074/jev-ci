# P6-03 — Final prompt decision

**Decision: retain the original Jev prompt. Semantic revision count: 0.**
The final preregistration name is **v1**. Its existing cache version remains
`jev-would_detect_regression-v1`; no cache migration or repeat inference is needed.
The GPT rubric, task wrapper, response schema, and message template are frozen
alongside it as `gpt-would_detect_regression-v1`.

P6-03 is complete under the availability exception already accepted in P6-01 and
P6-02. This does **not** mean all Jev scores exist or that evaluation may begin.

## Interpretation review

Reviewed the original instructions and true/false criteria against `overall.md`
sections 18, 20, and 35, the all-25 development baseline, and P6-02 defect triage.
The prompt explicitly asks about behavioral impact and assertions, permits
indirect relationships, and rejects vocabulary overlap alone. It uses a Noul
probability for exactly one saved patch/test-class pair.

The following development cases were examined for possible misunderstanding.
Their saved patches, compact test text, and ranking outputs were inspected;
selection was diagnostic, not an attempt to optimize the development score.

| Case | Evidence | Interpretation |
| --- | --- | --- |
| Cli-1 | `BugCLI13Test` asserts long/short option lookup affected by the CommandLine change. It receives 0.92, tied with two earlier classes; original BM25 order places it third. | A tied ordinal miss does not show failure to recognize the relevant behavior. |
| Math-7 | The patch changes event-state advancement/reset in AbstractIntegrator. `OverlappingEventsTest` exercises overlapping events with DormandPrince853Integrator and scores above the known trigger. | An indirect integration relationship is consistent with the stated task. It does not establish actual fault detection by that class. |
| JacksonDatabind-95 | Changes affect TypeFactory generic bindings and TypeParser. Top-ranked `TestTypeFactory1604` asserts specialized generic types. The known trigger is ninth. | Plausible related assertions are recognized; the lower trigger position alone is insufficient evidence of a misunderstood question. |
| JacksonDatabind-28 | The change affects ObjectNode deserialization token handling. Top-ranked `TestTreeDeserialization` includes ObjectMapper tree deserialization assertions. The known trigger is sixth. | Broad behavioral relevance is plausible; these outputs do not justify rewriting the rubric to target known trigger labels. |

These are limited observations about consistency with the task, not access to
model reasoning or proof that every judgment is correct. No demonstrated
misunderstanding warrants the optional semantic revision. There was no before/after
prompt experiment and no second variant was generated or scored. The provider WAF
failure concerns request availability, not interpretation of the question.

## Exact final artifacts

- [Jev v1](../prompts/jev/v1.json): exact question ID, Noul type, instructions,
  true/false criteria, and one-pair state field names.
- [GPT v1](../prompts/gpt/v1.json): exact shared rubric, task wrapper, schema, and
  complete chat message template. Placeholders stand for the saved representation
  strings; runtime construction must match `build_gpt_messages` exactly.
- [Decision record](../results/phase6/prompt_decision.json): zero-revision history,
  source commit, evidence hashes, artifact hashes, and the accepted gap.
- [Final cache inventory](../results/phase6/final_prompt_cache_inventory.json):
  every required development candidate's exact-input key and existing response
  file hash, plus observed model identities. This references the original cached
  responses without modifying or duplicating them.

Hashes use SHA-256 of file bytes. The verifier compares prompt snapshots against
runtime builders, rebuilds keys from current saved development inputs, validates
cached records, and compares the complete inventory. Differences fail verification
and require explicit review; this command never performs inference or writes files.

```bash
python3 scripts/verify_phase6_prompts.py
```

## Development coverage and exception

Verification passed across all 25 manifest development bugs:

| System | Valid required cached pairs | Complete bug shortlists |
| --- | ---: | ---: |
| Jev | 2691 / 2692 | 24 / 25 |
| GPT-Nano | 2692 / 2692 | 25 / 25 |

The only missing pair remains **Jsoup-70 / org.jsoup.integration.ConnectTest /
Jev**, A-001: OpenRouter WAF HTTP 403 on the original representation. The prior
[Phase 5 handoff](phase5-handoff.md) explicitly permits Phase 6 continuation with
this gap. No score was fabricated and no representation was edited to bypass it.
The literal requirement for complete final development Jev output remains unmet
by one pair; ticket completion inherits this documented exception, rather than
asserting full coverage. P6-04/P6-06 must settle availability before the evaluation
freeze. Model pinning is also a P6-04 decision, separate from freezing prompt text.

No new inference calls were made. Existing prompts, responses, candidate sets,
representations, and ranking rules were preserved. No evaluation example or
outcome was read or used in this decision; only split IDs in the locked manifest
were available. This is a prompt decision artifact, not the P6-07 experiment tag.
