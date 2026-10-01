# AI Usage and Development Transparency

## Purpose

This project uses AI in two separate roles: Codex as a development assistant and the OpenAI API as a runtime paper-classification component. AI use is disclosed because responsible engineering depends on knowing where probabilistic systems influenced the product.

## Codex in development

Codex was used to assist with repository inspection, implementation, tests, documentation, and consistency checks. That assistance does not replace ownership of the project. Requirements, scope, privacy boundaries, category definitions, acceptance criteria, and final review remain human responsibilities.

AI-assisted code is treated like code from any other untrusted draft source:

1. Read it in context.
2. Check that it matches the stated requirement.
3. Exercise trust boundaries and failure paths with automated tests.
4. Run the complete test suite.
5. Manually review security-sensitive behavior, especially file handling, secrets, external requests, and SQL.

## OpenAI API in the application

The runtime classifier receives a deliberately limited input: title, abstract, keywords, and only when the abstract is missing, a short introduction excerpt. It does not receive the source PDF or the full extracted document.

The requested output is constrained by a Pydantic schema:

- exactly one allowed primary category;
- lists of tags, research methods, and target vulnerabilities;
- relevance A, B, or C;
- a short relevance reason;
- confidence between 0 and 1.

Structured output and schema validation reduce format errors. They do not make the semantic judgment automatically correct.

## Human authority

AI output is a proposal, not ground truth. The interface lets a user correct category, tags, methods, vulnerabilities, relevance, its reason, and reading status. The database keeps the original `ai_*` values and separate current values, and sets `manually_reviewed` after a review. That separation supports auditability and later quality measurement.

Humans should decide:

- whether extracted metadata actually belongs to the paper;
- whether a paper's central contribution fits the chosen primary category;
- whether tags and vulnerabilities are specific enough;
- whether relevance reflects the current research question;
- whether evidence is strong enough to cite or rely on;
- whether a paper and any sensitive notes may be shared.

## What AI does not do in v0.1

AI does not translate full papers, generate research gaps, recommend papers, make academic-quality judgments, edit PDFs, browse paper websites, download files, or move files. It also does not override human-reviewed values.

## Verification policy

The repository includes unit and integration-style tests for schema rejection, mocked provider errors, metadata fallbacks, duplicate prevention, normalized database search, preservation of AI values, and continuation after a per-paper failure. Manual checks should additionally cover the Streamlit workflow with representative text PDFs, a malformed PDF, an image-only PDF, a missing API key, and a deliberately corrected classification.

This approach demonstrates the intended engineering stance: use AI productively while keeping requirements, validation, security decisions, evaluation, and accountability human-led.
