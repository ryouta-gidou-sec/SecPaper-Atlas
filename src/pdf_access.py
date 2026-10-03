"""Read-only quick access to a registered source PDF on the local PC."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import re
import webbrowser

from src.pdf_parser import has_pdf_signature, is_within_directory, sha256_file


PDF_UNAVAILABLE = "PDF could not be safely located in the inbox."
BROWSER_FAILED = "Unable to open PDF. Check your default browser."


class PDFAccessError(RuntimeError):
    """Expose only a fixed, localizable message key, never a filesystem error."""


def _matching_pdf(candidate: Path, inbox_dir: Path, file_hash: str) -> Path | None:
    try:
        if candidate.suffix.casefold() != ".pdf":
            return None
        resolved = candidate.resolve(strict=True)
        # Check containment before reading signature bytes or computing the hash.
        if not is_within_directory(resolved, inbox_dir) or not has_pdf_signature(resolved):
            return None
        if sha256_file(resolved) != file_hash:
            return None
        return resolved
    except (OSError, ValueError, RuntimeError):
        return None


def resolve_paper_pdf(inbox_dir: Path, paper: Mapping[str, object]) -> Path:
    """Locate the current source by basename and the existing SHA-256 identity.

    Scanner stores only a basename in filename, even for nested PDFs. Prefer the
    current inbox/filename, then look for matching basenames recursively. Hash
    matching prevents opening a different paper when basenames collide. The old
    absolute filepath is deliberately unused, so moving the project is safe.
    """

    try:
        filename = paper.get("filename")
        file_hash = paper.get("file_hash")
        if (
            not isinstance(filename, str)
            or not filename
            or any(character in filename for character in ("/", "\\", ":", "\x00"))
            or Path(filename).name != filename
            or Path(filename).suffix.casefold() != ".pdf"
            or not isinstance(file_hash, str)
            or re.fullmatch(r"[0-9a-fA-F]{64}", file_hash) is None
        ):
            raise PDFAccessError(PDF_UNAVAILABLE)

        inbox = inbox_dir.resolve(strict=True)
        if not inbox.is_dir():
            raise PDFAccessError(PDF_UNAVAILABLE)
        expected_hash = file_hash.casefold()
        direct = inbox / filename
        matched = _matching_pdf(direct, inbox, expected_hash)
        if matched is not None:
            return matched

        for candidate in inbox.rglob("*"):
            if candidate != direct and candidate.name.casefold() == filename.casefold():
                matched = _matching_pdf(candidate, inbox, expected_hash)
                if matched is not None:
                    return matched
    except PDFAccessError:
        raise
    except Exception:
        # Filesystem errors may contain private absolute paths.
        raise PDFAccessError(PDF_UNAVAILABLE) from None
    raise PDFAccessError(PDF_UNAVAILABLE)


def open_paper_pdf(inbox_dir: Path, paper: Mapping[str, object]) -> bool:
    """Open a validated file URI in the local PC's default browser.

    Local-only: webbrowser opens on the Streamlit server's PC. A remote/cloud
    server cannot use this to open the user's browser. The browser/OS decides
    whether to use a tab or window; no particular browser is requested.
    """

    path = resolve_paper_pdf(inbox_dir, paper)
    try:
        if not webbrowser.open_new_tab(path.as_uri()):
            raise PDFAccessError(BROWSER_FAILED)
    except PDFAccessError:
        raise
    except Exception:
        raise PDFAccessError(BROWSER_FAILED) from None
    return True
