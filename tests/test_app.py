from __future__ import annotations

from pathlib import Path

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
    )
    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run(timeout=15)
    assert not app.exception
    assert any(item.value == "Research Paper Classifier" for item in app.title)
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
