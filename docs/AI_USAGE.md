# AI Usage and Development Transparency

## Purpose

This project uses AI in two roles: Codex as a development assistant, and local Ollama (default) or an explicitly selected OpenAI API as the runtime classifier. AI use is disclosed because responsible engineering depends on knowing where probabilistic systems influenced the product.

## Codex in development

Codex was used to assist with repository inspection, implementation, tests, documentation, and consistency checks. That assistance does not replace ownership of the project. Requirements, scope, privacy boundaries, category definitions, acceptance criteria, and final review remain human responsibilities.

AI-assisted code is treated like code from any other untrusted draft source:

1. Read it in context.
2. Check that it matches the stated requirement.
3. Exercise trust boundaries and failure paths with automated tests.
4. Run the complete test suite.
5. Manually review security-sensitive behavior, especially file handling, secrets, external requests, and SQL.

## Local and optional OpenAI classification

Local classification uses loopback Ollama and an installed local model. Cloud references and remote endpoints are rejected, and there is no fallback to OpenAI. Run the Ollama server with `OLLAMA_NO_CLOUD=1`. Only selecting OpenAI discloses minimal paper input externally. Model installation/download is explicit and separate from classification.

The runtime classifier receives a deliberately limited input: title, abstract, keywords, and only when the abstract is missing, a short introduction excerpt. It does not receive the source PDF or the full extracted document.

The requested output is constrained by a Pydantic schema:

- exactly one allowed primary category;
- lists of tags, research methods, and target vulnerabilities;
- relevance A, B, or C;
- a short relevance reason;
- confidence between 0 and 1.

Structured output and schema validation reduce format errors. They do not make the semantic judgment automatically correct.

## Human authority

AI output is a proposal, not ground truth. Users can correct category, tags, methods, vulnerabilities, relevance, reason and reading status. The database retains original predictions in classification_runs, a latest ai_* projection, and separate human current values. Only an explicit review save sets manually_reviewed. Before review, AI is a display/filter fallback and current values remain empty. Retries retain prior AI originals and human values.

Humans should decide:

- whether extracted metadata actually belongs to the paper;
- whether a paper's central contribution fits the chosen primary category;
- whether tags and vulnerabilities are specific enough;
- whether relevance reflects the current research question;
- whether evidence is strong enough to cite or rely on;
- whether a paper and any sensitive notes may be shared.

## Ground truth and evaluation

Human Review is an application workflow for correcting a paper's current values. Evaluation Ground Truth is a separate human reference, assigned using a fixed rubric and evidence scope before comparing it with AI predictions. Saving a review does not automatically establish independent Ground Truth, and AI values must never be copied into reference labels without human judgment.

The public `data/ground_truth.csv` contains column headers only. Real reference labels and evaluation working files stay in ignored local storage. The CSV evaluation command reads explicitly prepared category labels; the database comparison command uses explicitly saved Human Review categories, whose independence must be assessed separately.

The v0.1.1 results are an eight-paper pilot covering three categories. Prompt adjustments used those same papers, so the later comparison is a development-set comparison. Tags, methods and relevance remain problematic; confidence is a model self-report, not a calibrated probability. See [EVALUATION.md](EVALUATION.md), [EVALUATION_RUBRIC.md](EVALUATION_RUBRIC.md) and [EVALUATION_RESULTS.md](EVALUATION_RESULTS.md).

## What AI does not do in v0.1

AI does not translate full papers, generate research gaps, recommend papers, make academic-quality judgments, edit PDFs, browse paper websites, download files, or move files. It also does not override human-reviewed values.

## Verification policy

The repository includes unit and integration-style tests for schema rejection, mocked provider errors, metadata fallbacks, duplicate prevention, normalized database search, preservation of AI values, and continuation after a per-paper failure. Manual checks should additionally cover the Streamlit workflow with representative text PDFs, a malformed PDF, an image-only PDF, a missing API key, and a deliberately corrected classification.

This approach demonstrates the intended engineering stance: use AI productively while keeping requirements, validation, security decisions, evaluation, and accountability human-led.
