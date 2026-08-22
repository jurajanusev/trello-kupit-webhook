from __future__ import annotations

import re
import unicodedata


CARD_URL_RE = re.compile(r"https://trello\.com/c/[A-Za-z0-9]+", re.I)


def school_bag_type(value, *, school_context=False, fold=None):
    """Return the durable type alias without inferring an owner or a physical item."""
    if fold is None:
        fold = lambda text: "".join(
            character for character in unicodedata.normalize("NFKD", text or "")
            if not unicodedata.combining(character)
        ).casefold()
    core = fold(strip_technical_wrappers(value))
    explicit_school = bool(re.search(r"\bskolsk\w*\b", core))
    has_bag = bool(re.search(r"\b(?:batoh|task)\w*\b", core))
    if has_bag and (explicit_school or school_context):
        return "skolska taska"
    return None


def strip_technical_wrappers(value):
    """Return the written identity only; do not infer an object from keywords."""
    text = str(value or "").strip()
    text = re.sub(r"^\s*(?:<n>|[←→↳])\s*", "", text, flags=re.I)
    text = text.replace("**", "").replace("*", "")
    text = re.sub(r"\s*\|\s*KARTA:\s*https?://\S+.*$", "", text, flags=re.I)
    text = re.split(r"\s+[—–]\s+", text, maxsplit=1)[0]
    text = re.split(r"\s+\|\s+(?:TU:|←|→)", text, maxsplit=1, flags=re.I)[0]
    return text.strip()


def resolve_identity(value, *, url_to_canonical=None, canonical_names=(), aliases=None,
                     owner_type_matches=None, physical_matches=None, fold=lambda x: x.casefold()):
    """Resolve using the permanent evidence order and never fuzzy similarity."""
    url_to_canonical = url_to_canonical or {}
    aliases = aliases or {}
    owner_type_matches = owner_type_matches or {}
    physical_matches = physical_matches or {}
    urls = CARD_URL_RE.findall(str(value or ""))
    linked = {url_to_canonical[url.casefold()] for url in urls if url.casefold() in url_to_canonical}
    if len(linked) == 1:
        return {"canonical": linked.pop(), "evidence": "master_url", "ambiguous": False}
    if len(linked) > 1:
        return {"canonical": None, "evidence": "conflicting_master_urls", "ambiguous": True}
    core = strip_technical_wrappers(value)
    canonical = {fold(name): name for name in canonical_names}
    if fold(core) in canonical:
        return {"canonical": canonical[fold(core)], "evidence": "canonical_name", "ambiguous": False}
    alias_map = {fold(alias): name for name, values in aliases.items() for alias in values}
    if fold(core) in alias_map:
        return {"canonical": alias_map[fold(core)], "evidence": "explicit_alias", "ambiguous": False}
    if fold(core) in owner_type_matches:
        return {"canonical": owner_type_matches[fold(core)], "evidence": "owner_plus_type", "ambiguous": False}
    if fold(core) in physical_matches:
        return {"canonical": physical_matches[fold(core)], "evidence": "confirmed_physical_identity", "ambiguous": False}
    return {"canonical": None, "evidence": "unresolved", "ambiguous": True}
