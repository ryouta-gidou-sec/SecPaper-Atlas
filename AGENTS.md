# Repository guidance

- Treat every file in `papers/inbox/` as immutable user data. Never rename, move, edit, or delete it.
- Never commit PDFs, `.env`, SQLite databases, logs, or other personal research data.
- Keep OpenAI inputs limited to extracted title, abstract, keywords, and (only when the abstract is missing) a short introduction excerpt.
- Preserve original AI outputs separately from user-reviewed values.
- Use parameterized SQLite queries and validate values at trust boundaries.
- Run `pytest` after behavioral changes and update architecture documentation when storage or data flow changes.
- Keep v0.1 focused on classification and library browsing; do not add translation, semantic search, recommendations, citation graphs, or automated PDF downloads.
