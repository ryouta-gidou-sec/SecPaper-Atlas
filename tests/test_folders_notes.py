"""Use synthetic papers to exercise local organization and real UI interactions."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.database import Database, FolderError
from src.i18n import t
from src.models import ClassificationResult, ExtractedMetadata


def add_paper(database, char="a", title="Session fixture"):
    return database.add_paper(
        file_hash=char * 64, filename="fixture.pdf", filepath="fixture.pdf",
        metadata=ExtractedMetadata(title=title, year=2024, abstract="Synthetic abstract."),
        classification=ClassificationResult(
            primary_category="Session Management", relevance="A", tags=["session"],
            relevance_reason="Synthetic reason.", relevance_confidence=0.9,
        ),
    )


def snapshot(database):
    with database.connect_readonly() as connection:
        return database.snapshot(connection)


def protected(database):
    return {key: value for key, value in snapshot(database)["tables"].items()
            if key not in {"folders", "paper_folders", "sqlite_sequence"}}


@pytest.mark.parametrize("name", ["", "  \t\n", "x" * 101, "bad\nname", None, 123])
def test_invalid_names(database, name):
    with pytest.raises(FolderError):
        database.create_folder(name)
    folder_id = database.create_folder("Valid")
    with pytest.raises(FolderError):
        database.rename_folder(folder_id, name)
    assert database.list_folders()[0]["name"] == "Valid"


@pytest.mark.parametrize("first, duplicate", [
    ("Session Security", " session security "), ("Straße", "STRASSE"),
    ("Café", "Cafe\u0301"), ("卒論候補", " 卒論候補 "),
])
def test_trim_casefold_unique_create_rename(database, first, duplicate):
    folder_id = database.create_folder(" " + first + " ")
    assert database.list_folders()[0]["name"] == first
    with pytest.raises(FolderError, match="already exists"):
        database.create_folder(duplicate)
    other = database.create_folder("Other")
    with pytest.raises(FolderError, match="already exists"):
        database.rename_folder(other, duplicate)
    database.rename_folder(folder_id, first.upper())
    database.create_folder("x" * 100)
    assert len(database.list_folders()) == 3


def test_many_to_many_combined_filters_and_delete_isolation(database):
    first, second = add_paper(database), add_paper(database, "b", "Other fixture")
    database.update_review(
        first, primary_category="Authentication", tags=["reviewed"], relevance="B", status="Read",
    )
    database.set_favorite(first, True)
    database.set_read_later(first, True)
    database.set_note(first, "セッション固定の評価方法が参考になりそう\nSecond line.")
    baseline = protected(database)
    folders = [database.create_folder(name) for name in ("卒論候補", "Session Security", "精読予定")]
    database.set_paper_folders(first, folders)
    database.set_paper_folders(second, [folders[1]])
    assert len(database.get_paper(first)["folders"]) == 3
    assert {p["id"] for p in database.search_papers(folder_id=folders[1])} == {first, second}
    assert [p["id"] for p in database.search_papers(
        folder_id=folders[1], keyword="Session", categories=["Authentication"],
        relevances=["B"], statuses=["Read"], tags=["reviewed"],
        classification_statuses=["classified"], year_min=2024, year_max=2024,
        favorites_only=True, read_later_only=True,
    )] == [first]
    assert database.search_papers(folder_id=folders[0], relevances=["A"]) == []
    database.rename_folder(folders[0], "Renamed")
    assert "Renamed" in {f["name"] for f in database.get_paper(first)["folders"]}
    database.delete_folder(folders[1])
    assert len(database.get_paper(first)["folders"]) == 2
    assert database.get_paper(second)["folders"] == []
    assert protected(database) == baseline
    database.set_paper_folders(first, [])
    assert protected(database) == baseline


def test_membership_atomic_validation_persistence(database):
    paper_id = add_paper(database)
    folder_id = database.create_folder("Candidates")
    database.set_paper_folders(paper_id, [folder_id, folder_id])
    for ids in ([folder_id, 999], [0], [-1], [True], ["1"], [2**63]):
        with pytest.raises(FolderError):
            database.set_paper_folders(paper_id, ids)
        assert [f["id"] for f in database.get_paper(paper_id)["folders"]] == [folder_id]
    with pytest.raises(FolderError):
        database.set_paper_folders(999, [folder_id])
    with pytest.raises(FolderError):
        database.rename_folder(999, "New")
    with pytest.raises(FolderError):
        database.delete_folder(999)
    database.initialize()
    assert Database(database.path).get_paper(paper_id)["folders"][0]["id"] == folder_id
    assert database.list_folders()[0]["paper_count"] == 1


def test_additive_migration_and_legacy_readonly_snapshot(database):
    paper_id = add_paper(database)
    database.set_favorite(paper_id, True)
    with database.connect() as connection:
        for table in ("paper_folders", "folders", "paper_notes"):
            connection.execute(f"DROP TABLE {table}")
    before = snapshot(database)
    database.initialize()
    after = snapshot(database)
    assert {k: v for k, v in after["tables"].items()
            if k not in {"folders", "paper_folders", "paper_notes"}} == before["tables"]
    assert database.get_paper(paper_id)["folders"] == []
    assert database.get_paper(paper_id)["note"] == ""
    raw = database.path.read_bytes()
    database.initialize()
    assert database.path.read_bytes() == raw


def test_note_preserves_folders_flags_and_ai_across_retry(database):
    paper_id = add_paper(database)
    folder_id = database.create_folder("Candidates")
    database.set_paper_folders(paper_id, [folder_id])
    database.set_user_state(paper_id, is_favorite=True, read_later=True)
    before = snapshot(database)
    for content in ("読みたい\n'quoted' <script>text</script>", "x" * 10000, ""):
        database.set_note(paper_id, content)
        assert Database(database.path).get_paper(paper_id)["note"] == content
        after = snapshot(database)
        assert {k: v for k, v in after["tables"].items() if k != "paper_notes"} == {
            k: v for k, v in before["tables"].items() if k != "paper_notes"
        }
    for invalid in (None, False, "x" * 10001, "bad\x00text"):
        with pytest.raises(ValueError):
            database.set_note(paper_id, invalid)
        assert database.get_paper(paper_id)["note"] == ""
    with pytest.raises(ValueError):
        database.set_note(999, "test")
    database.set_note(paper_id, "Saved note")
    note_before = snapshot(database)["tables"]["paper_notes"]
    database.update_classification(
        paper_id, ClassificationResult(
            primary_category="Token Security", relevance="C", relevance_reason="Retry.",
            relevance_confidence=0.8,
        ),
        classification_status="classified",
    )
    assert snapshot(database)["tables"]["paper_notes"] == note_before
    assert database.get_paper(paper_id)["folders"][0]["id"] == folder_id
    database.update_review(paper_id, primary_category="Authentication", relevance="B", status="Read", tags=[])
    assert snapshot(database)["tables"]["paper_notes"] == note_before
    assert database.get_paper(paper_id)["folders"][0]["id"] == folder_id


@pytest.mark.parametrize("language", ["ja", "en", "ko"])
def test_ui_folder_lifecycle_and_notes(tmp_path, monkeypatch, language):
    database = Database(tmp_path / "folders-ui.db")
    database.initialize()
    paper_id = add_paper(database)
    add_paper(database, "b", "Other fixture")
    database.set_user_state(paper_id, is_favorite=True, read_later=True)
    monkeypatch.setenv("DATABASE_PATH", str(database.path))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
    app.session_state["ui_language"] = language
    app.run(timeout=15)
    assert not app.exception
    assert app.sidebar.expander[0].label == "＋ " + t("New Folder", language)
    app.text_input(key="new_folder_name").set_value(" ")
    app.button(key="create_folder").click().run(timeout=15)
    assert any(item.value == t("Enter a folder name.", language) for item in app.error)
    for name in ("卒論候補", "Session Security"):
        app.text_input(key="new_folder_name").set_value(name)
        app.button(key="create_folder").click().run(timeout=15)
        assert not app.exception
    ids = {f["name"]: f["id"] for f in database.list_folders()}
    app.selectbox(key="selected_paper_id").set_value(paper_id).run(timeout=15)
    app.multiselect(key=f"paper-folders-{paper_id}").set_value(list(ids.values()))
    app.button(key="save_paper_folders").click().run(timeout=15)
    assert not app.exception
    assert len(database.get_paper(paper_id)["folders"]) == 2
    app.text_area(key=f"paper-note-{paper_id}").set_value("セッション固定の評価方法が参考になりそう")
    app.button(key="save_paper_note").click().run(timeout=15)
    assert database.get_paper(paper_id)["note"] == "セッション固定の評価方法が参考になりそう"
    baseline = protected(database)
    app.radio(key="filter_folder").set_value(ids["卒論候補"]).run(timeout=15)
    app.checkbox(key="filter_favorites").check()
    app.checkbox(key="filter_read_later").check().run(timeout=15)
    assert len(app.dataframe[0].value) == 1
    app.text_input(key="filter_keyword").set_value("absent").run(timeout=15)
    assert not app.dataframe
    app.text_input(key="filter_keyword").set_value("").run(timeout=15)
    app.selectbox(key="manage_folder_id").set_value(ids["卒論候補"]).run(timeout=15)
    rename_key = f"rename-folder-{ids['卒論候補']}-卒論候補"
    app.text_input(key=rename_key).set_value("精読予定")
    app.button(key="rename_folder").click().run(timeout=15)
    assert not app.exception
    assert "📁 精読予定" in app.radio(key="filter_folder").options
    assert app.radio(key="filter_folder").value == ids["卒論候補"]
    assert "精読予定" in app.multiselect(key=f"paper-folders-{paper_id}").options
    app.button(key="delete_folder").click().run(timeout=15)
    assert len(database.list_folders()) == 2
    app.checkbox(key=f"confirm-delete-folder-{ids['卒論候補']}-精読予定").check()
    app.button(key="delete_folder").click().run(timeout=15)
    assert not app.exception
    assert app.radio(key="filter_folder").value == 0
    assert len(database.list_folders()) == 1
    assert database.get_paper(paper_id)["folders"][0]["name"] == "Session Security"
    assert protected(database) == baseline
    app.checkbox(key=f"confirm-delete-folder-{ids['Session Security']}-Session Security").check()
    app.button(key="delete_folder").click().run(timeout=15)
    assert not app.exception
    assert database.get_paper(paper_id)["folders"] == []
    assert protected(database) == baseline
