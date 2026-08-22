from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from flask import jsonify, request

from cierny_kamen_all_props_registry import (
    PROP_AUTO_END,
    PROP_AUTO_START,
    exact_named,
    folded,
)
from cierny_kamen_global_reference import desired_description
from cierny_kamen_meeting_semantic_dryrun import load_board
from cierny_kamen_prop_identity_resolution import strip_technical_wrappers


KEY = "ck-followup-20aug-4f91d37c"
ENDPOINT_DISABLED = False
URL_RE = re.compile(r"https://trello\.com/c/[A-Za-z0-9]+", re.I)
LEGACY_HEADINGS = {
    "rekvizity v kontexte", "nadvaznost", "odkazy",
    "kontinuita priestoru", "kontinuita postav",
}
EXCLUDED_LIST_PARTS = (
    "original screener", "register", "rekvizit", "os. rekvizity",
    "nadvazne sety", "todo", "priestor", "auta",
)
MAP_PATH = Path(__file__).with_name("cierny_kamen_all_props_registry_map.json")
CONTINUITY_LABEL = "Nadväzná rekvizita"
KNOWN_AUTOMATED_N_IDENTITIES = {
    "Doggyho slúchadlá",
    "BANNER NA OTVORENIE BASKETBALOVEJ SEZÓNY",
    "Drevená pramica Jakuba a Sáry",
    "Výbava skautskej skupiny",
}
OWNER_ALIASES = {
    "alex": ("alexov", "alexova", "alexove", "alex"),
    "bety": ("betin", "betina", "betynina", "bety"),
    "kiko": ("kikov", "kikova", "kiko"),
    "veronika": ("veronikin", "veronikina", "veronika"),
    "dogy": ("dogyho", "dogy", "dagyho", "dagy"),
}


def starts_n(value):
    return bool(re.match(r"^\s*<n>(?:\s|\*|$)", value or "", re.I))


def contains_z(value):
    return "[z]" in (value or "").casefold()


def sha(value):
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def is_production_list(name):
    key = folded(name)
    return bool(key) and not any(part in key for part in EXCLUDED_LIST_PARTS)


def bag_type(value):
    key = folded(strip_technical_wrappers(value))
    if re.search(r"\b(?:batoh|skolsk\w*\s+(?:task|batoh))", key):
        return "školská taška"
    return None


def explicit_school_bag(value):
    key = folded(strip_technical_wrappers(value))
    return bool(re.search(r"\bskolsk\w*\b", key) and re.search(r"\b(?:task|batoh)\w*\b", key))


def bag_owner(value):
    key = folded(strip_technical_wrappers(value))
    for owner, aliases in OWNER_ALIASES.items():
        if any(re.search(rf"\b{re.escape(alias)}\w*\b", key) for alias in aliases):
            return owner
    return None


def known_automated_n(value):
    core = folded(strip_technical_wrappers(value))
    return core in {folded(name) for name in KNOWN_AUTOMATED_N_IDENTITIES}


def owner_from_list(list_name):
    match = re.match(r"^\s*(.+?)\s*[–—-]\s*OS\.\s*REKVIZITY\s*$", list_name or "", re.I)
    return match.group(1).strip() if match else None


def card_prop_rows(card):
    rows = []
    for checklist in card.get("checklists", []):
        if folded(checklist.get("name")) != "rekvizity":
            continue
        for item in sorted(checklist.get("checkItems", []), key=lambda row: row.get("pos", 0)):
            text = item.get("name") or ""
            rows.append({
                "card_id": card["id"], "checklist_id": checklist["id"],
                "item_id": item["id"], "text": text,
                "state": item.get("state"), "pos": item.get("pos"),
                "urls": URL_RE.findall(text), "has_n": starts_n(text),
                "has_z": contains_z(text), "text_sha256": sha(text),
            })
    return rows


def production_scenes(api, state):
    groups = defaultdict(list)
    for card in state["cards"]:
        if not is_production_list(card.get("list_name")):
            continue
        info = api["cierny_kamen_scene_name_info"](card.get("name", ""))
        if not info or info.get("test"):
            continue
        groups[info["scene_id"]].append(card)
    return dict(groups)


def load_archived_list_cards(api, state):
    result = []
    for board_list in state["lists"]:
        if not board_list.get("closed"):
            continue
        if "rekviz" not in folded(board_list.get("name")) and folded(board_list.get("name")) != "auta":
            continue
        rows = api["trello_get"](f"/lists/{board_list['id']}/cards", {
            "fields": "id,name,desc,shortUrl,idList,closed,pos,idLabels,dateLastActivity",
            "filter": "all", "limit": 1000,
        })
        for card in rows:
            result.append({**card, "list_name": board_list.get("name")})
    return result


def master_cards(api, state):
    candidates = []
    for card in state["cards"]:
        list_name = card.get("list_name") or ""
        if "rekviz" in folded(list_name) or folded(list_name) == "auta":
            candidates.append(card)
    known = {card["id"] for card in candidates}
    for card in load_archived_list_cards(api, state):
        if card["id"] not in known:
            candidates.append(card); known.add(card["id"])
    return candidates


def aliases_from_master(card):
    desc = card.get("desc") or ""
    aliases = []
    match = re.search(r"(?im)^ALIASY:\s*(.+)$", desc)
    if match and match.group(1).strip() != "—":
        aliases.extend(part.strip() for part in match.group(1).split(",") if part.strip())
    return aliases


def _manual_n_status(row, previous):
    if not row["has_n"]:
        return None
    if not previous:
        return "new_item_after_identity_map"
    if not starts_n(previous.get("original_name")):
        return "n_added_after_identity_map"
    return "already_known_n"


def build_audit(api):
    state = load_board(api)
    groups = production_scenes(api, state)
    scene_cards = {scene_id: rows[0] for scene_id, rows in groups.items() if len(rows) == 1}
    collisions = {scene_id: [card.get("shortUrl") for card in rows]
                  for scene_id, rows in groups.items() if len(rows) != 1}
    payload = api["cierny_kamen_import_payload"]()
    source_ids = {scene["scene_id"] for scene in payload["scenes"]}

    description_ops, description_conflicts, old_description_cards = [], [], []
    all_rows = []
    for scene_id, card in sorted(scene_cards.items()):
        rows = card_prop_rows(card)
        all_rows.extend({"scene_id": scene_id, "scene_url": card.get("shortUrl"), **row} for row in rows)
        desc = card.get("desc") or ""
        heading_keys = {folded(value) for value in re.findall(r"(?m)^#{2,3}\s+(.+?)\s*$", desc)}
        legacy = sorted(heading_keys & LEGACY_HEADINGS)
        if not legacy:
            continue
        old_description_cards.append({"scene_id": scene_id, "url": card.get("shortUrl"), "legacy": legacy})
        desired, conflict, preserved = desired_description(desc, rows)
        if conflict:
            description_conflicts.append({"scene_id": scene_id, "url": card.get("shortUrl"), "reason": conflict})
        elif desired != desc.strip():
            description_ops.append({
                "scene_id": scene_id, "card_id": card["id"], "url": card.get("shortUrl"),
                "before": desc, "after": desired,
                "before_sha256": sha(desc), "preserved_origins": [origin for origin, _ in preserved],
                "protected_z": [{"item_id": row["item_id"], "sha256": row["text_sha256"]}
                                for row in rows if row["has_z"]],
            })

    masters = master_cards(api, state)
    list_by_id = state["list_by_id"]
    masters_by_url = {(card.get("shortUrl") or "").casefold(): card for card in masters if card.get("shortUrl")}
    bag_rows = [row for row in all_rows if bag_type(row["text"])]
    bag_occurrences = []
    for row in bag_rows:
        linked = [masters_by_url[url.casefold()] for url in row["urls"] if url.casefold() in masters_by_url]
        bag_occurrences.append({
            **{key: row[key] for key in ("scene_id", "scene_url", "item_id", "text", "state", "urls", "has_n", "has_z")},
            "linked_masters": [{
                "id": card["id"], "name": card.get("name"), "url": card.get("shortUrl"),
                "closed": card.get("closed"),
                "list": list_by_id.get(card.get("idList"), {}).get("name") or card.get("list_name"),
            } for card in linked],
        })
    bag_master_candidates = []
    for card in masters:
        aliases = aliases_from_master(card)
        if bag_type(card.get("name")) or any(bag_type(alias) for alias in aliases):
            list_name = list_by_id.get(card.get("idList"), {}).get("name") or card.get("list_name")
            bag_master_candidates.append({
                "id": card["id"], "name": card.get("name"), "url": card.get("shortUrl"),
                "closed": card.get("closed"), "list": list_name,
                "owner_from_list": owner_from_list(list_name), "aliases": aliases,
                "desc_sha256": sha(card.get("desc") or ""),
            })
    by_owner = defaultdict(list)
    for card in bag_master_candidates:
        if card["owner_from_list"] and explicit_school_bag(card["name"]):
            by_owner[folded(card["owner_from_list"])].append(card)
    bag_duplicate_groups = [
        {"owner": owner, "cards": cards, "action": "review_same_owner_school_bag_identity"}
        for owner, cards in sorted(by_owner.items()) if len(cards) > 1
    ]
    bag_conflicts = [row for row in bag_occurrences if len(row["linked_masters"]) != 1]

    identity_map = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    old_by_item = {row["item_id"]: row for row in identity_map["records"]}
    canonical_lookup = defaultdict(list)
    alias_lookup = defaultdict(list)
    owner_school_lookup = defaultdict(list)
    for card in masters:
        canonical_lookup[folded(card.get("name"))].append(card)
        for alias in aliases_from_master(card):
            alias_lookup[folded(alias)].append(card)
        if explicit_school_bag(card.get("name")):
            owner = bag_owner(card.get("name")) or folded(owner_from_list(
                list_by_id.get(card.get("idList"), {}).get("name") or card.get("list_name")
            ))
            if owner:
                owner_school_lookup[owner].append(card)

    def resolve_manual(row):
        linked = [masters_by_url[url.casefold()] for url in row["urls"] if url.casefold() in masters_by_url]
        if len(linked) == 1:
            return linked, "existing_master_url", None
        if len(linked) > 1:
            return linked, "conflict_multiple_master_urls", None
        core = folded(strip_technical_wrappers(row["text"]))
        exact = canonical_lookup.get(core, []) or alias_lookup.get(core, [])
        if len(exact) == 1:
            return exact, "canonical_or_alias", None
        prefix = []
        for name, cards in list(canonical_lookup.items()) + list(alias_lookup.items()):
            if core == name or re.match(rf"^{re.escape(name)}(?:\s+(?:-|nadv|z\b|v\b|pri\b|z\s+\d))", core):
                prefix.extend(cards)
        prefix = list({card["id"]: card for card in prefix}.values())
        if len(prefix) == 1:
            return prefix, "canonical_or_alias_prefix", None
        if bag_type(row["text"]):
            owner = bag_owner(row["text"])
            owner_cards = owner_school_lookup.get(owner, []) if owner else []
            if len(owner_cards) == 1:
                return owner_cards, "owner_plus_school_bag_type", None
            if owner and not owner_cards:
                canonical = {
                    "alex": "Alexova školská taška", "bety": "Betina školská taška",
                    "kiko": "Kikova školská taška", "veronika": "Veronikina školská taška",
                    "dogy": "Dogyho školská taška",
                }.get(owner)
                return [], "create_confirmed_owner_school_bag", canonical
            if len(owner_cards) > 1:
                return owner_cards, "conflict_duplicate_owner_school_bag_masters", None
        return [], "conflict_unresolved_identity", None

    manual_n = []
    automated_n_excluded = []
    for row in all_rows:
        if not (row["scene_id"].startswith("01/") or row["scene_id"].startswith("02/")):
            continue
        status = _manual_n_status(row, old_by_item.get(row["item_id"]))
        if status in {"new_item_after_identity_map", "n_added_after_identity_map"}:
            if known_automated_n(row["text"]):
                automated_n_excluded.append({"scene_id": row["scene_id"], "item_id": row["item_id"],
                                             "identity_core": strip_technical_wrappers(row["text"])})
                continue
            linked, resolution, create_name = resolve_manual(row)
            manual_n.append({
                **{key: row[key] for key in ("scene_id", "scene_url", "card_id", "checklist_id", "item_id", "text", "state", "pos", "urls", "has_z", "text_sha256")},
                "status": status,
                "identity_core": strip_technical_wrappers(row["text"]),
                "linked_masters": [{"id": card["id"], "name": card.get("name"),
                                    "url": card.get("shortUrl"), "closed": card.get("closed"),
                                    "idLabels": card.get("idLabels", [])} for card in linked],
                "resolution": resolution, "create_name": create_name,
            })

    labels = exact_named(state["labels"], CONTINUITY_LABEL)
    safe_manual_resolutions = {
        "existing_master_url", "canonical_or_alias", "canonical_or_alias_prefix",
        "owner_plus_school_bag_type", "create_confirmed_owner_school_bag",
    }
    manual_n_planned = [row for row in manual_n if row["resolution"] in safe_manual_resolutions]
    z_rows = [row for row in all_rows if row["has_z"]]
    return {
        "status": "read-only-dry-run", "writes": 0,
        "board": state["board"],
        "counts": {
            "production_scene_cards": len(scene_cards), "source_scene_ids": len(source_ids),
            "extra_scene_ids": len(set(scene_cards) - source_ids), "collisions": len(collisions),
            "old_descriptions": len(old_description_cards),
            "description_updates": len(description_ops), "description_conflicts": len(description_conflicts),
            "prop_items": len(all_rows), "protected_z_items": len(z_rows),
            "bag_occurrences": len(bag_occurrences), "bag_master_candidates": len(bag_master_candidates),
            "bag_duplicate_groups": len(bag_duplicate_groups), "bag_conflicts": len(bag_conflicts),
            "manual_n_new_or_changed_ep01_02": len(manual_n),
            "known_automated_n_excluded": len(automated_n_excluded),
            "manual_n_with_existing_master": len(manual_n_planned),
            "manual_n_conflicts": len(manual_n) - len(manual_n_planned),
        },
        "production_lists": sorted({card.get("list_name") for card in scene_cards.values()}),
        "extra_scene_ids": sorted(set(scene_cards) - source_ids), "collisions": collisions,
        "old_description_cards": old_description_cards,
        "description_conflicts": description_conflicts,
        "description_ops": description_ops,
        "bag_occurrences": bag_occurrences,
        "bag_master_candidates": bag_master_candidates,
        "bag_duplicate_groups": bag_duplicate_groups, "bag_conflicts": bag_conflicts,
        "manual_n": manual_n,
        "known_automated_n_excluded": automated_n_excluded,
        "continuity_label_matches": [{"id": row["id"], "name": row.get("name")} for row in labels],
        "protected_z": [{"scene_id": row["scene_id"], "item_id": row["item_id"],
                         "text": row["text"], "sha256": row["text_sha256"]} for row in z_rows],
        "planned": {
            "description_writes": len(description_ops),
            "bag_identity_writes": 0,
            "manual_n_master_label_or_block_writes": len(manual_n_planned),
            "todo_writes": 0, "microsoft_todo_writes": 0, "due_writes": 0,
        },
        "_state": state, "_scene_cards": scene_cards, "_masters": masters,
    }


def public(audit, details=False):
    hidden = {"_state", "_scene_cards", "_masters"}
    if not details:
        hidden |= {"description_ops", "protected_z"}
    return {key: value for key, value in audit.items() if key not in hidden}


def register_routes(app, api):
    @app.route("/api/ck-followup-20260820", methods=["POST"])
    def ck_followup_20260820():
        if ENDPOINT_DISABLED:
            return jsonify({"error": "completed follow-up endpoint disabled"}), 410
        if request.headers.get("X-CK-Followup-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "dry-run").casefold()
        if mode not in {"audit", "dry-run"}:
            return jsonify({"error": "read-only phase; apply is disabled", "writes": 0}), 405
        try:
            return jsonify(public(build_audit(api), request.args.get("details") == "1")), 200
        except Exception as exc:
            app.logger.exception("Cierny Kamen follow-up audit failed")
            return jsonify({"status": "failed", "writes": 0,
                            "error": f"{type(exc).__name__}: {exc}"}), 502
