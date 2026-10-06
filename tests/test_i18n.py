from __future__ import annotations

import ast
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from src.database import Database
from src.i18n import (
    ENUM_TRANSLATIONS, LANGUAGES, TRANSLATIONS, canonical_from_display, display_enum, t,
)
from src.models import (
    ClassificationResult, ClassificationStatus, ExtractedMetadata, PaperStatus,
    PrimaryCategory, Relevance, enum_values,
)


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"
REQUIRED_KEYS = {
    "header_caption", "footer_caption", "Classifier", "Provider", "Model", "Library",
    "Scan papers/inbox", "Last scan results", "Search & filters", "Keyword",
    "Primary category", "Tags", "Research methods", "Target vulnerabilities", "Relevance",
    "Status", "Classification status", "Publication year", "Papers", "Relevance A",
    "Relevance B", "Relevance C", "Unread", "Category overview", "Category", "ID", "Title",
    "Year", "Primary Category", "Classification source", "Classification", "AI Provider",
    "AI Model", "Research Methods", "Human reviewed", "AI, not reviewed", "No AI result",
    "Unclassified", "Open paper details", "Authors", "Venue", "Abstract", "Keywords",
    "AI classification history", "Extraction sources", "Human correction", "Save review",
    "Unknown", "Unavailable", "None", "None extracted", "Classified", "Skipped", "Failed",
    "Classification — Human reviewed", "Classification — AI proposal, not reviewed",
    "Classification — unavailable", "Local processing on this PC",
    "Extracted classification input is sent to OpenAI",
    "Open PDF in default browser", "PDF could not be safely located in the inbox.",
    "Unable to open PDF. Check your default browser.",
}


def test_supported_languages_and_complete_ui_dictionary() -> None:
    assert LANGUAGES == {"ja": "日本語", "en": "English", "ko": "한국어"}
    assert set(TRANSLATIONS) == set(LANGUAGES) == set(ENUM_TRANSLATIONS)
    # Include every literal key in the UI so newly added UI text cannot miss a language.
    literal_keys = {
        node.args[0].value
        for node in ast.walk(ast.parse(APP_PATH.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "t" and node.args and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }
    for language in LANGUAGES:
        assert not (REQUIRED_KEYS | literal_keys) - TRANSLATIONS[language].keys()
        assert TRANSLATIONS[language].keys() == TRANSLATIONS["en"].keys()
        assert all(text.strip() for text in TRANSLATIONS[language].values())


def test_english_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(TRANSLATIONS["ja"], "Library")
    assert t("Library", "ja") == "Library"


def test_unknown_key_and_unsupported_language_fallback() -> None:
    assert t("unknown_ui_key", "ja") == "unknown_ui_key"
    assert t("unknown_ui_key", "unsupported") == "unknown_ui_key"
    assert t("header_caption", "unsupported") == t("header_caption", "en")
    assert display_enum("needs_review", "unsupported") == "Needs review"
    assert canonical_from_display("Needs review", "unsupported") == "needs_review"
    assert t("{count} result(s)", "ja", count=8) == "8件"


@pytest.mark.parametrize("language", ["ja", "ko"])
def test_primary_category_display(language: str) -> None:
    expected = {
        "ja": ["認証", "セッション管理", "認可", "トークンセキュリティ", "OAuth / OIDC / SSO",
               "アカウント管理", "脆弱性診断", "その他のセキュリティ"],
        "ko": ["인증", "세션 관리", "인가", "토큰 보안", "OAuth / OIDC / SSO",
               "계정 관리", "취약점 진단", "기타 보안"],
    }
    assert [display_enum(value, language) for value in PrimaryCategory] == expected[language]
    assert [display_enum(value, "en") for value in PrimaryCategory] == enum_values(PrimaryCategory)


@pytest.mark.parametrize("language,expected", [
    ("ja", ["未読", "確認済み", "読了", "重要"]),
    ("en", ["Unread", "Screened", "Read", "Important"]),
    ("ko", ["읽지 않음", "검토함", "읽음", "중요"]),
])
def test_paper_status_display(language: str, expected: list[str]) -> None:
    assert [display_enum(value, language) for value in PaperStatus] == expected


@pytest.mark.parametrize("language,expected", [
    ("ja", ["分類待ち", "分類済み", "失敗", "要確認"]),
    ("en", ["Pending", "Classified", "Failed", "Needs review"]),
    ("ko", ["분류 대기", "분류 완료", "실패", "검토 필요"]),
])
def test_classification_status_display(language: str, expected: list[str]) -> None:
    assert [display_enum(value, language) for value in ClassificationStatus] == expected


@pytest.mark.parametrize("language", LANGUAGES)
def test_canonical_round_trip_and_original_label_passthrough(language: str) -> None:
    for enum_type in (PrimaryCategory, PaperStatus, ClassificationStatus, Relevance):
        before = enum_values(enum_type)
        for value in before:
            assert canonical_from_display(value, language) == value
            assert canonical_from_display(display_enum(value, language), language) == value
        assert enum_values(enum_type) == before
    for original in ("Session Fixation", "Empirical Study", "Custom AI label", "自由タグ"):
        assert display_enum(original, language) == original
        assert canonical_from_display(original, language) == original
    assert t("Processing failed (ExampleError)", language) == "Processing failed (ExampleError)"


@pytest.fixture
def ui_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database = Database(tmp_path / "i18n-ui.db")
    database.initialize()
    ids = []
    for index in range(3):
        ids.append(database.add_paper(
            file_hash=str(index) * 64, filename=f"fixture-{index}.pdf", filepath=f"fixture-{index}.pdf",
            metadata=ExtractedMetadata(
                title=f"Original title {index}", authors=["Original Author"], year=2023 + index,
                venue="Original Venue", abstract="Original abstract text. " * 6,
                keywords=["Original keyword"], metadata_sources={"title": "PDF metadata"},
            ),
            classification=ClassificationResult(
                primary_category="Session Management", tags=["Session Fixation", "Custom AI tag"],
                research_methods=["Empirical Study"], target_vulnerabilities=["Session Fixation"],
                relevance="A", relevance_reason="Original AI reason.", relevance_confidence=0.9,
            ),
            classification_provider="local", classification_model="original-model",
        ))
    database.update_review(
        ids[2], primary_category="Authentication", tags=["Custom human tag"], relevance="B",
        status="Read", research_methods=["Human method"], target_vulnerabilities=["Human vulnerability"],
        relevance_reason="Original human reason.",
    )
    monkeypatch.setenv("DATABASE_PATH", str(database.path))
    st.cache_resource.clear()
    yield database, ids
    st.cache_resource.clear()


def test_language_switch_preserves_filters_selection_data_and_layout(ui_database) -> None:
    database, ids = ui_database
    before_papers = database.search_papers()
    before_dashboard = database.dashboard_counts()
    before_history = [database.classification_history(paper_id) for paper_id in ids]
    app = AppTest.from_file(str(APP_PATH)).run(timeout=15)
    assert not app.exception
    # Existing initialization performs its normal migration transaction once.
    # Language switches must leave even the SQLite bytes unchanged afterwards.
    before_bytes = database.path.read_bytes()
    assert app.selectbox(key="ui_language").value == "ja"
    assert app.sidebar.selectbox[0].options == ["日本語", "English", "한국어"]

    app.multiselect(key="filter_categories").set_value(["Session Management"])
    app.multiselect(key="filter_tags").set_value(["Session Fixation"])
    app.multiselect(key="filter_methods").set_value(["Empirical Study"])
    app.multiselect(key="filter_vulnerabilities").set_value(["Session Fixation"])
    app.multiselect(key="filter_relevances").set_value(["A"])
    app.multiselect(key="filter_statuses").set_value(["Unread"])
    app.multiselect(key="filter_classification_statuses").set_value(["classified"])
    app.text_input(key="filter_keyword").set_value("Original")
    app.slider(key="filter_years").set_value((2023, 2024))
    app.run(timeout=15)
    app.selectbox(key="selected_paper_id").set_value(ids[0])
    app.run(timeout=15)

    for language in ("en", "ko", "ja"):
        app.selectbox(key="ui_language").set_value(language).run(timeout=15)
        assert not app.exception
        assert app.session_state["ui_language"] == language
        assert app.selectbox(key="selected_paper_id").value == ids[0]
        assert app.multiselect(key="filter_categories").value == ["Session Management"]
        assert list(app.multiselect(key="filter_categories").proto.raw_values) == [
            display_enum("Session Management", language)
        ]
        assert app.multiselect(key="filter_statuses").value == ["Unread"]
        assert app.multiselect(key="filter_classification_statuses").value == ["classified"]
        assert app.multiselect(key="filter_tags").value == ["Session Fixation"]
        assert app.multiselect(key="filter_methods").value == ["Empirical Study"]
        assert app.multiselect(key="filter_vulnerabilities").value == ["Session Fixation"]
        assert app.multiselect(key="filter_relevances").value == ["A"]
        assert app.text_input(key="filter_keyword").value == "Original"
        assert app.slider(key="filter_years").value == (2023, 2024)
        assert [metric.value for metric in app.metric] == ["3", "2", "1", "0", "2"]
        assert len(app.metric) == 5
        table = app.dataframe[0].value
        assert set(table[t("ID", language)]) == set(ids[:2])
        assert set(table[t("Title", language)]) == {"Original title 0", "Original title 1"}
        assert set(table[t("Primary Category", language)]) == {display_enum("Session Management", language)}
        assert set(table[t("Tags", language)]) == {"Custom AI tag, Session Fixation"}
        assert set(table[t("AI Provider", language)]) == {"local"}
        assert set(table[t("AI Model", language)]) == {"original-model"}
        assert app.title[0].value == "SecPaper Atlas"
        assert any(item.value == t("header_caption", language) for item in app.caption)
        assert any(item.value == "Original abstract text. " * 5 + "Original abstract text."
                   for item in app.markdown)
        assert app.selectbox(key=f"review-{ids[0]}-category").value is None
        assert app.text_area(key=f"review-{ids[0]}-tags").value == ""
        assert app.button(key=f"review-{ids[0]}-save").label == t("Save review", language)
        # Layout weights and the right-hand form stay the same for all languages.
        columns = app.get("column")
        assert [round(column.proto.weight, 3) for column in columns] == [0.2] * 5 + [0.167, 0.167, 0.667] + [0.667, 0.333]
        assert len(columns[-1].get("form")) == 1
    assert database.search_papers() == before_papers
    assert database.dashboard_counts() == before_dashboard
    assert [database.classification_history(paper_id) for paper_id in ids] == before_history
    assert database.path.read_bytes() == before_bytes


@pytest.mark.parametrize("language", LANGUAGES)
def test_review_in_each_language_stores_canonical_values_and_preserves_ai(ui_database, language) -> None:
    database, ids = ui_database
    paper_id = ids[0]
    original = database.get_paper(paper_id)
    history = database.classification_history(paper_id)
    app = AppTest.from_file(str(APP_PATH))
    app.session_state["ui_language"] = language
    app.run(timeout=15)
    app.selectbox(key="selected_paper_id").set_value(paper_id).run(timeout=15)
    app.button(key=f"review-{paper_id}-save").click().run(timeout=15)
    assert any(item.value == t("Select a primary category and relevance before saving the review.", language)
               for item in app.error)
    assert database.get_paper(paper_id) == original
    category = app.selectbox(key=f"review-{paper_id}-category")
    assert display_enum("Authorization", language) in category.options
    category.set_value("Authorization")
    app.selectbox(key=f"review-{paper_id}-relevance").set_value("B")
    app.selectbox(key=f"review-{paper_id}-status").set_value("Important")
    app.text_area(key=f"review-{paper_id}-tags").set_value("Session Fixation, Custom human tag")
    app.text_area(key=f"review-{paper_id}-methods").set_value("Human method")
    app.text_area(key=f"review-{paper_id}-vulnerabilities").set_value("Human vulnerability")
    app.text_area(key=f"review-{paper_id}-reason").set_value("Original human reason.")
    app.button(key=f"review-{paper_id}-save").click().run(timeout=15)
    assert not app.exception
    reviewed = database.get_paper(paper_id)
    assert reviewed["primary_category"] == "Authorization"
    assert reviewed["relevance"] == "B"
    assert reviewed["status"] == "Important"
    assert reviewed["tags"] == ["Custom human tag", "Session Fixation"]
    assert reviewed["research_methods"] == ["Human method"]
    assert reviewed["target_vulnerabilities"] == ["Human vulnerability"]
    assert reviewed["relevance_reason"] == "Original human reason."
    for key in original:
        if key.startswith("ai_") or key in ("title", "authors", "abstract", "keywords"):
            assert reviewed[key] == original[key]
    assert database.classification_history(paper_id) == history
    for next_language in LANGUAGES:
        app.selectbox(key="ui_language").set_value(next_language).run(timeout=15)
        assert not app.exception
        assert app.selectbox(key=f"review-{paper_id}-category").value == "Authorization"
        assert app.selectbox(key=f"review-{paper_id}-status").value == "Important"
        if next_language != language:
            assert app.selectbox(key=f"review-{paper_id}-category").proto.raw_value == display_enum(
                "Authorization", next_language
            )
            assert app.selectbox(key=f"review-{paper_id}-status").proto.raw_value == display_enum(
                "Important", next_language
            )
        assert database.get_paper(paper_id) == reviewed


@pytest.mark.parametrize("language", LANGUAGES)
def test_scan_messages_translate_only_known_fixed_text(ui_database, language) -> None:
    app = AppTest.from_file(str(APP_PATH))
    app.session_state["ui_language"] = language
    results = [
        {"filename": "existing.pdf", "status": "Skipped", "message": "Already registered"},
        {"filename": "new.pdf", "status": "Classified", "message": "Success"},
        {"filename": "bad.pdf", "status": "Failed", "message": "Processing failed (ExampleError)"},
    ]
    app.session_state["scan_results"] = results
    app.run(timeout=15)
    assert not app.exception
    assert any(t("Already registered", language) == item.value for item in app.caption)
    assert any("Processing failed (ExampleError)" == item.value for item in app.caption)
    assert any(t("Skipped", language) in item.value for item in app.markdown)
    assert app.session_state["scan_results"] == results
