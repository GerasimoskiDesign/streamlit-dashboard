"""Text, code and phone-number normalisation (LOCKED).

Daily exports come from different systems and people. The same value arrives as
``Renewal_Only``, ``RENEWAL ONLY`` or ``renewal`` + non-breaking space + ``only``, and
the same phone number as ``+999 70 123 456``, ``99970123456.0`` (an Excel float) or
``999-70-123-456``. If these are not made identical before matching, renewals silently
fail to match their digital flags. Every comparison in the engine goes through here.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

import pandas as pd

_WS = re.compile(r"\s+")
_NON_DIGIT = re.compile(r"\D")
_FLOAT_SUFFIX = re.compile(r"\.0+$")


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def normalize_text(value: Any) -> str:
    """Normalise free text for comparison.

    NFKC folds compatibility characters (non-breaking spaces, full-width letters),
    underscores and hyphens become spaces, runs of whitespace collapse and the result
    is case-folded. ``Renewal_Only`` and ``renewal  only`` both become ``renewal only``.
    """
    if _is_missing(value):
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = text.replace("_", " ").replace("-", " ")
    return _WS.sub(" ", text).strip().casefold()


def normalize_code(value: Any) -> str:
    """Normalise an identifier such as a sales-point code.

    Codes keep their hyphens (``TS-01`` is a real code) but lose whitespace and case
    differences, so `` sp101k`` and ``SP101K`` are the same sales point.
    """
    if _is_missing(value):
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    return _WS.sub("", text).upper()


def normalize_login(value: Any) -> str:
    """Agent logins are matched case-insensitively and without whitespace."""
    return normalize_code(value).lower()


def normalize_phone(value: Any) -> str:
    """Reduce a phone number to digits only.

    Excel stores long numbers as floats, so ``99970123456`` comes back as
    ``99970123456.0``; the trailing ``.0`` must go *before* non-digits are stripped,
    otherwise it would turn into an extra ``0`` and the number would never match.
    """
    if _is_missing(value):
        return ""
    if isinstance(value, float):
        value = f"{value:.0f}"
    text = unicodedata.normalize("NFKC", str(value)).strip()
    text = _FLOAT_SUFFIX.sub("", text)
    return _NON_DIGIT.sub("", text)


def normalize_text_series(series: pd.Series) -> pd.Series:
    """Vectorised :func:`normalize_text` (object dtype keeps behaviour stable across pandas)."""
    return pd.Series([normalize_text(v) for v in series], index=series.index, dtype=object)


def normalize_code_series(series: pd.Series) -> pd.Series:
    """Vectorised :func:`normalize_code`."""
    return pd.Series([normalize_code(v) for v in series], index=series.index, dtype=object)


def normalize_login_series(series: pd.Series) -> pd.Series:
    """Vectorised :func:`normalize_login`."""
    return pd.Series([normalize_login(v) for v in series], index=series.index, dtype=object)


def normalize_phone_series(series: pd.Series) -> pd.Series:
    """Vectorised :func:`normalize_phone`."""
    return pd.Series([normalize_phone(v) for v in series], index=series.index, dtype=object)
