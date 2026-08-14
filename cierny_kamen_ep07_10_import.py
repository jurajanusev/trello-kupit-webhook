from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
import json

from flask import jsonify, request


KEY = "cierny-kamen-ep07-10-12aug-8d5a31c7"
BOARD_REF = "CzuD55PR"
PAYLOAD_PATH = Path(__file__).with_name("cierny_kamen_ep07_10_scenes.json")
IDENTITY_PATH = Path(__file__).with_name("cierny_kamen_ep07_10_identity_map.json")
SPACE_MAP_PATH = Path(__file__).with_name("cierny_kamen_ep07_10_space_map.json")
SPACE_LIST = "REGISTER PRIESTOROV"
SET_LIST = "NADVÄZNÉ SETY"
PROP_LIST = "REGISTER REKVIZÍT"


def folded(value):
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", value).strip().casefold()


def exact_named(items, name):
    target = folded(name)
    return [item for item in items if folded(item.get("name")) == target and not item.get("closed")]


def registry_aliases(card):
    values = {card.get("name", "")}
    desc = card.get("desc") or ""
    for label in ("KANONICKÝ NÁZOV", "ALIASY"):
        for match in re.finditer(rf"(?mi)^{label}:\s*(.+)$", desc):
            values.update(part.strip() for part in match.group(1).split(",") if part.strip() not in {"—", "-"})
    return {folded(value) for value in values if value}


def scene_summary(scene):
    return {
        "scene_id": scene["scene_id"], "name": scene["name"],
        "prepis": scene["prepis"], "location": scene["location"],
        "characters": scene["characters"], "source_page": scene["source_page"],
        "source_pdf": scene["source_pdf"], "action_sha256": scene["action_sha256"],
    }


def build_audit(api):
    payload = json.loads(PAYLOAD_PATH.read_text(encoding="utf-8"))
    identity_map = json.loads(IDENTITY_PATH.read_text(encoding="utf-8"))
    space_map = json.loads(SPACE_MAP_PATH.read_text(encoding="utf-8"))
    board = api["trello_get"](f"/boards/{BOARD_REF}", {"fields": "id,name,url,closed"})
    lists = api["trello_get"](f"/boards/{board['id']}/lists", {
        "fields": "id,name,pos,closed", "filter": "all",
    })
    labels = api["trello_get"](f"/boards/{board['id']}/labels", {
        "fields": "id,name,color", "limit": 1000,
    })
    cards = api["trello_get"](f"/boards/{board['id']}/cards", {
        "fields": "id,name,desc,idList,shortUrl,closed,idLabels,dateLastActivity",
        "filter": "all", "limit": 1000,
    })
    groups = defaultdict(list)
    for card in cards:
        info = api["cierny_kamen_scene_name_info"](card.get("name", ""))
        if info and not info.get("test"):
            groups[info["scene_id"]].append(card)
    source_ids = [scene["scene_id"] for scene in payload["scenes"]]
    source_set = set(source_ids)
    collisions = {
        sid: [{"name": c["name"], "url": c["shortUrl"], "closed": c["closed"]} for c in groups[sid]]
        for sid in source_ids if len(groups.get(sid, [])) > 1
    }
    existing = {sid: groups[sid][0] for sid in source_ids if len(groups.get(sid, [])) == 1}
    scene_lists = exact_named(lists, "SCENÁRE")
    space_lists = exact_named(lists, SPACE_LIST)
    set_lists = exact_named(lists, SET_LIST)
    prop_lists = exact_named(lists, PROP_LIST)
    personal_lists = sorted([
        item for item in lists if not item.get("closed") and folded(item.get("name")).endswith(" - os. rekvizity")
    ], key=lambda item: folded(item["name"]))
    space_cards = [card for card in cards if space_lists and card.get("idList") == space_lists[0]["id"] and not card.get("closed")]
    alias_index = defaultdict(list)
    for card in space_cards:
        for alias in registry_aliases(card):
            alias_index[alias].append(card)
    location_rows = []
    for location, count in sorted(Counter(scene["location"] for scene in payload["scenes"]).items(), key=lambda row: folded(row[0])):
        canonical_names = space_map.get(location, [location])
        targets = []
        for canonical_name in canonical_names:
            matches = alias_index.get(folded(canonical_name), [])
            targets.append({
                "canonical": canonical_name,
                "status": "matched" if len(matches) == 1 else "new" if not matches else "ambiguous",
                "matches": [{"name": c["name"], "url": c["shortUrl"]} for c in matches],
            })
        statuses = {target["status"] for target in targets}
        status = "ambiguous" if "ambiguous" in statuses else "new" if "new" in statuses else "matched"
        location_rows.append({
            "source": location, "scene_count": count, "status": status,
            "targets": targets,
        })
    ambiguous_locations = [row for row in location_rows if row["status"] == "ambiguous"]
    new_locations = [row for row in location_rows if row["status"] == "new"]
    blockers = []
    for name, found in (("SCENÁRE", scene_lists), (SPACE_LIST, space_lists), (SET_LIST, set_lists), (PROP_LIST, prop_lists)):
        if len(found) != 1:
            blockers.append(f"expected one open {name} list; found {len(found)}")
    if collisions:
        blockers.append("source scene ID collisions")
    if ambiguous_locations:
        blockers.append("ambiguous space aliases")
    required_labels = (
        "Auto", "Osobná rekvizita", "Dokument", "Screen",
        "Nadväzná rekvizita", "Nadväzný priestor", "Nadväzný set",
    )
    label_audit = {
        name: [{"id": item["id"], "name": item["name"], "color": item.get("color")} for item in exact_named(labels, name)]
        for name in required_labels
    }
    missing_labels = [name for name, found in label_audit.items() if not found]
    duplicate_labels = [name for name, found in label_audit.items() if len(found) > 1]
    if missing_labels or duplicate_labels:
        blockers.append("required label mismatch")
    return {
        "status": "read-only-dry-run", "writes": 0,
        "board": board, "blockers": blockers,
        "sources": payload["source_pdfs"], "episode_counts": payload["episode_counts"],
        "source_scene_count": len(source_ids), "unique_source_ids": len(source_set),
        "all_source_ids": source_ids,
        "trello_scene_cards_all": sum(1 for values in groups.values() if len(values) == 1),
        "trello_unique_scene_ids_all": len(groups),
        "create": [scene_summary(scene) for scene in payload["scenes"] if scene["scene_id"] not in existing],
        "update": [scene_summary(scene) for scene in payload["scenes"] if scene["scene_id"] in existing],
        "unchanged": [], "conflicts": collisions,
        "lists": {
            "scene": scene_lists, "space_registry": space_lists,
            "set_continuity": set_lists, "prop_registry": prop_lists,
            "personal_prop_lists": [{"id": item["id"], "name": item["name"]} for item in personal_lists],
        },
        "labels": label_audit, "missing_labels": missing_labels,
        "duplicate_labels": duplicate_labels,
        "locations": {
            "unique": len(location_rows),
            "matched": sum(row["status"] == "matched" for row in location_rows),
            "new": new_locations, "ambiguous": ambiguous_locations,
            "all": location_rows,
        },
        "registry_counts": {
            "space_cards": len(space_cards),
            "set_cards": sum(1 for card in cards if set_lists and card.get("idList") == set_lists[0]["id"] and not card.get("closed")),
            "global_prop_cards": sum(1 for card in cards if prop_lists and card.get("idList") == prop_lists[0]["id"] and not card.get("closed")),
            "personal_prop_cards": sum(1 for card in cards if card.get("idList") in {item["id"] for item in personal_lists} and not card.get("closed")),
        },
        "manual_protection": {
            "existing_source_cards": len(existing),
            "policy": "create-only while all ep07-10 IDs are absent; any existing ID is a conflict and is not written",
        },
        "semantic_plan": {
            "status": "explicit reviewed identity map loaded",
            "prop_items": identity_map["record_count"],
            "scenes_with_props": identity_map["scene_count_with_props"],
            "unique_prop_identities": len({record["stable_name"] for record in identity_map["records"]}),
            "continuity_groups": len({record["continuity_group"] for record in identity_map["records"] if record["continuity_group"]}),
            "category_counts": dict(Counter(category for record in identity_map["records"] for category in record["categories"])),
            "questions": identity_map["questions"],
            "set_continuity_items": 0,
            "set_continuity_note": "No explicit cross-scene physical set-state chain was confirmed in the four PDFs; ordinary repeated locations are not labelled.",
            "note": "No generic keyword classifier is used as authority.",
        },
    }


def register_routes(app, api):
    @app.route("/api/cierny-kamen-ep07-10", methods=["POST"])
    def cierny_kamen_ep07_10():
        if request.headers.get("X-CK-Ep07-10-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "dry-run").casefold().strip()
        if mode not in {"audit", "dry-run"}:
            return jsonify({"error": "only read-only audit/dry-run is enabled"}), 409
        audit = build_audit(api)
        return jsonify(audit), 200 if not audit["blockers"] else 409
