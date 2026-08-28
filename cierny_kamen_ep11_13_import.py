"""Read-only safety audit for authoritative Čierny Kameň episodes 11–13."""
from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

from flask import jsonify, request
from cierny_kamen_ep07_10_import import (
    CHECKLIST_NAMES, SPACE_LIST, PROP_LIST, apply_scene, card_map,
    combined_scenes, ensure_attachments, exact_named, folded,
    prop_registry_block, read_checklists, registry_aliases, runtime_state,
    scene_readback, space_registry_description,
)

KEY = "cierny-kamen-ep11-13-28aug-64d3f5a1"
BOARD_REF = "CzuD55PR"
PAYLOAD_PATH = Path(__file__).with_name("cierny_kamen_ep11_13_scenes.json")
MAP_PATH = Path(__file__).with_name("cierny_kamen_ep11_13_identity_space_map.json")
EXCLUDED = ("original screener", "register", "rekvizit", "nadvazne", "todo", "auta")
_WRITE_STATE_CACHE = {"state": None}


def scene_info(api, name):
    return api["cierny_kamen_scene_name_info"](name or "")


def is_scene_list(name):
    key = (name or "").casefold()
    return not any(item in key for item in EXCLUDED)


def load_sources():
    return (json.loads(PAYLOAD_PATH.read_text(encoding="utf-8")),
            json.loads(MAP_PATH.read_text(encoding="utf-8")))


def prop_groups(mapping):
    groups = defaultdict(list)
    for row in mapping["props"]:
        groups[row["stable_name"]].append(row)
    return groups


def target_prop_list(rows):
    categories = {value for row in rows for value in row["categories"]}
    owners = {row["owner"] for row in rows if row["owner"]}
    if "Auto" in categories:
        return "AUTÁ"
    if len(owners) == 1:
        return f"{next(iter(owners))} – OS. REKVIZITY"
    return PROP_LIST


def master_plans(state, payload, mapping):
    allowed_prop_ids = {item["id"] for item in state["lists"] if not item.get("closed") and (
        "rekvizit" in folded(item.get("name")) or folded(item.get("name")) == folded("AUTÁ")
    )}
    props = []
    for name, rows in sorted(prop_groups(mapping).items(), key=lambda item: folded(item[0])):
        matches = [card for card in state["cards"] if card.get("idList") in allowed_prop_ids and folded(name) in registry_aliases(card)]
        props.append({"name": name, "rows": rows, "categories": sorted({x for row in rows for x in row["categories"]}, key=folded),
                      "target_list": target_prop_list(rows), "matches": matches,
                      "status": "reuse" if len(matches) == 1 else "create" if not matches else "conflict"})
    space_lists = exact_named(state["lists"], SPACE_LIST)
    space_cards = [card for card in state["cards"] if space_lists and card.get("idList") == space_lists[0]["id"]]
    names = {}
    for entry in mapping["spaces_by_scene"].values():
        for name in entry["canonical_spaces"]:
            names.setdefault(folded(name), name)
    spaces = []
    for name in sorted(names.values(), key=folded):
        matches = [card for card in space_cards if folded(name) in registry_aliases(card)]
        spaces.append({"name": name, "matches": matches,
                       "status": "reuse" if len(matches) == 1 else "create" if not matches else "conflict"})
    return props, spaces


def audit(api):
    payload = json.loads(PAYLOAD_PATH.read_text(encoding="utf-8"))
    identity_space_map = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    board = api["trello_get"](f"/boards/{BOARD_REF}", {"fields": "id,name,url"})
    lists = api["trello_get"](f"/boards/{board['id']}/lists", {"fields": "id,name,closed", "filter": "all"})
    found = {}
    archived = {}
    for listing in lists:
        cards = api["trello_get"](f"/lists/{listing['id']}/cards", {"fields": "id,name,shortUrl,closed,idList", "filter": "all", "limit": 1000})
        for card in cards:
            info = scene_info(api, card.get("name"))
            if not info or info.get("test"):
                continue
            target = archived if listing.get("closed") or card.get("closed") else found
            target.setdefault(info["scene_id"], []).append({"name": card["name"], "url": card.get("shortUrl"), "list": listing["name"]})
    ids = [scene["scene_id"] for scene in payload["scenes"]]
    duplicates = {key: value for key, value in found.items() if len(value) > 1 and key in ids}
    existing = {key: value for key, value in found.items() if key in ids}
    missing = [key for key in ids if key not in found]
    mapped_ids = set(identity_space_map["spaces_by_scene"])
    source_ids = set(ids)
    map_errors = []
    if mapped_ids != source_ids:
        map_errors.append({"missing_space_maps": sorted(source_ids - mapped_ids),
                           "extra_space_maps": sorted(mapped_ids - source_ids)})
    prop_scene_errors = sorted({row["scene_id"] for row in identity_space_map["props"]} - source_ids)
    if prop_scene_errors:
        map_errors.append({"unknown_prop_scene_ids": prop_scene_errors})
    state = runtime_state(api)
    prop_plan, space_plan = master_plans(state, payload, identity_space_map)
    master_conflicts = ([{"type": "prop", "name": row["name"], "matches": len(row["matches"])} for row in prop_plan if row["status"] == "conflict"] +
                        [{"type": "space", "name": row["name"], "matches": len(row["matches"])} for row in space_plan if row["status"] == "conflict"])
    return {"status": "read-only-dry-run", "writes": 0, "board": board,
            "source_scenes": len(ids), "unique_source_ids": len(set(ids)),
            "existing": len(existing), "create": len(missing), "missing_ids": missing,
            "duplicates": duplicates, "archived_matches": {key: archived[key] for key in ids if key in archived},
            "excluded_lists": EXCLUDED, "source_stats": payload["stats"],
            "identity_space_map": {"version": identity_space_map["version"],
                                   "space_mappings": identity_space_map["space_mapping_count"],
                                   "prop_records": identity_space_map["prop_record_count"],
                                   "errors": map_errors},
            "prop_masters": {"reuse": sum(x["status"] == "reuse" for x in prop_plan),
                             "create": sum(x["status"] == "create" for x in prop_plan),
                             "conflicts": [x["name"] for x in prop_plan if x["status"] == "conflict"]},
            "space_masters": {"reuse": sum(x["status"] == "reuse" for x in space_plan),
                              "create": sum(x["status"] == "create" for x in space_plan),
                              "conflicts": [x["name"] for x in space_plan if x["status"] == "conflict"]},
            "blockers": [*map_errors, *master_conflicts]}


def resolve_master_maps(state, payload, mapping):
    prop_plan, space_plan = master_plans(state, payload, mapping)
    conflicts = [row["name"] for row in [*prop_plan, *space_plan] if row["status"] != "reuse"]
    if conflicts:
        raise ValueError(f"unresolved masters: {conflicts[:10]}")
    return ({row["name"]: row["matches"][0] for row in prop_plan},
            {row["name"]: row["matches"][0] for row in space_plan})


def display_link(scene, cards):
    if not scene or scene["scene_id"] not in cards:
        return "—"
    return f"[{scene['scene_id']} – {scene['prepis']}]({cards[scene['scene_id']]['shortUrl']})"


def desired_scene(scene, all_scenes, cards, prop_cards, space_cards, mapping):
    index = next(i for i, row in enumerate(all_scenes) if row["scene_id"] == scene["scene_id"])
    canonical_spaces = mapping["spaces_by_scene"][scene["scene_id"]]["canonical_spaces"]
    space_keys = {folded(x) for x in canonical_spaces}
    def same_space(row):
        entry = mapping["spaces_by_scene"].get(row["scene_id"])
        if entry:
            return bool(space_keys & {folded(x) for x in entry["canonical_spaces"]})
        return folded(row.get("location")) in space_keys
    previous_space = next((row for row in reversed(all_scenes[:index]) if same_space(row)), None)
    next_space = next((row for row in all_scenes[index + 1:] if same_space(row)), None)
    nav = ["### NAVIGÁCIA", "", "#### Rovnaký priestor",
           f"- Predchádzajúci: {display_link(previous_space, cards)}",
           f"- Nasledujúci: {display_link(next_space, cards)}", "", "#### Rovnaké postavy"]
    for character in scene.get("characters", []):
        key = folded(character)
        previous = next((row for row in reversed(all_scenes[:index]) if key in {folded(x) for x in row.get("characters", [])}), None)
        following = next((row for row in all_scenes[index + 1:] if key in {folded(x) for x in row.get("characters", [])}), None)
        nav.append(f"- {character}: ← {display_link(previous, cards)} | → {display_link(following, cards)}")
    location_value = ", ".join(f"[{name}]({space_cards[name]['shortUrl']})" for name in canonical_spaces)
    location_label = "LOKÁCIE" if len(canonical_spaces) > 1 else "LOKÁCIA"
    chars = scene.get("characters_raw") or "neuvedené"
    desc = (f"## {scene['prepis']}\n\n" + "\n".join(nav) +
            "\n\n### RUČNÉ DOPLNENIA\n\n### AKCIA A DIALÓGY\n" + scene["action_markdown"] +
            "\n\n<!-- CIERNY-KAMEN-SCHEDULE-METADATA:START -->\n"
            f"ČÍSLO OBRAZU: {scene['scene_id']}\nZDROJ: {scene['source_pdf']}\n"
            "NATÁČACÍ DEŇ: nenaplánované\nDÁTUM: nenaplánované\nPORADIE: nenaplánované\nUNIT: nenaplánované\n"
            f"{location_label}: {location_value}\nPOSTAVY: {chars}\n"
            "<!-- CIERNY-KAMEN-SCHEDULE-METADATA:END -->")
    records = [row for row in mapping["props"] if row["scene_id"] == scene["scene_id"]]
    prop_items = []
    questions = []
    for row in records:
        url = prop_cards[row["stable_name"]]["shortUrl"]
        if row["continuity_group"]:
            previous = row["previous"] or "prvý výskyt"
            following = row["next"] or "ďalší potvrdený obraz neurčený"
            prop_items.append(f"<n> **{row['stable_name']}** — *{row['current_state']} | ← {previous} | TU: {row['current_state']} | → {following}* | KARTA: {url}")
        else:
            prop_items.append(f"**{row['stable_name']}** — *{row['current_state']}* | KARTA: {url}")
        if row["ambiguity_question"]:
            questions.append(row["ambiguity_question"])
    set_items = [f"**{name}** — *prostredie obrazu {scene['scene_id']}* | KARTA: {space_cards[name]['shortUrl']}" for name in canonical_spaces]
    checklists = {"REKVIZITY": prop_items, "SET": set_items, "INFO Z PORADY": [],
                  "INFO Z NATÁČANIA": [], "OTÁZKY NA PORADU": list(dict.fromkeys(questions))}
    labels = {category for row in records for category in row["categories"] if category in {"Auto", "Nadväzná rekvizita"}}
    return desc, checklists, labels


def init_masters(api, state, payload, mapping, start, limit):
    prop_plan, space_plan = master_plans(state, payload, mapping)
    combined = [("prop", row) for row in prop_plan] + [("space", row) for row in space_plan]
    selected = combined[start:start + limit]
    labels = {folded(row["name"]): row for row in state["labels"]}
    results = []
    for kind, row in selected:
        if row["status"] == "conflict":
            raise ValueError(f"master conflict: {row['name']}")
        if row["status"] == "reuse":
            results.append({"type": kind, "name": row["name"], "created": False})
            continue
        list_name = row["target_list"] if kind == "prop" else SPACE_LIST
        targets = exact_named(state["lists"], list_name)
        if len(targets) > 1:
            raise ValueError(f"target list conflict: {list_name}")
        if not targets:
            target = api["trello_post_body"]("/lists", {"idBoard": state["board"]["id"], "name": list_name, "pos": "bottom"})
            state["lists"].append(target)
        else:
            target = targets[0]
        if kind == "prop":
            label_ids = [labels[folded(name)]["id"] for name in row["categories"] if folded(name) in labels]
            card = api["trello_post_body"]("/cards", {"idList": target["id"], "name": row["name"],
                    "desc": prop_registry_block(row["name"], row["categories"]), "pos": "bottom", "idLabels": ",".join(label_ids)})
        else:
            card = api["trello_post_body"]("/cards", {"idList": target["id"], "name": row["name"],
                    "desc": space_registry_description(row["name"]), "pos": "bottom"})
        results.append({"type": kind, "name": row["name"], "created": True, "url": card.get("shortUrl")})
    return {"selected": len(selected), "created": sum(x["created"] for x in results),
            "remaining": max(0, len(combined) - start - len(selected)), "results": results}


def apply_scene_new(api, state, scene, desired, label_ids, scene_list_id):
    desc, checklists, label_names = desired
    cards, collisions = card_map(api, state)
    if scene["scene_id"] in collisions:
        raise ValueError(f"scene collision: {scene['scene_id']}")
    card = cards.get(scene["scene_id"])
    created = False
    writes = 0
    if not card:
        card = api["trello_post_body"]("/cards", {"idList": scene_list_id, "name": scene["name"],
                "desc": desc, "pos": "bottom", "idLabels": ",".join(label_ids[folded(name)] for name in label_names)})
        state["cards"].append(card)
        created = True
        writes += 1
    else:
        if card.get("name") != scene["name"]:
            raise ValueError(f"existing name conflict: {scene['scene_id']}")
        if scene["source_pdf"] not in (card.get("desc") or ""):
            raise ValueError(f"protected existing description: {scene['scene_id']}")
        if card.get("desc") != desc:
            api["trello_put_body"](f"/cards/{card['id']}", {"desc": desc})
            card["desc"] = desc
            writes += 1
    actual = read_checklists(api, card["id"])
    projection = [(item["name"], [entry["name"] for entry in sorted(item.get("checkItems", []), key=lambda x: x.get("pos", 0))]) for item in actual]
    expected = [(name, checklists[name]) for name in CHECKLIST_NAMES]
    if actual and projection != expected:
        raise ValueError(f"existing checklist conflict: {scene['scene_id']}")
    if not actual:
        for position, name in enumerate(CHECKLIST_NAMES, 1):
            checklist = api["trello_post_body"](f"/cards/{card['id']}/checklists", {"name": name, "pos": position * 16384})
            writes += 1
            for item in checklists[name]:
                api["trello_post_body"](f"/checklists/{checklist['id']}/checkItems", {"name": item, "pos": "bottom"})
                writes += 1
    return card, writes, created


def register_routes(app, api):
    @app.route("/api/cierny-kamen-ep11-13", methods=["POST"])
    def endpoint():
        if request.headers.get("X-CK-Ep11-13-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "dry-run").casefold()
        allowed = {"dry-run", "audit", "master-init", "sample", "apply", "fill", "finalize", "final-audit"}
        if mode not in allowed:
            return jsonify({"error": "unsupported mode", "writes": 0}), 409
        if mode in {"dry-run", "audit"}:
            report = audit(api)
            return jsonify(report), 200 if not report["blockers"] else 409
        if mode == "final-audit":
            report = audit(api)
            return jsonify(report), 200 if not report["blockers"] and report["create"] == 0 and not report["duplicates"] else 409
        try:
            start = int(request.args.get("start", "0"))
            limit = int(request.args.get("limit", "5"))
        except ValueError:
            return jsonify({"error": "invalid start/limit"}), 400
        if start < 0 or limit < 1 or limit > 25:
            return jsonify({"error": "invalid start/limit"}), 400
        payload, mapping = load_sources()
        # Write batches operate only on the new ep11-13 scene IDs. Reusing the
        # state loaded by the previous small batch avoids a second full-board
        # download while every created card is appended to this cache below.
        # `refresh=1` remains available for an explicit read-before-write reset.
        refresh = request.args.get("refresh") == "1"
        try:
            if refresh or _WRITE_STATE_CACHE["state"] is None:
                _WRITE_STATE_CACHE["state"] = runtime_state(api)
            state = _WRITE_STATE_CACHE["state"]
        except Exception as exc:
            return jsonify({"status": "blocked", "stage": "runtime-state", "error": f"{type(exc).__name__}: {exc}"}), 409
        source_ids = {scene["scene_id"] for scene in payload["scenes"]}
        if set(mapping["spaces_by_scene"]) != source_ids:
            return jsonify({"status": "blocked", "error": "identity/space map does not cover source scenes"}), 409
        try:
            prop_plan, space_plan = master_plans(state, payload, mapping)
        except Exception as exc:
            return jsonify({"status": "blocked", "stage": "master-plan", "error": f"{type(exc).__name__}: {exc}"}), 409
        unresolved = [row["name"] for row in [*prop_plan, *space_plan] if row["status"] != "reuse"]
        if unresolved and mode != "master-init":
            return jsonify({"status": "blocked", "unresolved_masters": unresolved}), 409
        if mode == "master-init":
            try:
                result = init_masters(api, state, payload, mapping, start, limit)
                return jsonify({"status": "applied", "mode": mode, **result}), 200
            except Exception as exc:
                return jsonify({"status": "blocked", "error": f"{type(exc).__name__}: {exc}"}), 409
        try:
            prop_cards, space_cards = resolve_master_maps(state, payload, mapping)
            scene_lists = exact_named(state["lists"], "SCENÁRE")
            if len(scene_lists) != 1:
                return jsonify({"status": "blocked", "scene_lists": len(scene_lists)}), 409
            cards, collisions = card_map(api, state)
            relevant_collisions = sorted(source_ids & set(collisions))
            if relevant_collisions:
                return jsonify({"status": "blocked", "scene_collisions": relevant_collisions}), 409
            all_scenes = combined_scenes(api, payload)
        except Exception as exc:
            return jsonify({"status": "blocked", "stage": "prepare", "error": f"{type(exc).__name__}: {exc}"}), 409
        # Board labels are user-visible and their capitalization has changed over
        # time. Resolve them by the same accent/case-insensitive key used by the
        # rest of the importer while retaining the board's real label IDs.
        label_ids = {folded(row["name"]): row["id"] for row in state["labels"]}
        if mode == "sample":
            selected = [payload["scenes"][0]]
        elif mode == "fill":
            selected = [scene for scene in payload["scenes"] if scene["scene_id"] not in cards][:limit]
        else:
            selected = payload["scenes"][start:start + limit]
        results = []
        writes = 0
        for scene in selected:
            desired = desired_scene(scene, all_scenes, cards, prop_cards, space_cards, mapping)
            try:
                card, count, created = apply_scene_new(api, state, scene, desired, label_ids, scene_lists[0]["id"])
            except Exception as exc:
                return jsonify({"status": "blocked", "failed_scene_id": scene["scene_id"],
                                "error": f"{type(exc).__name__}: {exc}", "completed": results, "writes": writes}), 409
            cards[scene["scene_id"]] = card
            writes += count
            results.append({"scene_id": scene["scene_id"], "created": created, "writes": count,
                            "url": card.get("shortUrl")})
        if mode == "final-audit":
            return jsonify(audit(api)), 200
        return jsonify({"status": "applied", "mode": mode, "selected": len(selected),
                        "writes": writes, "remaining": 0 if mode == "sample" else max(0, len(payload["scenes"]) - start - len(selected)),
                        "results": results}), 200
