# Architecture

## Design goals

Version 0.1.1 is a local, inspectable classification pipeline. It prioritizes source-PDF integrity, deterministic duplicate handling, minimal data disclosure, recoverable AI failures, and explicit human authority over classifications.

## Components

| Component | Responsibility | Trust boundary |
|---|---|---|
| `src/config.py` | Resolve application-owned paths and environment settings; configure rotating logs | Reads secrets from local environment only |
| `src/pdf_parser.py` | Discover contained files, check signatures, hash content, extract bounded text and first-two-page block geometry/direction | Parses untrusted PDFs locally, read-only |
| `src/pdf_access.py` | Locate a registered PDF by filename/hash, validate it, and open a file URI in the default browser | Contained local source files only; no serving or PDF writes |
| `src/metadata_extractor.py` | Recover conservative bibliographic fields, provenance, and review reasons | Treats extracted text as untrusted data |
| `src/classifier.py` | Common protocol, minimal input/prompt/schema, validation, factory and optional OpenAI provider | External paper disclosure only when OpenAI is selected |
| `src/ollama_classifier.py` | Local model preflight and JSON Schema requests with bounded retry | Loopback only; no cloud inference or model download |
| `src/database.py` | Own schema, transactions, bound SQL, search, and human-review updates | Persists private local research data |
| `src/scanner.py` | Orchestrate stages and isolate failures per paper | Does not mutate input files |
| `src/i18n.py` | Translate UI text and enum display labels into Japanese, English, or Korean | Presentation only; never translates paper text or stored values |
| `app.py` | Present dashboard, filters, detail, scan controls, and review form | User-facing local interface |
| `scripts/evaluate.py` | Compare human labels with AI primary-category output and report accuracy / per-category metrics | Reads an explicitly prepared local CSV or successful run history and Human Review categories from SQLite in read-only mode |

## Data flow

```mermaid
sequenceDiagram
    actor User
    participant UI as Streamlit
    participant Scan as Scanner
    participant PDF as PDF parser
    participant Meta as Metadata extractor
    participant AI as Selected classifier (local default / OpenAI opt-in)
    participant DB as SQLite

    User->>UI: Scan papers/inbox
    UI->>Scan: Start scan
    Scan->>PDF: Discover + SHA-256
    Scan->>DB: Check file_hash
    alt new hash or unclassified record
        Scan->>PDF: Parse read-only
        PDF->>Meta: Text + PDF properties
        Meta->>Scan: Fields + sources + quality issues
        alt input passes quality gate
            Scan->>AI: Title + abstract + keywords
            opt no abstract
                Scan->>AI: Short introduction excerpt
            end
            AI-->>Scan: Validated classification or safe error
        else needs review
            Scan-->>UI: Hold before API disclosure
        end
        Scan->>DB: Transactional insert
    else already classified hash
        Scan-->>UI: Skipped
    end
    DB-->>UI: Effective values (AI fallback or reviewed current) + preserved AI values
    User->>UI: Save manual review
    UI->>DB: Update current values only
```

The parser may inspect up to 12 pages locally to find front matter, abstract, keywords, and an introduction excerpt. Only the first two pages retain block geometry, maximum span font sizes, and line directions. Mixed orientations are separated into distinct blocks; each retained block is bounded to 6,000 characters. These layouts are transient and do not change the database schema. The entire extracted text is never passed to the classifier. Abstracts are capped at 6,000 characters; introduction excerpts are used only when an abstract is absent and are capped at 2,500 characters. PDF creation and modification dates are not considered publication years.

Title extraction retains the existing top-quarter first-page layout and PDF-property
priority, excluding rotated/vertical margin text, arXiv identifier labels,
proceedings headers, association branding, and clear internal document names
(workflow suffixes or document extensions). A valid PDF title remains the fallback
after usable layout candidates. If both fail, a proceedings-cover fallback requires the explicit
"This paper is included in the Proceedings of" text plus a USENIX conference URL
or Security Symposium label. Only then may it search the top half of the first
page and join overlapping, adjacent title lines. Its provenance is `first page
cover layout`. If a proceedings cover still has no usable title, the second page
must contain a usable title and an abstract/section heading before its layout is
accepted, with `second page layout` provenance. This also aligns abstract and author
extraction with the article page; publication year and venue still use the first page.
Cover title geometry is not used to infer authors from mixed
name/affiliation rows; existing PDF author properties retain their priority.

Abstract labels accept case variations and explicit delimiters. A standalone
`Summary` label or a delimited `Summary:`/`Summary—` label is also eligible before
body section headings; subsection names such as "Summary of the Recovery Phase"
are excluded. Adjacent blocks in the same column are joined to retain multiple
abstract paragraphs; centered section headings also stop that column. Paragraph
breaks do not end an abstract. Keywords, numbered sections, content warnings,
ACM classification fields, copyright/license notices, footnotes, and contact fields
are explicit boundaries. Unlabeled summaries require title geometry and prose before
the first section. When that section is on a later page, the first page must also
contain an author/affiliation region; contiguous summary paragraphs stop before
footnotes and the page footer. Introduction
fallback first retains the first-page routes, then searches the parser's bounded
text if necessary. It accepts standalone, Arabic-numbered (including split-line
numbers), and Roman-numbered headings, skips split table-of-contents entries
followed by page numbers, and stops at the next numbered section or an explicit
References/Bibliography/Acknowledgments heading. Later-page provenance is `bounded
PDF text fallback`. Contact, affiliation, footnote, copyright and margin-label
noise ends an introduction excerpt conservatively.

Keywords use explicit front-matter labels and their column layout, support wrapped
lines (including line-end hyphenation) and comma/semicolon/middle-dot separators,
and stop at the next field or section. Bounded-text keyword matches after body
sections are rejected, preventing response templates from being mistaken for
metadata. Valid explicit PDF `/Keywords` properties are a final fallback; missing
keywords are never inferred. Provenance remains field-specific.

The shared quality gate also rejects clear arXiv/internal/proceedings false titles.
A supplied unusable abstract cannot be rescued by an introduction that the provider
would not send. These are narrow input checks, not a guarantee of complete metadata
quality: missing authors/year, incomplete prose and plausible but incorrect values
still require audit. Classifier payload fields, prompts, provider/model settings,
and storage schema remain unchanged; extraction alone does not change persisted
metadata or classification status.

## Database design

SQLite foreign keys are enabled for every connection. One insert and its label associations share a transaction.

### `papers`

The central table stores identity, bibliographic metadata, workflow state, processing diagnostics, and scalar classification fields. `file_hash` is a unique 64-character SHA-256 hex digest. Metadata lists that are not filter dimensions in v0.1 (`authors`, `keywords`, and extraction review reasons) are stored as JSON arrays. `metadata_sources` is a JSON object because it is sparse provenance metadata rather than a search dimension. `introduction_excerpt` is retained so a pending classification can be retried without relying on a stale in-memory parse.

Scalar AI/current pairs preserve provenance:

- `ai_primary_category` and `primary_category`
- `ai_relevance` and `relevance`
- `ai_relevance_reason` and `relevance_reason`
- `ai_relevance_confidence` and `relevance_confidence`

`manually_reviewed` distinguishes untouched AI output from a review. Before the first explicit review, current scalar fields and current label rows remain empty; classification writes only `ai_*` fields and `value_source='ai'` rows. Read and search results expose effective values without persisting a copy: AI values are the display/filter fallback while `manually_reviewed=0`, and current values take over after a review save. AI retries update only AI-owned values and never overwrite current values. Initialization adds missing workflow columns and clears the old AI-to-current projection only for unreviewed rows; reviewed rows and all AI originals are preserved. `classification_status` records `pending`, `classified`, `failed`, or `needs_review`; pending and failed records can be retried when scanning the inbox again. A needs-review record is re-extracted and is only sent when its input passes the quality gate. `classification_error` allows extraction results to survive an API or validation failure.

### Processing duration

`papers.processing_seconds` is the wall-clock duration in seconds of the latest
non-skipped scanner attempt, measured with `time.perf_counter()`. Measurement starts
before hashing and the duplicate lookup and ends after parsing, metadata extraction,
the input quality gate, and any classifier preflight, generation and Pydantic
validation (including bounded validation retries). It excludes the subsequent
database writes, result logging and UI rendering. It is not classification-only
latency; no separate extraction/classification duration columns are introduced.

New inserts and existing-record retries use the same boundary. Successful, failed,
pending and review-held attempts save their current measured duration; skipped
classified hashes leave the previous duration and history unchanged. Duration and
the classification result/history append share the classification-write transaction.
The storage API accepts only finite non-negative durations. An omitted/None duration
on a direct `update_classification()` call preserves the existing value, while zero
is a valid measured value. No schema change or migration is required.

`classification_runs` continues to preserve original validated answers and failures;
it does not store per-run latency. `processing_seconds` describes the latest scan
attempt, which may have failed while the latest successful AI projection is retained.
Historical timings are not inferred or backfilled.

### Searchable many-to-many values

```text
papers 1---* paper_tags *---1 tags
papers 1---* paper_methods *---1 research_methods
papers 1---* paper_vulnerabilities *---1 vulnerabilities
```

Each junction row includes `value_source`, either `ai` or `current`. Initial classification creates only AI rows. Review creates or replaces current rows. Search, facets, and the dashboard select AI rows for unreviewed papers and current rows for reviewed papers. This avoids opaque JSON filtering and supports future AI-versus-human evaluation without destroying history.

### Query behavior

All user values are bound parameters. Dynamic table and column identifiers are selected only from an internal constant mapping. Keyword search covers title, abstract, effective tags, and effective vulnerabilities. Category, tag, method, vulnerability, and relevance filters plus dashboard counts use AI values until a human review exists, then use current reviewed values. The Human correction form starts empty for unreviewed papers; saving it is the only operation that creates current values and sets `manually_reviewed=1`. Filters use “match any selected value” semantics.

## UI language boundary

The compact language selector is the first sidebar control. Japanese is the initial
default; `ui_language` lives only in Streamlit session state and survives reruns.
`src/i18n.py` resolves UI text with English, then the key itself, as fallbacks.
PrimaryCategory, PaperStatus, and ClassificationStatus have display aliases;
unmapped labels retain their original text. Selectbox and multiselect options stay
canonical and use `format_func` for translated display. Stable widget keys preserve
filters, selected paper IDs, and review state when the language changes. Search and
review persistence receive canonical/original values, never translated enum labels.
On a language change, the UI re-publishes the existing enum widget values through
session state so the browser refreshes selected display labels as well as options.

Table and chart labels are translated at rendering time. Extracted titles, authors,
abstracts, keywords, free-form tags/methods/vulnerabilities, reasons, provider/model
identifiers, and original history/provenance JSON remain unchanged. Known fixed
scan/review messages are translated; unmatched diagnostics are shown verbatim.
Language selection makes no classifier call or database write. Schema, taxonomy,
prompts, AI/Human Review separation, Ground Truth, and evaluation are unchanged.
The existing CSS, five metric columns, and 2:1 detail/review columns are retained.

## Classification provider boundary

`ClassifierProvider` exposes provider, model, `classify(...) -> ClassificationResult` and `close()`. Scanner orchestration does not import provider clients. The factory defaults to local; OpenAI must be selected explicitly. `PaperClassifier` remains an alias of `OpenAIClassifier` for existing callers and mocks. Input gate, minimal payload, prompt, schema and output validation are shared. The local model name is configurable with no default in code.

The request includes only:

- title, capped at 500 characters;
- abstract, capped at 6,000 characters;
- at most 30 keywords;
- a 2,500-character introduction excerpt only if no abstract exists.

Before a request, title must look usable and either an abstract of at least 80 characters or a bounded introduction excerpt of at least 120 characters must exist. Extraction review reasons and obvious diagram/noise text hold the item at `needs_review`; missing keywords alone do not. The OpenAI Python SDK's schema helper receives `ClassificationResult`, a Pydantic model with forbidden extra fields, enum-constrained primary category and relevance, bounded list sizes, a bounded explanation, and confidence between 0 and 1. The response is validated again before persistence. Provider exceptions are converted to an error containing only the exception type.

Ollama `/api/chat` receives the same JSON Schema in `format`, with all fields required, `stream=false`, `think=false`, temperature 0, context 8192 tokens and output cap 1024 tokens. JSON is parsed and strictly validated with Pydantic; no fence removal, enum guessing, default filling or numeric-string coercion is performed. Only output validation failures permit 0 or 1 regeneration. Transport, HTTP and model errors are not retried. The default local timeout is 180 seconds (configurable up to 600); OpenAI transport retries are disabled with a 60-second timeout.

### Local privacy

**Local Providerでは論文情報がPC外へ送信されない。** Only HTTP loopback addresses are accepted; localhost is normalized to a literal address. URL credentials, paths, queries and fragments are rejected. The HTTP client ignores proxy settings and does not follow redirects. Cloud model references and `/api/show` responses with remote_host/remote_model are rejected before paper submission; installed local model metadata must be present. The app performs no downloads, external fallback or tool invocation.

Run the trusted local Ollama server with `OLLAMA_NO_CLOUD=1` and restart it after changes. An app `.env` entry alone does not configure an already running server. Installation, model downloads and software updates can use the network separately; paper classification stays local.

### Additive provenance migration

Nullable papers columns `classification_provider` (local/openai), `classification_model`, and `classified_at` describe the latest successful ai_* projection. A failed retry changes workflow state without attributing an older success to the failing provider.

New `classification_runs` rows retain provider/model, validated result JSON or sanitized failure, UTC classification time for successes, and creation time. Run insertion, latest AI update and labels share a transaction. Retries replace the latest AI projection but retain all previous originals in history; Human Review never edits that history or gets overwritten by retries. Existing AI rows are snapshotted once, with unknown historical provider/model/date left null. Old failures keep their diagnostics without invented provenance. Migration is idempotent.

Normal scans skip classified hashes regardless of provider changes. Explicit `reclassify=True` enables deliberate comparison runs. Evaluation reads successful history and current human labels read-only, groups by provider/model, and uses the latest success per hash per group. The original CSV metrics remain available. Human Review categories are not automatically independent Ground Truth; evaluation references require a fixed rubric and separate human judgment. The multi-field v0.1.1 pilot in [EVALUATION_RESULTS.md](EVALUATION_RESULTS.md) used local helper scripts; the public CLI evaluates primary category only.

## PDF processing and source integrity

1. Resolve the candidate and inbox paths.
2. Reject paths that do not remain under the inbox after resolution.
3. Require a case-insensitive `.pdf` suffix and `%PDF-` magic bytes.
4. Stream the file through SHA-256.
5. Skip hashes already classified in SQLite; retry pending, failed, and review-held rows.
6. Open with PyMuPDF in read-only mode and reject password-protected or malformed files.
7. Extract bounded text and first-two-page layout/direction in memory. Never save changes to the document.

PDF filename changes produce the same hash and remain duplicates. Two byte-identical PDFs in different folders also map to one record.

### PDF quick access

Paper Detail places a localized "Open PDF in default browser" button just below
Authors/Year/Venue. On a
click, `src/pdf_access.py` first tries `settings.inbox_dir / filename`. Because
the scanner stores a basename even for nested PDFs, it falls back to recursively
matching basenames under the current inbox. Each candidate must match the existing
`file_hash` (SHA-256), so duplicate basenames cannot select another paper. The
stored absolute `filepath` is neither used nor changed; moving the project with
its inbox does not invalidate this lookup. A renamed or changed source fails
safely until its registered identity can be found again.

Filename/hash values are validated at the boundary. Candidates must exist as
regular files, have a case-insensitive `.pdf` suffix and `%PDF-` signature, and
remain inside the resolved inbox, including after symlink/junction resolution.
Containment is checked before reading or hashing a candidate. The matching,
resolved path is converted with `Path.as_uri()` and passed once to
`webbrowser.open_new_tab()`. A false return or exception produces a fixed,
localized warning without absolute paths or underlying exception text. The UI
no longer displays the stored local absolute path.

This opens the source PDF in the local environment's default browser without
requesting a particular browser. It is a local-only convenience for Streamlit,
the default browser, and PDFs on the same PC. `webbrowser` acts on the server's
PC; remote/cloud deployment cannot use it to open the client's browser. The
browser/OS controls the final PDF handler and whether it uses a tab or window;
the UI does not promise a new tab. A true return confirms dispatch rather than
PDF rendering.
No HTTP file server, upload, download, schema change, classification call, or
review/history write is part of this action.

## Error handling

The scan loop has a paper-level exception boundary. A broken PDF, extraction exception, API error, refusal, rate limit, response validation error, or SQLite failure becomes a result row and the next PDF continues. A classification failure is non-fatal: metadata is stored with null classification fields and a safe diagnostic. A parse failure is not inserted because there is no trustworthy PDF record to present.

Rotating logs are local and ignored by Git. They deliberately omit API keys, prompts, abstracts, and document text. UI messages likewise expose sanitized exception classes rather than provider payloads.

## Security design

- Secrets enter through environment variables loaded from an ignored `.env` file.
- PDF input is data, never executable content.
- Source files have no write, move, rename, or delete code path.
- Path containment is checked after resolution to address traversal and symlink escape.
- File type is checked at multiple layers: extension, magic bytes, and parser acceptance.
- SQL uses parameters and foreign keys; the hash also has a database uniqueness constraint.
- External disclosure is minimized and bounded.
- Runtime data is ignored by Git, with `.gitkeep` files retaining empty directory structure.

## Deliberate v0.1 constraints

The design excludes OCR, background jobs, full-text translation, vector databases, semantic search, recommendations, citation graphs, automatic downloads, automatic file movement, and PDF editing. Adding these prematurely would expand the attack surface and obscure the core classification evaluation.
