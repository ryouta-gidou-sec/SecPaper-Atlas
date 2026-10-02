# Evaluation Plan

## Goal

Evaluation asks whether the classifier is useful for the current literature-review task. It does not score paper quality. Version 0.1 provides a reproducible baseline for primary-category classification and records fields needed for later extraction and latency measurements.

## Ground-truth workflow

Use `data/ground_truth.csv` with these columns:

| Column | Meaning |
|---|---|
| `file_hash` | Stable SHA-256 identity; do not use a private filepath as the identifier |
| `title` | Human-readable reference for review |
| `ground_truth_category` | Category assigned by a human after reading enough of the paper |
| `ai_primary_category` | Original, unedited AI category |
| `reviewer_notes` | Optional short explanation for ambiguous decisions |

The checked-in CSV is intentionally empty. For real evaluation, populate a local copy from manually reviewed papers. Do not publish titles or hashes when the underlying paper collection or research activity is private.

Recommended procedure:

1. Define the category rubric before inspecting model output.
2. Sample across categories, years, venues, and easy/ambiguous cases rather than choosing only obvious papers.
3. Have the reviewer assign ground truth without looking at `ai_primary_category` when possible.
4. Preserve the original AI value, not the user-corrected current value.
5. Document disagreements and refine the rubric separately from the test set.

For a portfolio demonstration, report sample size and class distribution next to every metric. Accuracy from a small or strongly imbalanced set should be labeled preliminary.

## Baseline command

```powershell
python scripts/evaluate.py data/ground_truth.csv
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
python scripts/evaluate.py --database data/papers.db
```

This reads SQLite in read-only mode and reuses the category Accuracy/Precision/Recall/F1 calculation. It joins successful classification_runs to explicitly reviewed current category labels, groups by provider/model and takes the latest success per PDF hash within each group. Retries do not inflate sample size; failed and unreviewed records are excluded. Historical runs with unknown provenance appear under unknown rather than being guessed to be OpenAI.

Changing the provider/model does not automatically resubmit classified papers. Intentional comparison scans use `scan_inbox(..., reclassify=True)` and retain original history and Human Review values. Record the model, rubric and sample size with results. Groups may cover different papers; use a matched cohort when making a direct model comparison. Reviewing AI proposals can bias the reference labels; independently assigned ground truth remains preferable.

This command currently evaluates primary category. Tags, methods, vulnerabilities and relevance remain stored for later metric extensions.

## Metric definitions

For category `c`:

- **Precision:** of papers predicted as `c`, the fraction whose ground truth is `c`.
- **Recall:** of papers whose ground truth is `c`, the fraction predicted as `c`.
- **F1:** harmonic mean of precision and recall.
- **Accuracy:** fraction of all evaluated papers with an exact primary-category match.

Macro-F1 and a confusion matrix are useful next additions once the set is large enough. Multi-label tags, methods, and vulnerabilities should eventually use micro/macro precision, recall, and F1 with an explicit label-normalization policy.

## Metadata extraction evaluation

Create a separate reviewed table for title, authors, year, venue, abstract, and keywords. For each field record whether it is:

- exact;
- acceptable after normalization;
- missing when present in the document;
- incorrectly extracted;
- not available in the source.

Report success rate per field. Do not count a genuinely unavailable value as an extraction failure. Image-only PDFs should be reported separately because v0.1 has no OCR.

## Processing-time evaluation

`papers.processing_seconds` records wall-clock processing time for successfully inserted papers. Future reporting should separate local parsing time from API latency and include median, p90, model name, page-count distribution, and machine/network context. Average alone is vulnerable to rate-limit and network outliers.

## Threats to validity

- One reviewer can encode subjective category preferences.
- Categories overlap even though primary category is single-label.
- A collection focused on session security may hide weak performance on other categories.
- Changing prompts or models after seeing test results can overfit the evaluation set.
- Metadata extraction quality varies significantly by publisher layout and scanned versus text PDFs.

Use a frozen holdout set for any serious comparison between prompts or models, version the rubric, and report uncertain cases instead of forcing false precision.
