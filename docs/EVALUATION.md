# Evaluation Plan

## Goal

Evaluation asks whether the classifier is useful for the current literature-review task. It does not score paper quality. Version 0.1 provides the existing primary-category baseline and a locked, offline five-field heldout evaluator for frozen artifacts. It also records fields needed for later extraction and latency measurements.

The completed v0.1.1 pilot and prompt comparison are recorded in [EVALUATION_RESULTS.md](EVALUATION_RESULTS.md), with the fixed evidence scope and labeling rules in [EVALUATION_RUBRIC.md](EVALUATION_RUBRIC.md). The sample contains eight papers and three categories. Later prompt comparisons reuse that development set and do not establish general model performance.

## Ground-truth workflow

The public `data/ground_truth.csv` is a header-only template for the category CLI, with these columns:

| Column | Meaning |
|---|---|
| `file_hash` | Stable SHA-256 identity; do not use a private filepath as the identifier |
| `title` | Human-readable reference for review |
| `ground_truth_category` | Category assigned by a human after reading enough of the paper |
| `ai_primary_category` | Original, unedited AI category |
| `reviewer_notes` | Optional short explanation for ambiguous decisions |

Keep the checked-in template empty. Prepare an ignored local copy with the same category columns, for example `data/category-evaluation.local.csv`, and enter independently reviewed labels there. Preserve existing local Ground Truth files; do not overwrite them. The v0.1.1 multi-field reference also records review status and rubric/normalization versions, as specified in the rubric. Do not publish private reference rows, titles, hashes or review working files.

Recommended procedure:

1. Define the category rubric before inspecting model output.
2. Sample across categories, years, venues, and easy/ambiguous cases rather than choosing only obvious papers.
3. Have the reviewer assign ground truth without looking at `ai_primary_category` when possible.
4. Preserve the original AI value, not the user-corrected current value.
5. Document disagreements and refine the rubric separately from the test set.

For a portfolio demonstration, report sample size and class distribution next to every metric. Accuracy from a small or strongly imbalanced set should be labeled preliminary.

## Baseline command

```powershell
if (-not (Test-Path -LiteralPath data/category-evaluation.local.csv)) {
    Copy-Item data/ground_truth.csv data/category-evaluation.local.csv
}
# Fill the local copy with reviewed category labels before evaluating.
.\.venv\Scripts\python.exe scripts/evaluate.py data/category-evaluation.local.csv
```

Rows missing either category are excluded. The script reports:

- primary-category accuracy;
- per-category precision;
- per-category recall;
- per-category F1;
- per-category support.

No external ML library is required, which keeps the evaluation calculation auditable.

## Local / OpenAI / Human comparison

```powershell
.\.venv\Scripts\python.exe scripts/evaluate.py --database data/papers.db
```

This reads SQLite in read-only mode and reuses the category Accuracy/Precision/Recall/F1 calculation. It joins successful classification_runs to explicitly reviewed current category labels, groups by provider/model and takes the latest success per PDF hash within each group. Retries do not inflate sample size; failed and unreviewed records are excluded. Historical runs with unknown provenance appear under unknown rather than being guessed to be OpenAI.

Changing the provider/model does not automatically resubmit classified papers. Intentional comparison scans use `scan_inbox(..., reclassify=True)` and retain original history and Human Review values. Record the model, rubric and sample size with results. Groups may cover different papers; use a matched cohort when making a direct model comparison. Reviewing AI proposals can bias the reference labels; independently assigned ground truth remains preferable.

The database comparison command evaluates primary category. The separate frozen-artifact command below evaluates all five fields without selecting runs from history. The multi-field exact-match and micro-F1 results in the v0.1.1 report were calculated by one-off local helper scripts; those scripts and private inputs are not part of the public CLI. Individual evaluation data is excluded from Git, so the published pilot is an aggregate report rather than a bundled dataset for reproducing those counts.

## Metric definitions

For category `c`:

- **Precision:** of papers predicted as `c`, the fraction whose ground truth is `c`.
- **Recall:** of papers whose ground truth is `c`, the fraction predicted as `c`.
- **F1:** harmonic mean of precision and recall.
- **Accuracy:** fraction of all evaluated papers with an exact primary-category match.

The frozen-artifact evaluator includes macro Precision/Recall/F1 and confusion matrices with fixed class orders. Multi-label fields use exact-set match and micro/macro Precision/Recall/F1 under the unchanged rubric normalization-v1.

## Metadata extraction evaluation

Create a separate reviewed table for title, authors, year, venue, abstract, and keywords. For each field record whether it is:

- exact;
- acceptable after normalization;
- missing when present in the document;
- incorrectly extracted;
- not available in the source.

Report success rate per field. Do not count a genuinely unavailable value as an extraction failure. Image-only PDFs should be reported separately because v0.1 has no OCR.

## Processing-time evaluation

`papers.processing_seconds` records the latest non-skipped scanner attempt, including hashing, parsing, extraction, input gating and classifier generation/validation. New inserts and retries save the value for successful, pending, failed and review-held attempts; skipped papers retain their previous duration. It excludes subsequent DB writes, result logging and UI rendering, and is not AI-only latency. History has no per-run timing. See [ARCHITECTURE.md](ARCHITECTURE.md#processing-duration) for the exact boundary. Future reporting should separate parsing from inference and report median, p90, model and environment context.

## Threats to validity

- One reviewer can encode subjective category preferences.
- Categories overlap even though primary category is single-label.
- A collection focused on session security may hide weak performance on other categories.
- Changing prompts or models after seeing test results can overfit the evaluation set.
- Metadata extraction quality varies significantly by publisher layout and scanned versus text PDFs.

Use a frozen holdout set for any serious comparison between prompts or models, version the rubric, and report uncertain cases instead of forcing false precision.

## Locked heldout Evaluation Dataset v1

IDs 1–8 are development / historical tuning; IDs 9–40 are the locked heldout set (n=32). Do not subdivide the heldout cohort or combine it with development scores. The original freeze continues to describe candidate roles at freeze time; the later split-v1 lock is a separate artifact.

Ground Truth provenance: **AI-assisted Ground Truth draft, independently reviewed and finally approved by a human reviewer.** Individual frozen AI predictions were not used to make label decisions or compared during drafting. Preflight requested the complete manifest (truncated display), and tooling exposed an aggregate assertion. This documented procedural deviation prevents claiming strict non-exposure blinding. The human approved all 32 candidates without corrections. IDs 1–8 reuse existing reviewed values without re-review.

All real inputs, canonical GT, split, protocol and raw results are ignored local artifacts. The public CSV remains a header-only template. The JSON GT and split use a `content` envelope with SHA-256 `content_digest`; creation timestamps are outside the digest. GT records retain raw values separately from predictions and carry `paper_id`, `file_hash`, split role and the five fields. The protocol is similarly locked before scoring and must exactly match `evaluation-protocol-v1` in `scripts/evaluation_v1.py`.

```powershell
.\.venv\Scripts\python.exe scripts/evaluate.py `
  --frozen-manifest data/evaluation-dataset-v1/freeze-manifest.json `
  --ground-truth data/evaluation-ground-truth-v1/ground-truth-v1.json `
  --split data/evaluation-ground-truth-v1/split-v1.json `
  --protocol data/evaluation-results-v1/evaluation-protocol-v1.json
```

This command reads explicit JSON paths and prints deterministic JSON. It validates dataset/content identities, GT approval, rubric and normalization versions, unique IDs/hashes, exact development/heldout roles and the protocol lock. It joins by ID and file hash and uses only the freeze-time current AI prediction. It does not access SQLite, history or a provider. Invalid/missing fields cause an error, rather than silent exclusion. Existing CSV and database CLI behavior is preserved.

Primary class order: Authentication; Session Management; Authorization; Token Security; OAuth / OIDC / SSO; Account Management; Vulnerability Assessment; Other Security. Relevance order: A, B, C. Both report Accuracy, micro Precision/Recall/F1 (all equal Accuracy for single-label classification), macro Precision/Recall/F1, class support and confusion matrices (GT rows, prediction columns). Macros include all fixed eight/three classes, including absent classes. Zero division is 0; absent support does not establish class performance.

Tags, Research Methods and Target Vulnerabilities report normalized exact-set match, micro Precision/Recall/F1 and macro Precision/Recall/F1 on the sorted heldout GT/prediction label union, plus per-label support. Zero division is 0. Explicit empty/empty sets count as an exact match; an empty label union has macro 0. Missing values are invalid, not empty sets. Only rubric-v1 whitespace cleanup, its field-specific exact alias dictionary and exact canonical deduplication apply. Unregistered spelling/case remains unchanged; there is no fuzzy, semantic or parent-label matching.

The formal evaluation is a one-shot comparison of frozen predictions. A separate standalone calculation cross-checked every metric, support, count and confusion matrix before formal results were written. The deterministic evaluation identity binds dataset, GT, split, predictions, rubric, normalization, evaluator source and protocol digests; timestamps are excluded. Both a full-corpus prediction identity and the evaluated 32-paper subset identity are recorded. Aggregate findings and limits are in [EVALUATION_RESULTS.md](EVALUATION_RESULTS.md).

**No heldout tuning:** after this evaluation, do not use Evaluation Dataset v1 IDs 9–40 to change the classifier prompt, model settings, normalization, taxonomy or Ground Truth, or to regenerate predictions. Future improvements must use development IDs 1–8 or a new development corpus and a new independent test set. Descriptive error analysis does not authorize adjustments in this task.
