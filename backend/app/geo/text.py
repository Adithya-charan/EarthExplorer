"""Name normalisation shared by the gazetteer and the resolver."""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

_NON_ALNUM = re.compile(r"[^0-9a-z]+")


@lru_cache(maxsize=400_000)
def fold(text: str | None) -> str:
    """Case-fold, strip accents and collapse punctuation: 'Île-de-France' -> 'ile de france'."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    stripped = stripped.replace("ß", "ss").replace("ø", "o").replace("Ø", "O").replace("ł", "l").replace("Ł", "L")
    return _NON_ALNUM.sub(" ", stripped.casefold()).strip()


def slug(text: str | None) -> str:
    return fold(text).replace(" ", "-")


def title_case_if_shouting(name: str | None) -> str | None:
    """Natural Earth stores some physical names in capitals ('SAHARA'); show them as 'Sahara'."""
    if not name:
        return name
    letters = [c for c in name if c.isalpha()]
    if letters and all(c.isupper() for c in letters) and len(letters) > 3:
        return name.title()
    return name
