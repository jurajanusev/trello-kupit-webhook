from __future__ import annotations

import re
import unicodedata
import hashlib
from collections import Counter, defaultdict
from pathlib import Path
import json

from flask import jsonify, request

from cierny_kamen_all_props_registry import (
    PROP_AUTO_END, PROP_AUTO_START, ensure_attachment,
)
from cierny_kamen_spaces_props import (
    SPACE_AUTO_END, SPACE_AUTO_START, replace_space_auto_block, space_marker,
)


KEY = "cierny-kamen-ep07-10-12aug-8d5a31c7"
BOARD_REF = "CzuD55PR"
PAYLOAD_PATH = Path(__file__).with_name("cierny_kamen_ep07_10_scenes.json")
IDENTITY_PATH = Path(__file__).with_name("cierny_kamen_ep07_10_identity_map.json")
SPACE_MAP_PATH = Path(__file__).with_name("cierny_kamen_ep07_10_space_map.json")
SPACE_LIST = "REGISTER PRIESTOROV"
SET_LIST = "NADVÄZNÉ SETY"
PROP_LIST = "REGISTER REKVIZÍT"
SAMPLE_SCENES = ("07/01LP", "08/07FLASH", "09/35", "10/11")
CATEGORY_LABELS = (
    "Auto", "Osobná rekvizita", "Dokument", "Screen",
    "Nadväzná rekvizita", "Nadväzný priestor", "Nadväzný set",
)


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


def replace_auto_block(actual, start_marker, end_marker, desired_block):
    actual = actual or ""
    if start_marker in actual and end_marker in actual:
        start = actual.index(start_marker)
        end = actual.index(end_marker, start) + len(end_marker)
        return actual[:start] + desired_block + actual[end:]
    return (actual.rstrip() + "\n\n" + desired_block).lstrip("\n")


def prop_registry_block(name, categories, occurrences=None):
    links = occurrences or ["- Odkazy sa doplnia po vytvorení obrazových kariet."]
    return (
        f"{PROP_AUTO_START}\n"
        f"KANONICKÝ NÁZOV: {name}\n"
        "ALIASY: —\n"
        f"KATEGÓRIE: {', '.join(sorted(categories, key=folded)) or '—'}\n\n"
        "### VÝSKYTY V OBRAZOCH\n"
        f"{chr(10).join(links)}\n"
        f"{PROP_AUTO_END}"
    )


def space_registry_description(name):
    block = (
        f"{SPACE_AUTO_START}\n"
        "# REGISTER PRIESTORU\n\n"
        f"**KANONICKÝ NÁZOV:** {name}\n\n"
        "**ALIASY:** —\n\n"
        "**NADRADENÝ PRIESTOR:** —\n\n"
        "**PODPRIESTORY:** —\n\n"
        "**INT/EXT:** NEURČENÉ\n\n"
        "**ZÁKLADNÝ VZHĽAD/DRESSING:** Doplní sa z autoritatívnych scén; ručné poznámky, fotografie a pôdorysy sú chránené.\n\n"
        "## ODKAZY NA OBRAZOVÉ KARTY\n"
        "- Odkazy sa doplnia po vytvorení obrazových kariet.\n\n"
        "## ČASOVÁ OS ŠPECIFICKÝCH ZMIEN\n"
        "- Bez potvrdenej špecifickej zmeny stavu priestoru.\n"
        f"{SPACE_AUTO_END}"
    )
    key = re.sub(r"[^a-z0-9]+", "-", folded(name)).strip("-")
    return (
        f"{space_marker(key)}\n{block}\n\n"
        "## NATÁČACIA LOKÁCIA (RUČNE)\n\n"
        "## RUČNÉ POZNÁMKY / FOTKY / PÔDORYSY\n"
    )


def identity_groups(identity_map):
    groups = defaultdict(list)
    for record in identity_map["records"]:
        if not record.get("physical_presence", True):
            continue
        groups[record["stable_name"]].append(record)
    return groups


def registry_card_candidates(cards, allowed_list_ids, name):
    target = folded(name)
    return [
        card for card in cards
        if card.get("idList") in allowed_list_ids
        and target in registry_aliases(card)
    ]


def owner_list_name(owner):
    return f"{owner} – OS. REKVIZITY" if owner else PROP_LIST


def registry_plan(state, identity_map, scene_filter=None):
    groups = identity_groups(identity_map)
    if scene_filter:
        groups = {
            name: [record for record in records if record["scene_id"] in scene_filter]
            for name, records in groups.items()
            if any(record["scene_id"] in scene_filter for record in records)
        }
    prop_lists = exact_named(state["lists"], PROP_LIST)
    personal_lists = [
        item for item in state["lists"]
        if not item.get("closed") and folded(item.get("name")).endswith(" - os. rekvizity")
    ]
    allowed_ids = {item["id"] for item in [*prop_lists, *personal_lists]}
    rows = []
    for name, records in sorted(groups.items(), key=lambda item: folded(item[0])):
        owners = {record.get("owner") for record in records if record.get("owner")}
        owner = next(iter(owners)) if len(owners) == 1 else None
        target_list = owner_list_name(owner)
        matches = registry_card_candidates(state["cards"], allowed_ids, name)
        rows.append({
            "name": name, "owner": owner, "target_list": target_list,
            "categories": sorted({category for record in records for category in record["categories"]}, key=folded),
            "scene_ids": sorted({record["scene_id"] for record in records}),
            "matches": [{"id": card["id"], "name": card["name"], "url": card.get("shortUrl"), "idList": card["idList"], "closed": card.get("closed")} for card in matches],
            "status": "reuse" if len(matches) == 1 else "create" if not matches else "conflict",
        })
    return rows


def canonical_space_names(payload, space_map, scene_filter=None):
    names = set()
    for scene in payload["scenes"]:
        if scene_filter and scene["scene_id"] not in scene_filter:
            continue
        names.update(space_map.get(scene["location"], [scene["location"]]))
    return sorted(names, key=folded)


def space_plan(state, payload, space_map, scene_filter=None):
    lists = exact_named(state["lists"], SPACE_LIST)
    cards = [card for card in state["cards"] if lists and card.get("idList") == lists[0]["id"]]
    rows = []
    for name in canonical_space_names(payload, space_map, scene_filter):
        matches = [card for card in cards if folded(name) in registry_aliases(card)]
        rows.append({
            "name": name,
            "matches": [{"id": card["id"], "name": card["name"], "url": card.get("shortUrl"), "closed": card.get("closed")} for card in matches],
            "status": "reuse" if len(matches) == 1 else "create" if not matches else "conflict",
        })
    return rows


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
    state = {"board": board, "lists": lists, "labels": labels, "cards": cards}
    prop_plan = registry_plan(state, identity_map)
    spaces_plan = space_plan(state, payload, space_map)
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
    if any(row["status"] == "conflict" for row in prop_plan):
        blockers.append("prop registry identity conflicts")
    if any(row["status"] == "conflict" for row in spaces_plan):
        blockers.append("space registry identity conflicts")
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
            "registry": {
                "reuse": sum(row["status"] == "reuse" for row in prop_plan),
                "create": sum(row["status"] == "create" for row in prop_plan),
                "conflict": [row for row in prop_plan if row["status"] == "conflict"],
                "sample": [row for row in prop_plan if set(row["scene_ids"]) & set(SAMPLE_SCENES)],
            },
            "space_registry": {
                "reuse": sum(row["status"] == "reuse" for row in spaces_plan),
                "create": sum(row["status"] == "create" for row in spaces_plan),
                "conflict": [row for row in spaces_plan if row["status"] == "conflict"],
            },
        },
    }


def register_routes(app, api):
    @app.route("/api/cierny-kamen-ep07-10", methods=["POST"])
    def cierny_kamen_ep07_10():
        if request.headers.get("X-CK-Ep07-10-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "dry-run").casefold().strip()
        allowed = {
            "audit", "dry-run", "sample-registry-init", "sample-space-init",
            "registry-init", "space-init",
        }
        if mode not in allowed:
            return jsonify({"error": "unsupported mode"}), 409
        audit = build_audit(api)
        if mode in {"audit", "dry-run"}:
            return jsonify(audit), 200 if not audit["blockers"] else 409
        if audit["blockers"]:
            return jsonify(audit), 409
        payload = json.loads(PAYLOAD_PATH.read_text(encoding="utf-8"))
        identity_map = json.loads(IDENTITY_PATH.read_text(encoding="utf-8"))
        space_map = json.loads(SPACE_MAP_PATH.read_text(encoding="utf-8"))
        state = api["cierny_kamen_import_state"]({
            "board_ref": BOARD_REF,
        })
        try:
            start = int(request.args.get("start", "0"))
            limit = int(request.args.get("limit", "5"))
        except ValueError:
            return jsonify({"error": "invalid start/limit"}), 400
        if start < 0 or limit < 1 or limit > 10:
            return jsonify({"error": "invalid start/limit"}), 400
        sample_only = mode.startswith("sample-")
        scene_filter = set(SAMPLE_SCENES) if sample_only else None
        if mode.endswith("registry-init"):
            rows = registry_plan(state, identity_map, scene_filter)
            selected = rows[start:start + limit]
            conflicts = [row for row in selected if row["status"] == "conflict"]
            if conflicts:
                return jsonify({"status": "blocked", "conflicts": conflicts}), 409
            label_by_name = {
                name: exact_named(state["labels"], name)[0]
                for name in CATEGORY_LABELS
            }
            created_lists = []
            created_cards = []
            unchanged = []
            for row in selected:
                if row["status"] == "reuse":
                    unchanged.append(row)
                    continue
                target_lists = exact_named(state["lists"], row["target_list"])
                if len(target_lists) > 1:
                    return jsonify({"status": "blocked", "target_list": row["target_list"]}), 409
                if not target_lists:
                    target = api["trello_post_body"]("/lists", {
                        "idBoard": state["board"]["id"], "name": row["target_list"], "pos": "bottom",
                    })
                    state["lists"].append(target)
                    created_lists.append({"name": target["name"], "id": target["id"]})
                else:
                    target = target_lists[0]
                labels_for_card = [label_by_name[name]["id"] for name in row["categories"]]
                card = api["trello_post_body"]("/cards", {
                    "idList": target["id"], "name": row["name"],
                    "desc": prop_registry_block(row["name"], row["categories"]),
                    "pos": "bottom", "idLabels": ",".join(labels_for_card),
                })
                created_cards.append({"name": row["name"], "id": card["id"], "url": card.get("shortUrl"), "list": target["name"]})
            return jsonify({
                "status": "applied", "mode": mode, "start": start,
                "selected": len(selected), "created_lists": created_lists,
                "created_cards": created_cards, "unchanged": len(unchanged),
                "writes": len(created_lists) + len(created_cards),
                "remaining": max(0, len(rows) - start - len(selected)),
            }), 200
        rows = space_plan(state, payload, space_map, scene_filter)
        selected = rows[start:start + limit]
        conflicts = [row for row in selected if row["status"] == "conflict"]
        if conflicts:
            return jsonify({"status": "blocked", "conflicts": conflicts}), 409
        space_lists = exact_named(state["lists"], SPACE_LIST)
        if len(space_lists) != 1:
            return jsonify({"status": "blocked", "space_lists": len(space_lists)}), 409
        created = []
        unchanged = []
        for row in selected:
            if row["status"] == "reuse":
                unchanged.append(row)
                continue
            card = api["trello_post_body"]("/cards", {
                "idList": space_lists[0]["id"], "name": row["name"],
                "desc": space_registry_description(row["name"]), "pos": "bottom",
            })
            created.append({"name": row["name"], "id": card["id"], "url": card.get("shortUrl")})
        return jsonify({
            "status": "applied", "mode": mode, "start": start,
            "selected": len(selected), "created": created,
            "unchanged": len(unchanged), "writes": len(created),
            "remaining": max(0, len(rows) - start - len(selected)),
        }), 200
