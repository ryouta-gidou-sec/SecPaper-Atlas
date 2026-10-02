from __future__ import annotations

from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from src.database import Database
from src.models import ClassificationResult, ExtractedMetadata


def test_library_dashboard_filters_detail_and_human_correction(
    tmp_path: Path, monkeypatch: object
) -> None:
    database_path = tmp_path / "ui-smoke.db"
    database = Database(database_path)
    database.initialize()
    classification = ClassificationResult(
        primary_category="Session Management",
        tags=["Session Fixation"],
        research_methods=["Empirical Study"],
        target_vulnerabilities=["Session Fixation"],
        relevance="A",
        relevance_reason="A test fixture for UI rendering.",
        relevance_confidence=0.9,
    )
    paper_id = database.add_paper(
        file_hash="d" * 64,
        filename="fixture.pdf",
        filepath="fixture.pdf",
        metadata=ExtractedMetadata(
            title="A UI Fixture Paper",
            authors=["Example Author"],
            year=2024,
            venue="Example Venue",
            abstract="A test abstract for exercising the local paper detail and review form. " * 2,
            keywords=["session"],
        ),
        classification=classification,
        classification_provider="local",
        classification_model="ui-test-model",
    )
    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
    app.session_state["ui_language"] = "en"
    app.run(timeout=15)
    assert not app.exception
    assert any(item.value == "SecPaper Atlas" for item in app.title)
    assert app.dataframe[0].value.iloc[0]["Primary Category"] == "Session Management"
    assert app.dataframe[0].value.iloc[0]["Classification source"] == "AI, not reviewed"
    assert app.dataframe[0].value.iloc[0]["AI Provider"] == "local"
    assert app.dataframe[0].value.iloc[0]["AI Model"] == "ui-test-model"
    assert any(item.value.startswith("Provider:") for item in app.caption)
    assert any("AI Provider: local" in item.value for item in app.caption)
    assert {item.label for item in app.multiselect} >= {
        "Primary category",
        "Tags",
        "Research methods",
        "Target vulnerabilities",
        "Relevance",
        "Status",
        "Classification status",
    }
    assert any(item.label == "Keyword" for item in app.text_input)
    assert any(item.label == "Open paper details" for item in app.selectbox)
    assert any(item.label == "Tags (comma-separated; custom tags allowed)" for item in app.text_area)
    assert next(
        item for item in app.selectbox if item.label == "Primary category"
    ).value is None
    assert next(item for item in app.selectbox if item.label == "Relevance").value is None
    assert next(
        item for item in app.text_area
        if item.label == "Tags (comma-separated; custom tags allowed)"
    ).value == ""

    category_filter = next(item for item in app.multiselect if item.label == "Primary category")
    category_filter.set_value(["Session Management"])
    next(item for item in app.multiselect if item.label == "Tags").set_value(["Session Fixation"])
    next(item for item in app.multiselect if item.label == "Research methods").set_value(
        ["Empirical Study"]
    )
    next(item for item in app.multiselect if item.label == "Target vulnerabilities").set_value(
        ["Session Fixation"]
    )
    next(item for item in app.multiselect if item.label == "Relevance").set_value(["A"])
    next(item for item in app.multiselect if item.label == "Status").set_value(["Unread"])
    next(item for item in app.multiselect if item.label == "Classification status").set_value(
        ["classified"]
    )
    app.run(timeout=15)
    assert not app.exception
    assert app.dataframe

    next(item for item in app.text_input if item.label == "Keyword").set_value("no matching paper")
    app.run(timeout=15)
    assert not app.exception
    assert any("No papers match" in item.value for item in app.info)
    next(item for item in app.text_input if item.label == "Keyword").set_value("")
    for filter_label in (
        "Primary category",
        "Tags",
        "Research methods",
        "Target vulnerabilities",
        "Relevance",
        "Status",
        "Classification status",
    ):
        next(item for item in app.multiselect if item.label == filter_label).set_value([])
    app.run(timeout=15)

    next(item for item in app.selectbox if item.label == "Primary category").set_value("Authorization")
    next(item for item in app.selectbox if item.label == "Relevance").set_value("B")
    next(
        item
        for item in app.text_area
        if item.label == "Tags (comma-separated; custom tags allowed)"
    ).set_value("Human reviewed tag")
    next(item for item in app.button if item.label == "Save review").click()
    app.run(timeout=15)

    reviewed = database.get_paper(paper_id)
    assert reviewed["primary_category"] == "Authorization"
    assert reviewed["ai_primary_category"] == "Session Management"
    assert reviewed["tags"] == ["Human reviewed tag"]
    assert reviewed["ai_tags"] == ["Session Fixation"]


def test_unreviewed_ai_values_are_visible_but_not_saved_as_current(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "unreviewed.db")
    database.initialize()
    classification = ClassificationResult(
        primary_category="Session Management",
        tags=["Session Fixation"],
        research_methods=["Empirical Study"],
        target_vulnerabilities=["Session Fixation"],
        relevance="A",
        relevance_reason="AI-only proposal.",
        relevance_confidence=0.9,
    )
    paper_id = database.add_paper(
        file_hash="e" * 64,
        filename="unreviewed.pdf",
        filepath="unreviewed.pdf",
        metadata=ExtractedMetadata(title="An Unreviewed Paper", year=2024),
        classification=classification,
    )

    paper = database.get_paper(paper_id)
    assert paper["manually_reviewed"] is False
    assert paper["primary_category"] is None
    assert paper["relevance"] is None
    assert paper["tags"] == []
    assert paper["research_methods"] == []
    assert paper["target_vulnerabilities"] == []
    assert paper["effective_primary_category"] == "Session Management"
    assert paper["effective_tags"] == ["Session Fixation"]
    assert database.search_papers(categories=["Session Management"])[0]["id"] == paper_id
    assert database.search_papers(tags=["Session Fixation"])[0]["id"] == paper_id
    assert database.search_papers(methods=["Empirical Study"])[0]["id"] == paper_id
    assert database.search_papers(vulnerabilities=["Session Fixation"])[0]["id"] == paper_id
    assert database.search_papers(relevances=["A"])[0]["id"] == paper_id
    assert database.list_facets()["tags"] == ["Session Fixation"]


def test_full_year_range_keeps_papers_with_unknown_year_visible(
    tmp_path: Path, monkeypatch: object
) -> None:
    database_path = tmp_path / "unknown-year.db"
    database = Database(database_path)
    database.initialize()
    for file_hash, filename, year in (
        ("f" * 64, "known-old.pdf", 2013),
        ("g" * 64, "known-new.pdf", 2024),
        ("h" * 64, "unknown-year.pdf", None),
    ):
        database.add_paper(
            file_hash=file_hash,
            filename=filename,
            filepath=filename,
            metadata=ExtractedMetadata(title=f"A Test Paper About {filename}", year=year),
            classification=None,
        )
    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    st.cache_resource.clear()

    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
    app.session_state["ui_language"] = "en"
    app.run(timeout=15)
    assert not app.exception
    assert len(app.dataframe[0].value) == 3
    year_slider = next(item for item in app.slider if item.label == "Publication year")
    year_slider.set_value((2013, 2013))
    app.run(timeout=15)
    assert not app.exception
    assert len(app.dataframe[0].value) == 1
    assert app.dataframe[0].value.iloc[0]["Title"] == "A Test Paper About known-old.pdf"
