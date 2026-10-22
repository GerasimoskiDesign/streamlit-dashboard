"""Hash lock for the production counting logic.

The published numbers are the team's official source for renewal and digital-share
figures, so "someone tweaked a filter" must not be
possible without anyone noticing. The engine files are listed in
``LOCKED_LOGIC.sha256``; the build verifies every hash first and refuses to run if a
file changed. After a reviewed change, ``python -m salesreport lock`` rewrites the
manifest - which then shows up in version control as a deliberate, reviewable diff.

Hashes are computed on content with line endings normalised to LF, so a checkout on
Windows (CRLF) and on Linux (LF) produce the same manifest.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from salesreport.settings import PROJECT_ROOT

MANIFEST_NAME = "LOCKED_LOGIC.sha256"

#: The files whose content defines the published numbers.
LOCKED_FILES = (
    "src/salesreport/rules.py",
    "src/salesreport/normalize.py",
    "src/salesreport/inputs/loader.py",
    "src/salesreport/engine/common.py",
    "src/salesreport/engine/model.py",
    "src/salesreport/engine/v4.py",
)

MODIFIED_MESSAGE = "logic was modified - re-validate before publishing numbers"


class LogicModifiedError(RuntimeError):
    """A locked engine file does not match its recorded hash."""


def file_hash(path: Path) -> str:
    """SHA-256 of the file content with CRLF/CR normalised to LF."""
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def compute_manifest(
    root: Path = PROJECT_ROOT, files: tuple[str, ...] = LOCKED_FILES
) -> dict[str, str]:
    """Current hashes of the locked files, keyed by repo-relative path."""
    return {name: file_hash(root / name) for name in files}


def write_manifest(root: Path = PROJECT_ROOT, files: tuple[str, ...] = LOCKED_FILES) -> Path:
    """Regenerate the manifest after a reviewed change."""
    manifest = compute_manifest(root, files)
    path = root / MANIFEST_NAME
    lines = [f"{digest}  {name}" for name, digest in sorted(manifest.items())]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path


def read_manifest(root: Path = PROJECT_ROOT) -> dict[str, str]:
    """Parse ``<sha256>  <path>`` lines."""
    path = root / MANIFEST_NAME
    if not path.exists():
        raise LogicModifiedError(f"{MANIFEST_NAME} not found - run `python -m salesreport lock`")
    entries = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, name = line.split(maxsplit=1)
            entries[name.strip()] = digest
    return entries


def check_manifest(root: Path = PROJECT_ROOT) -> list[str]:
    """Return a list of problems (empty when every locked file matches)."""
    expected = read_manifest(root)
    problems = []
    for name, digest in sorted(expected.items()):
        path = root / name
        if not path.exists():
            problems.append(f"missing locked file: {name}")
        elif file_hash(path) != digest:
            problems.append(f"changed: {name}")
    for name in LOCKED_FILES:
        if name not in expected:
            problems.append(f"not in manifest: {name}")
    return problems


def verify_lock(root: Path = PROJECT_ROOT) -> None:
    """Raise :class:`LogicModifiedError` if any locked file changed."""
    problems = check_manifest(root)
    if problems:
        raise LogicModifiedError(f"{MODIFIED_MESSAGE}: " + "; ".join(problems))
