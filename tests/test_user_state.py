from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sqlite3
import json

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest
from streamlit.proto.WidgetStates_pb2 import WidgetState

from src.database import Database
from src.i18n import LANGUAGES, TRANSLATIONS, t
from src.models import ClassificationResult, ExtractedMetadata

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


@pytest.fixture
def library(database):
    ids = []
    for index in range(4):
        ids.append(database.add_paper(
            file_hash=str(index) * 64, filename=f"synthetic-{index}.pdf",
            filepath=f"synthetic-{index}.pdf",
            metadata=ExtractedMetadata(title=f"Synthetic paper {index}", year=2020 + index),
            classification=ClassificationResult(
                primary_category="Authentication", relevance="A", relevance_reason="Synthetic reason",
                relevance_confidence=0.9, tags=["Synthetic tag"],
                research_methods=["Synthetic method"], target_vulnerabilities=["Synthetic vulnerability"],
            ),
            classification_provider="local", classification_model="synthetic-model",
        ))
    database.update_review(
        ids[0], primary_category="Authorization", relevance="B", status="Read",
        tags=["Human tag"], research_methods=["Human method"],
        target_vulnerabilities=["Human vulnerability"], relevance_reason="Human reason",
    )
    return database, ids


def snapshot(database):
    with database.connect_readonly() as connection:
        return database.snapshot(connection)


def test_existing_database_additive_initialization_and_default_state(library):
    database, ids = library
    with database.connect() as connection:
        connection.execute("DROP TABLE paper_user_state")
    before = snapshot(database)
    database.initialize()
    after = snapshot(database)
    assert {k: v for k, v in after["tables"].items() if k != "paper_user_state"} == before["tables"]
    assert after["tables"]["paper_user_state"] == []
    assert [r for r in after["schema"] if r[2] != "paper_user_state"] == before["schema"]
    raw = database.path.read_bytes()
    for _ in range(3):
        database.initialize()
        assert database.path.read_bytes() == raw
        assert snapshot(database) == after
    for paper_id in ids:
        state = database.get_user_state(paper_id)
        assert state == {"paper_id": paper_id, "is_favorite": False, "read_later": False,
                         "created_at": None, "updated_at": None}
        assert database.get_paper(paper_id)["user_state"] == state
    assert snapshot(database) == after  # Reading defaults does not insert rows.


@pytest.mark.parametrize("flag,setter,other", [
    ("is_favorite", "set_favorite", "read_later"),
    ("read_later", "set_read_later", "is_favorite"),
])
def test_on_off_independence_persistence_and_no_ai_changes(library, flag, setter, other):
    database, ids = library
    before = deepcopy(snapshot(database))
    paper_id = ids[0]
    database.set_user_state(paper_id, **{other: True})
    for enabled in (True, False, True, False):
        getattr(database, setter)(paper_id, enabled)
        reopened = Database(database.path)
        state = reopened.get_user_state(paper_id)
        assert state[flag] is enabled
        assert state[other] is True
        assert state["created_at"] and state["updated_at"]
        assert reopened.get_paper(paper_id)["user_state"] == state
    after = snapshot(database)
    assert after["schema"] == before["schema"]
    assert {k: v for k, v in after["tables"].items() if k != "paper_user_state"} == {
        k: v for k, v in before["tables"].items() if k != "paper_user_state"
    }  # Exact papers, AI originals, Human Review, labels, timestamps and history.
    assert len(after["tables"]["paper_user_state"]) == 1
    unchanged = database.path.read_bytes()
    database.set_user_state(paper_id, **{flag: False, other: True})
    assert database.path.read_bytes() == unchanged


def test_user_state_filters_and_existing_filters(library):
    database, ids = library
    database.set_favorite(ids[0], True)
    database.set_read_later(ids[1], True)
    database.set_user_state(ids[2], is_favorite=True, read_later=True)
    def result(**filters):
        return {paper["id"] for paper in database.search_papers(**filters)}
    assert result() == set(ids)
    assert result(favorites_only=True) == {ids[0], ids[2]}
    assert result(read_later_only=True) == {ids[1], ids[2]}
    assert result(favorites_only=True, read_later_only=True) == {ids[2]}
    assert result(favorites_only=True, keyword="does not exist") == set()
    assert result(read_later_only=True, categories=["Authorization"]) == set()
    assert result(favorites_only=True, categories=["Authorization"], relevances=["B"],
                  statuses=["Read"], tags=["Human tag"], methods=["Human method"],
                  vulnerabilities=["Human vulnerability"], classification_statuses=["classified"],
                  year_min=2020, year_max=2020, keyword="Synthetic") == {ids[0]}


@pytest.mark.parametrize("invalid", [True, 0, -1, "1", "1 OR 1=1", 1.0, None, 2**63])
def test_user_state_rejects_invalid_ids(library, invalid):
    database, _ = library
    before = snapshot(database)
    with pytest.raises(ValueError):
        database.set_favorite(invalid, True)
    with pytest.raises(ValueError):
        database.get_user_state(invalid)
    assert snapshot(database) == before


@pytest.mark.parametrize("invalid", [0, 1, "true", "false", [], {}])
def test_user_state_rejects_nonboolean_values(library, invalid):
    database, ids = library
    before = snapshot(database)
    with pytest.raises(ValueError):
        database.set_favorite(ids[0], invalid)
    with pytest.raises(ValueError):
        database.set_read_later(ids[0], invalid)
    with pytest.raises(ValueError):
        database.search_papers(favorites_only=invalid)
    with pytest.raises(ValueError):
        database.search_papers(read_later_only=invalid)
    assert snapshot(database) == before


def test_missing_paper_and_database_constraints(library):
    database, ids = library
    for operation in (lambda: database.get_user_state(9999),
                      lambda: database.set_favorite(9999, True),
                      lambda: database.set_user_state(ids[0])):
        with pytest.raises(ValueError):
            operation()
    with database.connect() as connection:
        connection.execute("INSERT INTO paper_user_state (paper_id) VALUES (?)", (ids[0],))
    assert database.get_user_state(ids[0])["is_favorite"] is False
    assert database.get_user_state(ids[0])["read_later"] is False
    for sql, args in (
        ("INSERT INTO paper_user_state (paper_id) VALUES (?)", (ids[0],)),
        ("INSERT INTO paper_user_state (paper_id) VALUES (?)", (9999,)),
        ("UPDATE paper_user_state SET is_favorite = ? WHERE paper_id = ?", (2, ids[0])),
        ("UPDATE paper_user_state SET read_later = ? WHERE paper_id = ?", (-1, ids[0])),
    ):
        with pytest.raises(sqlite3.IntegrityError), database.connect() as connection:
            connection.execute(sql, args)


def test_snapshot_captures_user_state_for_refresh_stale_state_checks(library):
    database, ids = library
    before = snapshot(database)
    database.set_read_later(ids[0], True)
    assert snapshot(database)["tables"]["paper_user_state"] != before["tables"]["paper_user_state"]


def edit_list(app, row, **flags):
    editor = app.dataframe[0]
    # AppTest has no data-editor interaction method. Deliver the same serialized
    # widget event as the browser, preserving all other widgets' current state.
    states = app._tree.get_widget_states()
    states.widgets.append(WidgetState(
        id=editor.proto.id,
        string_value=json.dumps({"edited_rows": {row: flags}, "added_rows": [], "deleted_rows": []}),
    ))
    app._run(states, timeout=15)
    assert not app.exception


@pytest.mark.parametrize("language", LANGUAGES)
def test_list_detail_filters_reload_localization_and_no_classifier(library, monkeypatch, language):
    database, ids = library
    monkeypatch.setenv("DATABASE_PATH", str(database.path))
    def reject_classifier(*args, **kwargs):
        pytest.fail("Favorite / Read Later must never invoke a classifier or scan")
    monkeypatch.setattr("src.classifier.create_classifier", reject_classifier)
    monkeypatch.setattr("src.scanner.scan_inbox", reject_classifier)
    protected = snapshot(database)["tables"]
    app = AppTest.from_file(str(APP_PATH))
    app.session_state["ui_language"] = language
    app.run(timeout=15)
    assert not app.exception
    for key in ("Favorite", "Read Later", "Favorites only", "Read Later only"):
        assert key in TRANSLATIONS[language]
    target = ids[2]
    row = next(index for index, value in enumerate(app.dataframe[0].value[t("ID", language)])
               if value == target)
    app.selectbox(key="selected_paper_id").set_value(target).run(timeout=15)
    edit_list(app, row, **{t("Favorite", language): True})
    assert database.get_user_state(target)["is_favorite"] is True
    assert app.toggle(key=f"user-state-{target}-is_favorite").value is True
    assert app.toggle(key=f"user-state-{target}-read_later").value is False
    app.toggle(key=f"user-state-{target}-read_later").set_value(True).run(timeout=15)
    assert not app.exception
    table = app.dataframe[0].value
    assert bool(table.loc[table[t("ID", language)] == target, t("Read Later", language)].iloc[0])
    app.checkbox(key="filter_favorites").check().run(timeout=15)
    assert list(app.dataframe[0].value[t("ID", language)]) == [target]
    app.checkbox(key="filter_read_later").check().run(timeout=15)
    assert list(app.dataframe[0].value[t("ID", language)]) == [target]
    app.toggle(key=f"user-state-{target}-is_favorite").set_value(False).run(timeout=15)
    assert not app.exception
    assert not app.dataframe
    app.checkbox(key="filter_favorites").uncheck().run(timeout=15)
    assert list(app.dataframe[0].value[t("ID", language)]) == [target]
    edit_list(app, 0, **{t("Read Later", language): False})
    assert not app.dataframe
    app.checkbox(key="filter_read_later").uncheck().run(timeout=15)
    edit_list(app, row, **{t("Favorite", language): True, t("Read Later", language): True})
    reopened = AppTest.from_file(str(APP_PATH))
    reopened.session_state["ui_language"] = language
    reopened.run(timeout=15)
    state = database.get_user_state(target)
    assert state["is_favorite"] and state["read_later"]
    reopened.selectbox(key="selected_paper_id").set_value(target).run(timeout=15)
    assert reopened.toggle(key=f"user-state-{target}-is_favorite").value is True
    assert reopened.toggle(key=f"user-state-{target}-read_later").value is True
    for other_language in LANGUAGES:
        reopened.selectbox(key="ui_language").set_value(other_language).run(timeout=15)
        assert not reopened.exception
        assert reopened.toggle(key=f"user-state-{target}-is_favorite").label == t("Favorite", other_language)
        assert reopened.checkbox(key="filter_read_later").label == t("Read Later only", other_language)
    after = snapshot(database)["tables"]
    assert {k: v for k, v in after.items() if k != "paper_user_state"} == {
        k: v for k, v in protected.items() if k != "paper_user_state"
    }


def test_initialize_preserves_saved_flags_timestamps_and_database_bytes(library):
    database, ids = library
    database.set_user_state(ids[0], is_favorite=True, read_later=True)
    with database.connect() as connection:
        connection.execute(
            "UPDATE paper_user_state SET created_at = ?, updated_at = ? WHERE paper_id = ?",
            ("2020-01-01T00:00:00.000Z", "2020-01-01T00:00:00.000Z", ids[0]),
        )
    database.set_favorite(ids[0], False)
    state = database.get_user_state(ids[0])
    assert state["created_at"] == "2020-01-01T00:00:00.000Z"
    assert state["updated_at"] != state["created_at"]
    assert state["read_later"] is True
    raw = database.path.read_bytes()
    for _ in range(3):
        database.initialize()
        assert database.get_user_state(ids[0]) == state
        assert database.path.read_bytes() == raw
