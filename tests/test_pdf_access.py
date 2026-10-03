from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import Mock

import pytest

from src import pdf_access
from src.i18n import LANGUAGES, TRANSLATIONS, t
from src.pdf_access import (
    BROWSER_FAILED, PDF_UNAVAILABLE, PDFAccessError, open_paper_pdf, resolve_paper_pdf,
)


@pytest.fixture(autouse=True)
def browser(monkeypatch: pytest.MonkeyPatch) -> Mock:
    opener = Mock(return_value=True)
    monkeypatch.setattr(pdf_access.webbrowser, "open_new_tab", opener)
    return opener


@pytest.fixture
def source(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    path = inbox / "論文 #1.PDF"
    path.write_bytes(b"%PDF-1.7\noriginal source\n")
    paper = {
        "filename": path.name,
        "file_hash": hashlib.sha256(path.read_bytes()).hexdigest(),
        "filepath": r"C:\OldLocation\papers\inbox\obsolete.pdf",
    }
    return inbox, path, paper


def test_valid_pdf_signature_uri_and_single_successful_open(source, browser, monkeypatch):
    inbox, path, paper = source
    before = path.read_bytes()
    signature_check = Mock(wraps=pdf_access.has_pdf_signature)
    monkeypatch.setattr(pdf_access, "has_pdf_signature", signature_check)
    assert open_paper_pdf(inbox, paper) is True
    signature_check.assert_called_once_with(path.resolve())
    browser.assert_called_once_with(path.resolve().as_uri())
    uri = browser.call_args.args[0]
    assert uri.startswith("file://")
    assert "%20" in uri and "%23" in uri and "%E8" in uri
    assert path.read_bytes() == before


def test_direct_path_is_preferred_without_recursive_discovery(source, browser, monkeypatch):
    inbox, path, paper = source
    monkeypatch.setattr(Path, "rglob", Mock(side_effect=AssertionError("unnecessary discovery")))
    assert resolve_paper_pdf(inbox, paper) == path.resolve()
    browser.assert_not_called()


def test_nested_same_basename_is_selected_by_hash_after_project_move(source, browser):
    inbox, path, paper = source
    nested = inbox / "conference" / path.name
    nested.parent.mkdir()
    nested.write_bytes(path.read_bytes())
    # The root-level basename now belongs to a different paper.
    path.write_bytes(b"%PDF-1.7\ndifferent paper\n")
    other = inbox / "other" / path.name
    other.parent.mkdir()
    other.write_bytes(b"%PDF-1.7\nanother paper\n")
    assert open_paper_pdf(inbox, paper) is True
    browser.assert_called_once_with(nested.resolve().as_uri())


def test_identical_nested_copies_still_have_the_same_registered_identity(source, browser):
    inbox, path, paper = source
    for directory in ("one", "two"):
        nested = inbox / directory / path.name
        nested.parent.mkdir()
        nested.write_bytes(path.read_bytes())
    path.unlink()  # Isolated test fixture only.
    assert open_paper_pdf(inbox, paper) is True
    opened = browser.call_args.args[0]
    assert opened in [(inbox / folder / paper["filename"]).resolve().as_uri()
                      for folder in ("one", "two")]
    browser.assert_called_once()


@pytest.mark.parametrize("case", [
    "missing", "directory", "non_pdf", "fake_pdf", "changed_content", "outside_absolute",
    "outside_relative", "windows_absolute", "windows_traversal", "file_uri", "null_filename",
    "non_string_filename", "missing_hash", "malformed_hash", "non_string_hash",
])
def test_invalid_candidates_fail_without_opening_or_exposing_paths(source, browser, case):
    inbox, path, paper = source
    if case == "missing":
        path.unlink()
    elif case == "directory":
        path.unlink()
        path.mkdir()
    elif case == "non_pdf":
        path = inbox / "source.txt"
        path.write_bytes(b"%PDF-1.7\n")
        paper["filename"] = path.name
    elif case == "fake_pdf":
        path.write_bytes(b"not a PDF")
    elif case == "changed_content":
        path.write_bytes(b"%PDF-1.7\nchanged source\n")
    elif case in ("outside_absolute", "outside_relative"):
        outside = inbox.parent / "outside.pdf"
        outside.write_bytes(b"%PDF-1.7\n")
        paper["filename"] = str(outside) if case == "outside_absolute" else "../outside.pdf"
    elif case == "windows_absolute":
        paper["filename"] = r"C:\Users\private\outside.pdf"
    elif case == "windows_traversal":
        paper["filename"] = r"..\outside.pdf"
    elif case == "file_uri":
        paper["filename"] = "file:///C:/private/outside.pdf"
    elif case == "null_filename":
        paper["filename"] = "bad\x00.pdf"
    elif case == "non_string_filename":
        paper["filename"] = None
    elif case == "missing_hash":
        paper.pop("file_hash")
    elif case == "malformed_hash":
        paper["file_hash"] = "not a hash"
    elif case == "non_string_hash":
        paper["file_hash"] = 123
    with pytest.raises(PDFAccessError) as error:
        open_paper_pdf(inbox, paper)
    assert str(error.value) == PDF_UNAVAILABLE
    assert str(inbox) not in str(error.value)
    assert "C:\\" not in str(error.value)
    browser.assert_not_called()


def test_old_filepath_never_serves_as_an_external_fallback(source, browser):
    inbox, path, paper = source
    outside = inbox.parent / path.name
    outside.write_bytes(path.read_bytes())
    path.unlink()
    paper["filepath"] = str(outside)
    with pytest.raises(PDFAccessError, match="^" + PDF_UNAVAILABLE.replace(".", r"\.") + "$"):
        open_paper_pdf(inbox, paper)
    browser.assert_not_called()


def test_real_directory_link_escape_is_rejected_before_reading(source, browser, monkeypatch):
    inbox, path, paper = source
    outside_dir = inbox.parent / "outside"
    outside_dir.mkdir()
    outside = outside_dir / path.name
    outside.write_bytes(path.read_bytes())
    path.unlink()
    link = inbox / "linked"
    try:
        link.symlink_to(outside_dir, target_is_directory=True)
    except OSError:
        # Windows directory junctions exercise real reparse-point containment
        # without requiring Developer Mode / symbolic-link privileges.
        import _winapi

        _winapi.CreateJunction(str(outside_dir), str(link))
    signature_check = Mock(wraps=pdf_access.has_pdf_signature)
    monkeypatch.setattr(pdf_access, "has_pdf_signature", signature_check)
    try:
        with pytest.raises(PDFAccessError):
            open_paper_pdf(inbox, paper)
        signature_check.assert_not_called()
        browser.assert_not_called()
    finally:
        if link.is_symlink():
            link.unlink()
        else:
            link.rmdir()


def test_resolved_outside_path_is_rejected_even_without_symlink_privileges(
    source, browser, monkeypatch,
):
    inbox, path, paper = source
    outside = inbox.parent / "outside.pdf"
    outside.write_bytes(path.read_bytes())
    original_resolve = Path.resolve

    def escaped_resolve(candidate, *args, **kwargs):
        if candidate == path:
            return original_resolve(outside, *args, **kwargs)
        return original_resolve(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", escaped_resolve)
    signature_check = Mock(wraps=pdf_access.has_pdf_signature)
    monkeypatch.setattr(pdf_access, "has_pdf_signature", signature_check)
    with pytest.raises(PDFAccessError):
        open_paper_pdf(inbox, paper)
    signature_check.assert_not_called()
    browser.assert_not_called()


def test_browser_false_is_a_safe_failure(source, browser):
    inbox, path, paper = source
    browser.return_value = False
    with pytest.raises(PDFAccessError) as error:
        open_paper_pdf(inbox, paper)
    assert str(error.value) == BROWSER_FAILED
    browser.assert_called_once_with(path.resolve().as_uri())


@pytest.mark.parametrize("stage", ["resolve", "signature", "hash", "uri", "browser"])
def test_exceptions_are_sanitized(source, browser, monkeypatch, stage):
    inbox, path, paper = source
    private_error = OSError(r"C:\Users\private\secret.pdf")
    failing = Mock(side_effect=private_error)
    if stage == "resolve":
        monkeypatch.setattr(Path, "resolve", failing)
    elif stage == "signature":
        monkeypatch.setattr(pdf_access, "has_pdf_signature", failing)
    elif stage == "hash":
        monkeypatch.setattr(pdf_access, "sha256_file", failing)
    elif stage == "uri":
        monkeypatch.setattr(Path, "as_uri", failing)
    else:
        browser.side_effect = private_error
    with pytest.raises(PDFAccessError) as error:
        open_paper_pdf(inbox, paper)
    assert str(error.value) == (BROWSER_FAILED if stage in ("uri", "browser") else PDF_UNAVAILABLE)
    assert "private" not in str(error.value)
    assert "C:\\" not in str(error.value)
    if stage == "browser":
        browser.assert_called_once()
    else:
        browser.assert_not_called()


@pytest.mark.parametrize("language,label", [
    ("ja", "PDFを既定ブラウザで開く"),
    ("en", "Open PDF in default browser"),
    ("ko", "기본 브라우저에서 PDF 열기"),
])
def test_all_quick_access_messages_have_translations(language, label):
    assert language in LANGUAGES
    assert t("Open PDF in default browser", language) == label
    for key in ("Open PDF in default browser", PDF_UNAVAILABLE, BROWSER_FAILED):
        assert key in TRANSLATIONS[language]
        assert TRANSLATIONS[language][key].strip()
