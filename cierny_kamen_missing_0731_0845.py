from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from flask import jsonify, request

from cierny_kamen_ep07_10_import import (
    BOARD_REF,
    CHECKLIST_NAMES,
    IDENTITY_PATH,
    PAYLOAD_PATH,
    SPACE_MAP_PATH,
    exact_named,
    folded,
    registry_card_candidates,
    runtime_state,
)


KEY = "ck-missing-0731-0845-24aug-72f9c3e1"
ENDPOINT_DISABLED = False
TARGET_IDS = ("07/31", "07/32", "07/36", "08/45")
SOURCE_HASHES = {
    "07": "09ede7bfbd8ecb641b18f20a805dc3ff87c4ebff546ca2071ae48ca8288742a3",
    "08": "a23c5f37f372113b0b484909bd8deabb05860a58fc8dab99f5f16db9d9893823",
}
EXCLUDED_LIST_FRAGMENTS = (
    "original screener", "register", "rekvizity", "nadvazne sety",
    "todo", "os. rekvizity", "auta",
)


def _target_payload():
    payload = json.loads(PAYLOAD_PATH.read_text(encoding="utf-8"))
    by_id = {scene["scene_id"]: scene for scene in payload["scenes"]}
    return payload, [copy.deepcopy(by_id[scene_id]) for scene_id in TARGET_IDS]


def _production_groups(api, state):
    groups = defaultdict(list)
    for card in state["cards"]:
        list_name = state["lists_by_id"].get(card.get("idList"), {}).get("name", "")
        list_fold = folded(list_name)
        if any(fragment in list_fold for fragment in EXCLUDED_LIST_FRAGMENTS):
            continue
        info = api["cierny_kamen_scene_name_info"](card.get("name", ""))
        if info and not info.get("test"):
            groups[info["scene_id"]].append({**card, "list_name": list_name})
    return dict(groups)


def _supplement_required_lists(api, state):
    wanted = {
        "SCENÁRE", "REGISTER REKVIZÍT", "REGISTER PRIESTOROV", "AUTÁ",
        "KIKO – OS. REKVIZITY", "VERONIKA – OS. REKVIZITY",
        "SOFIA – OS. REKVIZITY",
    }
    cards = {card["id"]: card for card in state["cards"]}
    for item in state["lists"]:
        if item.get("closed") or not any(folded(item.get("name")) == folded(name) for name in wanted):
            continue
        for card in api["trello_get"](f"/lists/{item['id']}/cards", {
            "fields": "id,name,desc,idList,shortUrl,closed,idLabels,pos",
            "filter": "open", "limit": 1000,
        }):
            cards[card["id"]] = card
    state["cards"] = list(cards.values())


def _archived_and_variant_matches(api, state):
    rows = defaultdict(dict)
    for scene_id in TARGET_IDS:
        for query in (scene_id, scene_id.replace("/", " / ")):
            result = api["trello_get"]("/search", {
                "query": query, "idBoards": state["board"]["id"],
                "modelTypes": "cards", "cards_limit": 100,
                "card_fields": "id,name,desc,idList,shortUrl,closed,idLabels,pos",
            })
            for card in result.get("cards", []):
                info = api["cierny_kamen_scene_name_info"](card.get("name", ""))
                if not info:
                    continue
                candidate = info["scene_id"]
                if candidate == scene_id or candidate.startswith(scene_id) or scene_id.startswith(candidate):
                    rows[scene_id][card["id"]] = {
                        "id": card["id"], "name": card.get("name"),
                        "url": card.get("shortUrl"), "closed": card.get("closed"),
                        "list": state["lists_by_id"].get(card.get("idList"), {}).get("name"),
                        "parsed_scene_id": candidate,
                    }
    return {key: list(value.values()) for key, value in rows.items()}


def _records_for_targets():
    identity_map = json.loads(IDENTITY_PATH.read_text(encoding="utf-8"))
    records = [copy.deepcopy(row) for row in identity_map["records"] if row["scene_id"] in TARGET_IDS]
    additions = [
        {
            "scene_id": "07/32", "stable_name": "Čas 21:50 na Kikovom mobile",
            "owner": None, "categories": ["Screen"], "continuity_group": None,
            "action": "na obrazovke Kikovho mobilu je zobrazený čas 21:50",
            "current_state": "zobrazuje čas 21:50", "previous": None, "next": None,
            "physical_presence": True,
        },
        {
            "scene_id": "07/36", "stable_name": "Veronikina platobná karta",
            "owner": "VERONIKA", "categories": ["Osobná rekvizita"],
            "continuity_group": None,
            "action": "Veronika ju prikladá k terminálu a platba je zamietnutá",
            "current_state": "platba kartou je zamietnutá", "previous": None, "next": None,
            "physical_presence": True,
        },
    ]
    existing = {(row["scene_id"], folded(row["stable_name"])) for row in records}
    records.extend(row for row in additions if (row["scene_id"], folded(row["stable_name"])) not in existing)
    return records


def _target_list_name(record):
    if "Auto" in record.get("categories", []):
        return "AUTÁ"
    owner = record.get("owner")
    return f"{owner} – OS. REKVIZITY" if owner else "REGISTER REKVIZÍT"


def _prop_plan(state, records):
    allowed_ids = {
        item["id"] for item in state["lists"] if not item.get("closed")
        and ("rekvizit" in folded(item.get("name")) or folded(item.get("name")) == "auta")
    }
    rows = []
    for record in records:
        matches = registry_card_candidates(state["cards"], allowed_ids, record["stable_name"])
        rows.append({
            "scene_id": record["scene_id"], "stable_name": record["stable_name"],
            "target_list": _target_list_name(record),
            "categories": record.get("categories", []),
            "continuity": bool(record.get("continuity_group")),
            "status": "reuse" if len(matches) == 1 else "create" if not matches else "conflict",
            "matches": [{"id": card["id"], "name": card["name"], "url": card.get("shortUrl"),
                         "list": state["lists_by_id"].get(card.get("idList"), {}).get("name")}
                        for card in matches],
        })
    return rows


def _space_plan(state, scenes):
    space_map = json.loads(SPACE_MAP_PATH.read_text(encoding="utf-8"))
    lists = exact_named(state["lists"], "REGISTER PRIESTOROV")
    cards = [card for card in state["cards"] if lists and card.get("idList") == lists[0]["id"]]
    rows = []
    for scene in scenes:
        names = space_map.get(scene["location"], [scene["location"]])
        for name in names:
            matches = [card for card in cards if folded(name) in {
                folded(card.get("name")), *[folded(value) for value in re.findall(
                    r"(?mi)^(?:KANONICKÝ NÁZOV|ALIASY):\s*(.+)$", card.get("desc") or "")]
            }]
            rows.append({
                "scene_id": scene["scene_id"], "source_location": scene["location"],
                "canonical": name,
                "status": "matched" if len(matches) == 1 else "missing" if not matches else "conflict",
                "matches": [{"id": card["id"], "name": card["name"], "url": card.get("shortUrl")} for card in matches],
            })
    return rows


def build_audit(api):
    payload, scenes = _target_payload()
    state = runtime_state(api)
    _supplement_required_lists(api, state)
    groups = _production_groups(api, state)
    variants = _archived_and_variant_matches(api, state)
    records = _records_for_targets()
    props = _prop_plan(state, records)
    spaces = _space_plan(state, scenes)
    blockers = []
    source_hashes = {row["scene_id"]: row.get("source_sha256", "").casefold() for row in scenes}
    for scene in scenes:
        expected = SOURCE_HASHES[scene["scene_id"].split("/", 1)[0]]
        if source_hashes[scene["scene_id"]] != expected:
            blockers.append(f"{scene['scene_id']} source hash mismatch")
        if groups.get(scene["scene_id"]):
            blockers.append(f"{scene['scene_id']} already exists in production")
        external = [row for row in variants.get(scene["scene_id"], [])
                    if "original screener" not in folded(row.get("list"))]
        if external:
            blockers.append(f"{scene['scene_id']} open/archive variant exists")
    if len(exact_named(state["lists"], "SCENÁRE")) != 1:
        blockers.append("SCENÁRE target list missing or ambiguous")
    for row in spaces:
        if row["status"] != "matched":
            blockers.append(f"space {row['canonical']} {row['status']}")
    for row in props:
        if row["status"] == "conflict":
            blockers.append(f"prop {row['stable_name']} has duplicate masters")
        if len(exact_named(state["lists"], row["target_list"])) != 1:
            blockers.append(f"prop target list {row['target_list']} missing or ambiguous")
    labels_needed = sorted({category for row in records for category in row.get("categories", [])})
    label_rows = {name: exact_named(state["labels"], name) for name in labels_needed}
    for name, matches in label_rows.items():
        if len(matches) != 1:
            blockers.append(f"label {name} missing or ambiguous")
    swallowed = []
    all_scenes = payload["scenes"]
    by_id = {scene["scene_id"]: scene for scene in all_scenes}
    for target in scenes:
        index = all_scenes.index(by_id[target["scene_id"]])
        for neighbor in all_scenes[max(0, index - 1):index] + all_scenes[index + 1:index + 2]:
            for card in groups.get(neighbor["scene_id"], []):
                action_probe = re.sub(r"[*_#]", "", target.get("action_markdown") or "")[:80]
                if action_probe and action_probe in re.sub(r"[*_#]", "", card.get("desc") or ""):
                    swallowed.append({"target": target["scene_id"], "neighbor": neighbor["scene_id"], "url": card.get("shortUrl")})
                    blockers.append(f"{target['scene_id']} content appears swallowed by {neighbor['scene_id']}")
    existing_content = {}
    scene_by_id = {row["scene_id"]: row for row in scenes}
    for scene_id in TARGET_IDS:
        cards = groups.get(scene_id, [])
        if len(cards) != 1:
            continue
        card = cards[0]
        checklists = sorted(api["trello_get"](f"/cards/{card['id']}/checklists", {
            "checkItems": "all", "fields": "id,name,pos",
        }), key=lambda row: row.get("pos", 0))
        desc = card.get("desc") or ""
        source = scene_by_id[scene_id]
        existing_content[scene_id] = {
            "url": card.get("shortUrl"), "list": card.get("list_name"),
            "exact_card_name": card.get("name") == source.get("name"),
            "description_chars": len(desc),
            "description_sha256": hashlib.sha256(desc.encode("utf-8")).hexdigest(),
            "exact_action_present": source.get("action_markdown") in desc,
            "exact_title_present": f"## {source.get('prepis')}" in desc,
            "metadata_present": desc.count("<!-- CIERNY-KAMEN-SCHEDULE-METADATA:START -->") == 1,
            "simplified_description": all(marker in desc for marker in (
                "## NAVIGÁCIA", "## RUČNÉ DOPLNENIA", "## AKCIA A DIALÓGY",
            )) and not any(marker in desc for marker in (
                "REKVIZITY V KONTEXTE", "NADVAZNOSŤ", "### ODKAZY",
                "KONTINUITA PRIESTORU", "KONTINUITA POSTÁV",
            )),
            "checklist_names": [row.get("name") for row in checklists],
            "checklist_item_counts": {row.get("name"): len(row.get("checkItems", [])) for row in checklists},
            "prop_items": [item.get("name") for row in checklists if folded(row.get("name")) == "rekvizity"
                           for item in sorted(row.get("checkItems", []), key=lambda value: value.get("pos", 0))],
            "set_items": [item.get("name") for row in checklists if folded(row.get("name")) == "set"
                          for item in sorted(row.get("checkItems", []), key=lambda value: value.get("pos", 0))],
        }
    return {
        "status": "read-only-dry-run", "writes": 0, "board": state["board"],
        "target_ids": list(TARGET_IDS), "source_count": len(scenes),
        "source": [{"scene_id": row["scene_id"], "name": row["name"], "prepis": row["prepis"],
                    "source_pdf": row["source_pdf"], "source_page": row.get("source_page"),
                    "action_sha256": row.get("action_sha256")} for row in scenes],
        "production_matches": {sid: [{"name": c["name"], "url": c.get("shortUrl"), "list": c["list_name"]}
                                    for c in groups.get(sid, [])] for sid in TARGET_IDS},
        "open_archived_variants": variants, "swallowed_content": swallowed,
        "existing_content": existing_content,
        "spaces": spaces, "props": props,
        "planned": {"create_scenes": sum(not groups.get(sid) for sid in TARGET_IDS),
                    "create_prop_masters": sum(row["status"] == "create" for row in props),
                    "reuse_prop_masters": sum(row["status"] == "reuse" for row in props),
                    "create_checklists": sum(not groups.get(sid) for sid in TARGET_IDS) * len(CHECKLIST_NAMES),
                    "todo_writes": 0, "microsoft_todo_writes": 0},
        "labels": {name: [{"id": row["id"], "name": row["name"]} for row in matches]
                   for name, matches in label_rows.items()},
        "blockers": blockers,
        "protected_policy": "create-only scenes; existing cards are read-only except later explicit automatic navigation links; [z] is untouched",
        "_state": state, "_groups": groups, "_scenes": scenes, "_records": records,
    }


def public(audit):
    return {key: value for key, value in audit.items() if not key.startswith("_")}


def register_routes(app, api):
    @app.route("/api/cierny-kamen-missing-0731-0845", methods=["POST"])
    def cierny_kamen_missing_0731_0845():
        if ENDPOINT_DISABLED:
            return jsonify({"status": "disabled"}), 410
        if request.headers.get("X-CK-Missing-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "dry-run").casefold()
        if mode not in {"dry-run", "audit"}:
            return jsonify({"error": "apply not enabled before reviewed dry-run", "writes": 0}), 409
        try:
            audit = build_audit(api)
            return jsonify(public(audit)), 200 if not audit["blockers"] else 409
        except Exception as exc:
            app.logger.exception("missing CK scene audit failed")
            return jsonify({"status": "failed", "writes": 0,
                            "error": f"{type(exc).__name__}: {exc}"}), 502
