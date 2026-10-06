from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from src.database import Database
from src.models import ClassificationResult, ExtractedMetadata
from src.config import get_settings
from src.i18n import display_enum, t
from src.pdf_access import BROWSER_FAILED, PDF_UNAVAILABLE
from src.pdf_parser import sha256_file


@pytest.mark.parametrize("language", ["ja", "en", "ko"])
def test_sidebar_order_and_existing_widget_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str,
) -> None:
    settings = get_settings(tmp_path)
    database = Database(settings.database_path)
    database.initialize()
    for index, year in enumerate((2023, 2025)):
        database.add_paper(
            file_hash=str(index) * 64, filename=f"fixture-{index}.pdf",
            filepath=f"fixture-{index}.pdf",
            metadata=ExtractedMetadata(title=f"Sidebar fixture {index}", year=year),
            classification=None,
        )
    monkeypatch.setattr("src.config.get_settings", lambda: settings)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
    app.session_state["ui_language"] = language
    app.session_state["scan_results"] = [
        {"filename": "existing.pdf", "status": "Skipped", "message": "Already registered"},
    ]
    app.run(timeout=15)
    assert not app.exception
    sidebar = list(app.sidebar)
    # AppTest iteration includes the container itself before its rendered elements.
    assert sidebar[1].key == "ui_language"
    assert app.sidebar.selectbox[0].options == ["日本語", "English", "한국어"]
    assert [item.value for item in app.sidebar.header] == [
        t("Library", language), t("Search & filters", language), t("Classifier", language),
    ]
    assert app.sidebar.button(key="scan_inbox").label == t("Scan papers/inbox", language)
    assert app.sidebar.expander[0].label == t("Last scan results", language)
    assert {item.key for item in app.sidebar.multiselect} == {
        "filter_categories", "filter_tags", "filter_methods", "filter_vulnerabilities",
        "filter_relevances", "filter_statuses", "filter_classification_statuses",
    }
    assert app.sidebar.text_input[0].key == "filter_keyword"
    assert app.sidebar.slider[0].key == "filter_years"
    assert sidebar.index(app.sidebar.slider[0]) < sidebar.index(app.sidebar.header[-1])
    captions = [item.value for item in app.sidebar.caption]
    assert captions[-3:] == [
        f"{t('Provider', language)}: {settings.classifier_provider}",
        f"{t('Model', language)}: {settings.classifier_model or t('Not configured', language)}",
        t("Local processing on this PC" if settings.classifier_provider == "local"
          else "Extracted classification input is sent to OpenAI", language),
    ]


@pytest.mark.parametrize("language", ["ja", "en", "ko"])
@pytest.mark.parametrize("counts", [(), (1,), (1, 3)])
def test_category_chart_has_nonnegative_integer_counts_and_zero_based_axis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str, counts: tuple[int, ...],
) -> None:
    database = Database(tmp_path / "category-chart.db")
    database.initialize()
    labels = ("Session Management", "Authentication")
    index = 0
    for label, count in zip(labels, counts):
        for _ in range(count):
            database.add_paper(
                file_hash=f"{index:064x}", filename=f"fixture-{index}.pdf",
                filepath=f"fixture-{index}.pdf",
                metadata=ExtractedMetadata(title=f"Chart fixture {index}"),
                classification=ClassificationResult(
                    primary_category=label, tags=[], research_methods=[],
                    target_vulnerabilities=[], relevance="A", relevance_reason="Chart fixture.",
                    relevance_confidence=0.9,
                ),
            )
            index += 1
    monkeypatch.setenv("DATABASE_PATH", str(database.path))
    expected = database.dashboard_counts()["categories"]
    assert expected == dict(zip(labels, counts))
    assert all(isinstance(count, int) and count >= 0 for count in expected.values())
    charts = []
    render_chart = st.altair_chart

    def capture_chart(chart, **kwargs):
        charts.append(chart.to_dict())
        return render_chart(chart, **kwargs)

    monkeypatch.setattr(st, "altair_chart", capture_chart)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
    app.session_state["ui_language"] = language
    app.run(timeout=15)
    assert not app.exception
    if not counts:
        assert not charts
        assert any(item.value == t(
            "Add PDFs to papers/inbox and run a scan to build the dashboard.", language,
        ) for item in app.info)
        return
    assert len(charts) == 1
    spec = charts[0]
    assert spec["mark"]["type"] == "bar"
    x, y = spec["encoding"]["x"], spec["encoding"]["y"]
    assert x["field"] == t("Papers", language)
    assert x["type"] == "quantitative"
    assert x["scale"]["domainMin"] == 0
    assert x["scale"]["zero"] is True
    assert x["axis"]["format"] == "d"
    assert x["axis"]["tickMinStep"] == 1
    assert y["field"] == t("Category", language)
    assert y["type"] == "nominal"
    rows = spec["data"]["values"]
    assert rows == [
        {t("Category", language): display_enum(label, language), t("Papers", language): count}
        for label, count in expected.items()
    ]


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


@pytest.mark.parametrize("language", ["ja", "en", "ko"])
@pytest.mark.parametrize("outcome", ["success", "false", "exception", "missing"])
def test_pdf_quick_access_uses_selected_paper_and_preserves_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str, outcome: str,
) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "quick-access.db"))
    settings = get_settings(tmp_path)
    settings.ensure_directories()
    monkeypatch.setattr("src.config.get_settings", lambda: settings)
    database = Database(settings.database_path)
    database.initialize()
    ids = []
    paths = []
    for index in range(2):
        path = settings.inbox_dir / f"source-{index}.pdf"
        path.write_bytes(f"%PDF-1.7\nsource {index}\n".encode())
        paths.append(path)
        ids.append(database.add_paper(
            file_hash=sha256_file(path), filename=path.name, filepath=str(path.resolve()),
            metadata=ExtractedMetadata(title=f"PDF access fixture {index}"), classification=None,
        ))
    opener = Mock(return_value=outcome != "false")
    if outcome == "exception":
        opener.side_effect = OSError(r"C:\Users\private\source.pdf")
    monkeypatch.setattr("src.pdf_access.webbrowser.open_new_tab", opener)
    st.cache_resource.clear()
    try:
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
        app.session_state["ui_language"] = language
        app.run(timeout=15)
        app.selectbox(key="selected_paper_id").set_value(ids[1]).run(timeout=15)
        assert not app.exception
        opener.assert_not_called()
        assert app.button(key="open_paper_pdf").label == "📄 " + t("Open PDF in default browser", language)
        assert not app.code
        columns = app.get("column")
        assert [round(column.proto.weight, 3) for column in columns] == [0.2] * 5 + [0.167, 0.167, 0.667] + [0.667, 0.333]
        assert len(columns[-2].get("button")) == 1
        assert len(columns[-1].get("form")) == 1
        before_db = database.path.read_bytes()
        before_papers = database.search_papers()
        before_history = [database.classification_history(paper_id) for paper_id in ids]
        before_pdfs = [path.read_bytes() for path in paths]
        if outcome == "missing":
            paths[1].unlink()  # Isolated fixture only.
        app.button(key="open_paper_pdf").click().run(timeout=15)
        assert not app.exception
        if outcome == "missing":
            opener.assert_not_called()
            expected_warning = PDF_UNAVAILABLE
        else:
            opener.assert_called_once_with(paths[1].resolve().as_uri())
            expected_warning = BROWSER_FAILED
        if outcome != "success":
            assert any(item.value == t(expected_warning, language) for item in app.warning)
        else:
            assert not app.warning
        assert not any("C:\\" in item.value or str(tmp_path) in item.value for item in app.warning)
        # A later UI rerun must not dispatch the PDF again.
        app.run(timeout=15)
        assert opener.call_count == (0 if outcome == "missing" else 1)
        assert database.path.read_bytes() == before_db
        assert database.search_papers() == before_papers
        assert [database.classification_history(paper_id) for paper_id in ids] == before_history
        assert paths[0].read_bytes() == before_pdfs[0]
        if outcome != "missing":
            assert paths[1].read_bytes() == before_pdfs[1]
    finally:
        st.cache_resource.clear()
