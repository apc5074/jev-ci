# Jev CI Test Selection Experiment

## 1. Research question

**Can Jev prioritize regression tests from a code change well enough to detect real regressions while running only a small fraction of the available test suite?**

The experiment tests a two-stage static test-selection system:

```text
code change
    ↓
BM25 candidate retrieval
    ↓
top 200 candidate test classes
    ↓
Jev probability scoring
    ↓
reranked test suite
    ↓
run highest-ranked tests first
```

The primary question is not whether Jev can determine with certainty whether an individual test will fail. It is:

> Given a real behavior-changing patch and a large set of existing tests, does Jev rank the tests that actually expose the resulting regression earlier than inexpensive retrieval baselines?

This is a **test prioritization / test impact analysis experiment**, not a binary classification experiment.

---

# 2. Why Defects4J is the dataset

Use **Defects4J 3.0.1**.

Defects4J currently contains 854 active reproducible bugs across Java projects. Each bug has a buggy revision and a fixed revision, and critically, at least one known _triggering test_ that fails on the buggy revision and passes after the fix. The fixes are source-code changes and have been manually minimized to remove unrelated changes.

That gives us three things for every example:

```text
fixed code
buggy code
known test(s) exposing the behavioral difference
```

We will invert the normal interpretation.

For bug `Lang-10`:

```text
fixed revision
     ↓
reverse patch
     ↓
buggy revision
```

We pretend the reverse patch is a newly proposed code change.

The question becomes:

> Which tests should CI run to catch the regression introduced by this change?

The Defects4J triggering tests are then exact known positives because they pass before the simulated change and fail after it.

This is significantly cleaner than showing Jev the historical bug-fix patch and asking which tests relate to it.

---

# 3. Experimental hypotheses

Freeze these before running the evaluation set.

### H1 — primary hypothesis

At a test budget of **10% of all test classes**, BM25→Jev detects a larger fraction of Defects4J regressions than BM25 alone.

Primary metric:

```text
Fault Detection Recall @ 10% Test Budget
```

### H2

Jev places the first known triggering test earlier in the ranking than BM25 and embedding similarity.

Measured with:

```text
MRR
normalized first-trigger rank
APFD
```

### H3

Jev approaches or exceeds the ranking performance of a cheap generative LLM reranker while requiring substantially less inference cost.

Comparator:

```text
GPT-5.4 nano
```

using the fixed snapshot:

```text
gpt-5.4-nano-2026-03-17
```

GPT-5.4 nano is explicitly positioned for high-volume tasks including classification and ranking, and supports structured output.

### Practical-success criterion

Call the Jev approach practically successful if either:

```text
Jev FDR@10%
    >= BM25 FDR@10% + 5 absolute percentage points
```

or:

```text
Jev performance is within 2 percentage points
of GPT-5.4 nano at FDR@10%

AND

Jev reranking cost <= 30% of the GPT reranking cost.
```

These thresholds must not change after evaluation results are visible.

---

# 4. Dataset composition

Use exactly five Defects4J projects:

```text
Cli
Lang
Math
Jsoup
JacksonDatabind
```

Reasons:

- all contain at least 30 active bugs;
- they represent multiple kinds of Java libraries;
- they avoid relying on a single repository's naming conventions;
- they contain enough examples for project-level analysis;
- they avoid making the experiment dominated by Closure's unusually large codebase.

Select exactly:

```text
30 bugs/project
5 projects
150 total bugs
```

The selection is deterministic.

For each project:

```python
rng = random.Random(20260922)
selected = rng.sample(sorted(active_bug_ids), 30)
```

Perform projects in this fixed order:

```text
Cli
Lang
Math
Jsoup
JacksonDatabind
```

Use the same RNG instance continuously rather than resetting it between projects.

For each project:

```text
first 5 selected bugs  → development set
remaining 25           → evaluation set
```

Final:

```text
development: 25 bugs
evaluation:  125 bugs
```

The 25 development bugs may be used to debug the implementation and ensure prompts are interpreted correctly.

**Do not report them in the headline evaluation.**

The 125 evaluation bugs remain untouched until every prompt, representation, model, candidate size, and metric is frozen.

---

# 5. Dataset manifest

The first data script creates:

```text
data/manifest.json
```

containing:

```json
{
  "defects4j_version": "3.0.1",
  "selection_seed": 20260922,
  "projects": {},
  "development_bug_ids": [],
  "evaluation_bug_ids": [],
  "created_at": "...",
  "git_commit": "..."
}
```

Also record:

```text
Defects4J git commit
Python version
Java version
OS
architecture
timezone
```

Never regenerate the split once evaluation has begun.

---

# 6. Environment

Use a Linux container rather than relying on a developer laptop environment.

Recommended base:

```text
Ubuntu 22.04
Python 3.12
Java 11
```

Defects4J states that its bugs were reproduced with Java 11 and that executions should use the timezone `America/Los_Angeles`; different settings can produce unexpected test behavior.

The container must set:

```bash
ENV TZ=America/Los_Angeles
```

Install:

```text
Java 11
Git
Subversion
Perl
cpanm
Python 3.12
```

Then:

```bash
git clone https://github.com/rjust/defects4j
cd defects4j
cpanm --installdeps .
./init.sh

export PATH="$PATH:/workspace/defects4j/framework/bin"
```

Validate with:

```bash
defects4j info -p Lang
```

Defects4J's documented setup requires Git, Subversion, Perl/cpanm, Java 11, and the initialization step above.

---

# 7. Repository layout

Use:

```text
jev-ci-test-selection/
│
├── Dockerfile
├── requirements.txt
├── experiment.yaml
├── EXPERIMENT.md
│
├── data/
│   ├── manifest.json
│   ├── bugs/
│   ├── patches/
│   ├── tests/
│   └── candidates/
│
├── cache/
│   ├── embeddings/
│   ├── jev/
│   └── gpt/
│
├── src/
│   ├── select_bugs.py
│   ├── checkout.py
│   ├── extract_patch.py
│   ├── extract_tests.py
│   ├── representations.py
│   ├── tokenize.py
│   ├── bm25.py
│   ├── embeddings.py
│   ├── jev_ranker.py
│   ├── gpt_ranker.py
│   ├── ranking.py
│   ├── metrics.py
│   ├── statistics.py
│   └── plots.py
│
├── scripts/
│   ├── prepare_dataset.py
│   ├── run_candidates.py
│   ├── run_jev.py
│   ├── run_gpt.py
│   └── evaluate.py
│
├── results/
│   ├── rankings/
│   ├── metrics.csv
│   ├── predictions.jsonl
│   ├── statistics.json
│   └── figures/
│
└── tests/
```

---

# 8. Constructing one experimental example

For each selected Defects4J bug `P-B`:

check out:

```bash
defects4j checkout -p P -v Bf -w fixed/
defects4j checkout -p P -v Bb -w buggy/
```

The **fixed revision is the base branch**.

The hypothetical pull request is:

```text
fixed → buggy
```

In other words, we deliberately reverse the real bug fix.

Call this:

```text
regression_patch
```

Never call it `bug_patch` or `reverse_fix` inside model state because those names would leak the answer.

---

# 9. Extracting the regression patch

From the fixed checkout obtain:

```bash
defects4j export -p classes.modified
defects4j export -p dir.src.classes
```

Obtain the corresponding properties from the buggy checkout if necessary.

Defects4J directly exposes `classes.modified`, source directories, test directories, all test classes, and triggering tests through `defects4j export`.

For every modified production source file:

```text
fixed source → buggy source
```

Generate a unified diff using:

```python
difflib.unified_diff(
    fixed_lines,
    buggy_lines,
    n=3
)
```

Thus:

```diff
- correct code
+ regression-producing code
```

The model sees exactly the proposed regression-introducing change.

### Patch representation

The representation is:

```text
MODIFIED FILES:
<paths>

MODIFIED CLASSES:
<FQCNs>

PROPOSED CODE CHANGE:

<unified diff>
```

Maximum:

```text
12,000 UTF-8 characters
```

Most minimized Defects4J patches should be comfortably smaller.

If longer than 12,000 characters:

```text
first 6,000 characters
+
"[...PATCH TRUNCATED...]"
+
last 6,000 characters
```

Store:

```text
patch_truncated = true/false
original_patch_chars
representation_chars
```

Do not create an LLM summary of the patch.

---

# 10. Ground truth

From the fixed checkout:

```bash
defects4j export -p tests.all
defects4j export -p tests.trigger
```

`tests.all` gives developer-written **test classes**.

`tests.trigger` gives **test methods** known to expose the bug.

Convert triggering methods such as:

```text
org.foo.ParserTest::testInvalidInput
```

to triggering classes:

```text
org.foo.ParserTest
```

For bug `b`:

```python
positive_classes[b] = {
    trigger.split("::")[0]
    for trigger in tests_trigger
}
```

### Important evaluation rule

Do **not** label every non-triggering test as a negative.

A non-triggering test may still be semantically related or useful; Defects4J only tells us that the known triggering tests definitely expose the bug.

Therefore:

**Do not report:**

```text
classification accuracy
precision
false positive rate
Brier score
AUROC
```

Those would incorrectly treat unlabeled tests as true negatives.

The experiment evaluates only **where known triggering tests appear in the ranking**.

---

# 11. Candidate test representation

Candidate source comes from the **fixed/base revision**, because that is what CI would possess before the proposed regression-producing change.

Determine:

```bash
defects4j export -p dir.src.tests
```

Map each FQCN in `tests.all` to its Java source file.

Handle nested classes by mapping:

```text
FooTest$Nested
```

to:

```text
FooTest.java
```

If the direct package path fails, recursively search for:

```text
<SimpleClassName>.java
```

If the source still cannot be found:

```text
source_missing = true
```

and use the FQCN alone.

Do not exclude the bug.

### Test source compacting

If source is <= 240 lines:

```text
use entire source
```

If source is > 240 lines:

1. Split into windows of 80 lines.
2. Use stride 60, giving 20-line overlap.
3. Tokenize the proposed patch.
4. BM25-score each window against the patch.
5. Select the top three windows.
6. Restore those windows to original source order.
7. Remove duplicate overlap lines.
8. Concatenate them.

Hard cap the final representation at:

```text
12,000 UTF-8 characters
```

Candidate state:

```text
TEST CLASS:
org.example.ParserTest

SOURCE FILE:
src/test/java/org/example/ParserTest.java

TEST SOURCE:
<compact representation>
```

The same representation is supplied to Jev and GPT.

---

# 12. Code tokenizer

All lexical retrieval uses exactly one tokenizer.

Algorithm:

```text
1. split at non-alphanumeric characters
2. split camelCase boundaries
3. split PascalCase boundaries
4. split snake_case
5. lowercase
6. discard empty tokens
7. discard tokens of length 1
```

Do not stem.

Do not remove English stopwords.

Do not remove Java keywords.

The objective is to keep the lexical baseline extremely transparent.

Example:

```text
parseHTTPResponse_v2
```

becomes approximately:

```text
parse
http
response
v2
```

---

# 13. BM25 baseline and candidate generator

Use standard BM25:

```text
k1 = 1.5
b  = 0.75
```

Corpus for each bug:

```text
all candidate test classes
```

Document:

```text
FQCN + entire available test source
```

Query:

```text
modified file paths
+
modified class names
+
regression patch
```

Rank every test class.

This complete ranking is:

```text
BM25
```

It is both:

1. a baseline;
2. candidate generation for expensive semantic rerankers.

---

# 14. Semantic shortlist

Take:

```text
K = min(200, number_of_test_classes)
```

from the BM25 ranking.

Freeze these candidate IDs to:

```text
data/candidates/<project>_<bug>.json
```

Once generated, Jev and GPT receive **exactly the same shortlist**.

Calculate:

```text
candidate_recall@200
```

defined as:

> fraction of evaluation bugs where at least one known triggering class appears in the BM25 top 200.

This is the maximum fraction of bugs for which reranking the top 200 can move a triggering test ahead of the BM25 tail.

Do not increase `K` after seeing this number.

---

# 15. Random baseline

Generate **1,000 random test-suite permutations per bug**.

Seed:

```python
random.Random(1337 + evaluation_bug_index)
```

Report the mean metric across these permutations.

This provides expected random ranking performance.

---

# 16. Embedding baseline

Use:

```text
text-embedding-3-small
```

The model currently costs $0.02/M input tokens and is intended for similarity/search tasks.

Embed the compact regression patch representation.

Embed every compact test representation.

Cosine similarity:

```python
score = dot(q, d) / (norm(q) * norm(d))
```

Rank **all test classes** by descending similarity.

Cache embeddings permanently.

Ranking name:

```text
Embedding
```

No combination with BM25.

---

# 17. Jev configuration

At the start of the experiment call:

```text
GET /v1/models
```

The official TypeSafe API documents this endpoint for discovering model names.

Store the response in:

```text
results/typesafe_models.json
```

Use the exact stable Jev model ID returned at experiment start.

Do **not** use:

```text
jev-latest
```

for final evaluation because aliases may change.

Record:

```text
jev_model_id
API provider
date
```

TypeSafe currently describes Jev as returning typed decisions with probabilities rather than generated prose, and currently advertises input pricing of $42 per billion tokens with free output tokens.

---

# 18. Jev scoring task

Perform **one Noul decision per patch/test-class pair**.

Do not put multiple candidate classes in the same model state.

Run calls concurrently.

State:

```json
{
  "code_change": "<regression patch representation>",
  "candidate_test": "<candidate test representation>"
}
```

Question ID:

```text
would_detect_regression
```

Use a Noul because the desired output is directly interpretable as:

```text
P(yes)
```

Prompt:

```text
A code change is proposed against a working codebase.

The candidate test class already exists in the codebase.

Would this test class be likely to expose an incorrect behavioral
regression caused by the proposed code change if such a regression
exists?

Answer YES when the test exercises behavior affected by the changed
code and its assertions could plausibly fail because of an incorrect
change.

This includes indirect behavioral relationships across methods or
classes.

Do not require exact identifier or filename overlap.

Answer NO when the test is merely in the same project or discusses
similar vocabulary but is unlikely to execute or validate behavior
affected by this change.
```

Criteria:

```text
true:
The test exercises and checks behavior that could be affected by the
proposed code change, so an incorrect implementation could cause this
test to fail.

false:
The test does not meaningfully exercise or validate behavior affected
by the proposed change, even if names or vocabulary overlap.
```

Score:

```python
jev_score = answer.noul
```

No threshold is used.

The probability is purely a ranking score.

---

# 19. Jev ranking

For the BM25 top 200:

```text
sort descending by jev_score
```

Tie-break using:

```text
original BM25 rank
```

Then append all tests outside the top 200 in their original BM25 order.

Final ranking:

```text
Jev
```

Therefore Jev can improve or worsen the shortlist but cannot magically retrieve candidates that BM25 did not surface.

That is intentional.

---

# 20. Generative LLM baseline

Use:

```text
gpt-5.4-nano-2026-03-17
```

with:

```text
reasoning effort = none
```

The current model documentation explicitly describes it as suited to classification and ranking and lists the fixed snapshot above.

Feed exactly the same:

```text
regression patch representation
candidate test representation
```

and the same semantic rubric used for Jev.

Request structured output:

```json
{
  "probability": 0.0
}
```

Instruction:

```text
Return a number from 0 to 1 estimating how likely this existing test
class is to expose an incorrect behavioral regression caused by the
proposed code change.

Use the provided rubric. Return only the structured probability.
```

Use one request per candidate.

No chain-of-thought is requested or stored.

Rank BM25 top 200 by probability, tie-breaking by BM25 rank.

Append remaining tests in BM25 order.

Ranking:

```text
GPT-Nano
```

---

# 21. API concurrency

For both Jev and GPT:

```text
max concurrent requests = 16
```

Retry:

```text
429
500
502
503
529
network timeout
```

Maximum:

```text
3 retries
```

Backoff:

```text
1 second
2 seconds
4 seconds
```

If a request still fails, store the failure.

Do not substitute `0.5`.

Do not omit the test.

Final evaluation begins only after every required candidate has a valid model score.

---

# 22. API caching

Every semantic request gets a SHA-256 cache key:

```text
SHA256(
    provider
    + model_id
    + prompt_version
    + serialized_state
    + serialized_question
)
```

Store:

```json
{
  "cache_key": "...",
  "bug_id": "...",
  "test_class": "...",
  "model": "...",
  "score": 0.83,
  "input_tokens": 4211,
  "output_tokens": 0,
  "latency_ms": 182,
  "provider_request_id": "...",
  "timestamp": "..."
}
```

Never issue a paid call twice when an exact cache entry exists.

---

# 23. Rankings being evaluated

The final experiment has exactly five systems:

```text
Random
BM25
Embedding
BM25 → Jev
BM25 → GPT-5.4 nano
```

No additional system may be added to the headline table after seeing results.

Additional experiments must be labeled post-hoc/exploratory.

---

# 24. Primary metric: Fault Detection Recall at 10%

For bug `b`:

```text
N_b = number of available test classes
P_b = known triggering test classes
```

Budget:

```python
k = max(1, ceil(0.10 * N_b))
```

The bug is detected when:

```python
any(trigger in ranking[:k] for trigger in P_b)
```

Then:

```text
FDR@10% =
number of detected bugs
/
number of evaluation bugs
```

This answers:

> If CI ran only the top 10% of test classes, how often would it execute at least one test known to catch the regression?

This is the single **primary outcome**.

---

# 25. Secondary budget metrics

Also calculate:

```text
FDR@1%
FDR@2%
FDR@5%
FDR@20%
FDR@50%
FDR@100%
```

Always use:

```python
max(1, ceil(fraction * N))
```

Plot these as the test-budget curve.

---

# 26. Mean Reciprocal Rank

For each bug find:

```text
r_b = rank of earliest triggering test class
```

where rank begins at 1.

Then:

```text
RR_b = 1 / r_b
MRR  = mean(RR_b)
```

Higher is better.

---

# 27. Normalized first-trigger rank

For every bug:

```text
NFTR_b = r_b / N_b
```

Report:

```text
median NFTR
mean NFTR
```

Interpretation:

```text
NFTR = 0.08
```

means a triggering test appears after approximately 8% of test classes.

Lower is better.

---

# 28. APFD

Because each Defects4J example represents one underlying fault, calculate:

```text
APFD_b = 1 - (r_b / N_b) + 1/(2*N_b)
```

Average across bugs.

Higher is better.

This gives a conventional test-prioritization-style metric while remaining equivalent to rewarding earlier detection of the single known fault.

---

# 29. Do not claim runtime reduction

The primary resource budget is:

```text
fraction of test classes executed
```

not wall-clock CI duration.

Test classes have unequal runtimes.

Therefore conclusions must say:

> “reduced test-class execution budget”

rather than:

> “reduced CI runtime by 90%.”

Actual execution-time measurement can be a later experiment.

---

# 30. Cost metrics

Store actual provider usage for every call.

Calculate:

```text
total reranking input tokens
total reranking output tokens
total API dollars
mean dollars / bug
mean dollars / candidate
```

Store a:

```text
pricing_snapshot.json
```

containing provider prices used for the calculation and retrieval date.

Do not recompute historical experiment cost using future pricing.

---

# 31. Latency metrics

Measure client-observed request time:

```text
request sent → full response received
```

Report per model:

```text
p50 candidate latency
p95 candidate latency
mean candidate latency
total wall-clock time to score one 200-test shortlist
```

Use concurrency 16 for the shortlist-wall-clock comparison.

Network/provider latency will be noisy, so treat cost and ranking quality as stronger evidence than small latency differences.

---

# 32. Statistical analysis

All comparisons are paired by bug.

### Primary comparison

```text
Jev vs BM25
on FDR@10%
```

Create a 2×2 table:

```text
                BM25 detected   BM25 missed
Jev detected
Jev missed
```

Use:

```text
McNemar exact test
```

Report:

```text
Jev-only detections
BM25-only detections
both
neither
```

Do not report only a p-value.

### Bootstrap confidence intervals

Use:

```text
10,000 paired bootstrap samples
```

Resample the 125 evaluation bug IDs with replacement.

For every sample calculate:

```text
Δ FDR@10%
Δ MRR
Δ APFD
Δ median NFTR
```

Report 95% percentile intervals.

Perform the same comparisons for:

```text
Jev vs Embedding
Jev vs GPT-Nano
```

but mark those as secondary comparisons.

---

# 33. Project-level analysis

Report results separately for:

```text
Cli
Lang
Math
Jsoup
JacksonDatabind
```

Do not perform significance claims on 25-bug project subsets.

Project-level numbers are descriptive.

The purpose is to determine whether an overall effect comes entirely from one codebase.

---

# 34. Candidate-generation ceiling

Report:

```text
BM25 trigger recall@200
```

If a trigger lies outside the top 200, Jev cannot move it.

For Jev failures classify:

```text
candidate generation failure:
    no triggering class in BM25 top 200

reranker failure:
    trigger was in top 200 but Jev ranked it poorly
```

This distinction is mandatory.

---

# 35. Development-set rules

The 25 development bugs can be used to catch:

```text
broken source extraction
wrong reverse diff
incorrect trigger parsing
prompt misunderstanding
API schema errors
ranking bugs
```

You may inspect development results manually.

You may **not** repeatedly rewrite the Jev prompt simply to maximize dev-set scores.

Allow at most:

```text
one semantic prompt revision
```

after the first complete development run.

Once revised:

```text
freeze prompt_version = v1
```

Commit it.

No changes after evaluation begins.

---

# 36. Preregistration file

Before running any of the 125 evaluation bugs, commit:

```text
EXPERIMENT.md
```

containing:

```text
dataset
selected bug IDs
dev/eval split
patch direction
representations
candidate K=200
BM25 configuration
embedding model
Jev model
Jev prompt
GPT model
GPT prompt
metrics
primary hypothesis
success criteria
statistics
```

Tag the git commit:

```text
experiment-v1-frozen
```

Store that commit hash in every result file.

---

# 37. Integrity tests before evaluation

Automated tests must verify:

### Patch direction

For every example:

```text
BASE = fixed
PROPOSED = buggy
```

Never reversed.

### Trigger consistency

Every triggering class must belong to the exported test-suite metadata unless Defects4J metadata explicitly indicates otherwise.

### No label leakage

The model states must never contain:

```text
bug ID
issue title
tests.trigger
triggering method
"buggy"
"fixed"
expected result
Defects4J metadata labels
```

### Ranking integrity

Every method must return:

```text
exactly N unique test classes
```

with no duplicates or missing classes.

### Jev/GPT shortlist equality

Both semantic rerankers must receive exactly the same BM25 top-200 IDs.

---

# 38. Evaluation output schema

Create one row per:

```text
bug × method
```

in:

```text
results/metrics.csv
```

Fields:

```text
project
bug_id
split
method
num_test_classes
num_trigger_classes
first_trigger_rank
normalized_first_trigger_rank
detected_at_1pct
detected_at_2pct
detected_at_5pct
detected_at_10pct
detected_at_20pct
detected_at_50pct
reciprocal_rank
apfd
candidate_trigger_in_top200
reranker_input_tokens
reranker_output_tokens
reranker_cost_usd
reranker_wall_ms
patch_truncated
missing_test_source_count
```

Also save all raw scores to:

```text
results/predictions.jsonl
```

Never make plots directly from API responses.

All plots must derive from these frozen result files.

---

# 39. Required headline table

Produce:

| Method       | FDR@5% | FDR@10% | FDR@20% | MRR | APFD | Median NFTR | Cost/Bug |
| ------------ | -----: | ------: | ------: | --: | ---: | ----------: | -------: |
| Random       |        |         |         |     |      |             |        — |
| BM25         |        |         |         |     |      |             |        — |
| Embedding    |        |         |         |     |      |             |          |
| Jev          |        |         |         |     |      |             |          |
| GPT-5.4 nano |        |         |         |     |      |             |          |

Bold only the numerically highest result in each quality column.

Do not hide losing metrics.

---

# 40. Required figures

## Figure 1 — Fault detection vs test budget

X-axis:

```text
% of test classes executed
```

Y-axis:

```text
fraction of regressions detected
```

Lines:

```text
Random
BM25
Embedding
Jev
GPT-Nano
```

Points:

```text
1%
2%
5%
10%
20%
50%
100%
```

This is the main figure.

## Figure 2 — First-trigger rank distribution

CDF:

```text
x = normalized first-trigger rank
y = fraction of bugs detected
```

This shows the whole ranking rather than arbitrary cutoffs.

## Figure 3 — Performance by project

FDR@10% grouped by project.

## Figure 4 — Quality versus cost

X:

```text
mean reranking cost / bug
```

Y:

```text
FDR@10%
```

Methods:

```text
Embedding
Jev
GPT-Nano
```

---

# 41. Failure analysis

Only begin manual failure analysis after aggregate results are frozen.

Select:

```text
10 largest Jev improvements over BM25
10 largest Jev regressions versus BM25
```

using:

```text
BM25 first-trigger rank - Jev first-trigger rank
```

for gains and the inverse for losses.

No hand-picking.

For every case classify the dominant phenomenon:

```text
identifier/name match
behavioral semantic match
cross-class relationship
test source provided useful clue
BM25 candidate-generation miss
Jev overvalued superficial similarity
Jev missed indirect dependency
large/truncated patch
large/truncated test
ambiguous test responsibility
```

Write short qualitative examples without feeding these observations back into the experiment.

---

# 42. Interpretation rules

### Strong positive result

Example:

```text
BM25 FDR@10%       61%
Embedding          64%
Jev                75%
GPT-Nano           76%
```

combined with materially lower Jev cost.

Conclusion:

> A cheap decision model provided useful semantic test-impact reranking beyond lexical and embedding retrieval and approached generative-model reranking quality.

### Moderate result

Example:

```text
BM25               61%
Jev                 65%
GPT-Nano            74%
```

Conclusion:

> Jev adds measurable semantic signal but does not replace a generative reranker when ranking quality is the primary goal.

### Negative result

Example:

```text
BM25               66%
Jev                 64%
```

Conclusion:

> Pointwise Jev judgments did not improve static regression-test prioritization over simple lexical retrieval in this setup.

That is still a valid finding.

### Candidate-generation failure

If:

```text
BM25 trigger recall@200 = 70%
```

then the system is strongly candidate-generation limited.

Do not conclude:

> “Jev cannot perform test selection.”

Conclude:

> “The evaluated BM25→Jev pipeline is bottlenecked by first-stage candidate retrieval.”

---

# 43. Claims this experiment does NOT support

Do not claim:

```text
90% lower CI runtime
Jev understands code better than LLMs
Jev replaces coverage analysis
Jev identifies every affected test
non-triggering tests are irrelevant
the probabilities are perfectly calibrated
```

The experiment supports only claims about **ranking known fault-revealing test classes under a static test-selection setup**.

---

# 44. Execution order

Agents must perform the work in this sequence:

1. Build the Docker environment.
2. Install and validate Defects4J.
3. Generate the deterministic 150-bug manifest.
4. Check out fixed and buggy revisions.
5. Extract test metadata and reverse patches.
6. Build test representations.
7. Verify patch direction and label parsing.
8. Run the 25-bug development set.
9. Fix implementation bugs.
10. Allow at most one Jev prompt revision.
11. Freeze `EXPERIMENT.md`.
12. Commit/tag `experiment-v1-frozen`.
13. Generate BM25 rankings for all 125 evaluation bugs.
14. Freeze top-200 candidate lists.
15. Generate embeddings and full embedding rankings.
16. Score identical top-200 candidates with Jev.
17. Score identical top-200 candidates with GPT-5.4 nano.
18. Assemble complete rankings.
19. Calculate metrics.
20. Freeze `metrics.csv` and `predictions.jsonl`.
21. Run paired bootstrap analysis.
22. Run McNemar analysis.
23. Generate figures.
24. Perform deterministic failure analysis.
25. Write README/research report.

Agents must not alter earlier steps based on evaluation results.

---

# 45. 48-hour scope

The project should prioritize the experiment over presentation.

### First block

Complete:

```text
environment
Defects4J
manifest
checkout pipeline
reverse-patch extraction
trigger extraction
test representations
```

### Second block

Complete:

```text
BM25
embedding baseline
Jev client
GPT baseline
caching
dev run
```

Then freeze the experiment.

### Third block

Run:

```text
125 evaluation bugs
Jev scoring
GPT scoring
metrics
statistics
```

### Final block

Produce:

```text
four figures
headline table
failure analysis
README
short research writeup
```

Do not build a frontend.

Do not train a model.

Do not implement GitHub Actions integration yet.

Do not add dynamic code coverage yet.

Those are follow-up work.

---

# 46. Agent completion criteria

The experiment is finished only when all of these exist:

```text
data/manifest.json
EXPERIMENT.md
125 complete evaluation examples
all five full rankings per example
all semantic calls cached
metrics.csv
predictions.jsonl
statistics.json
four required figures
headline result table
20-case failure analysis
README containing methodology and conclusion
```

And this command succeeds from a clean environment:

```bash
python scripts/evaluate.py
```

without making any paid API requests.

It must regenerate:

```text
metrics
statistics
tables
figures
```

from the cached raw predictions.

---

# 47. Final experiment in one sentence

The experiment takes **125 real historical Java regressions**, represents each as a code change from the working version to the defective version, asks several static ranking systems which existing test classes should run first, and measures how quickly each system surfaces a test that is known to actually fail because of that regression.

That is the cleanest version of the Jev test-selection idea.

## Pre-freeze amendment: test representation version 2

Section 11's long-source compaction rule is superseded by
[the version 2 contract](../docs/test-representations.md): reserve the first 40
source lines, select up to three 80-line windows at stride 60 by BM25 score times
the fraction of unseen lines, and retain at most 240 source lines with explicit
omission markers. The 12,000-character cap remains. This amendment is not based
on evaluation results and has not demonstrated an accuracy improvement. Both
semantic rankers must receive the same version; freeze it in Phase 6.
