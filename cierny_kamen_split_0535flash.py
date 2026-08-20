from __future__ import annotations

import copy
import hashlib
import re
import unicodedata

from flask import jsonify, request

from cierny_kamen_all_props_registry import ensure_attachment
from cierny_kamen_reference_all import board_support_data, protected_card_value


KEY = "cierny-kamen-split-0535flash-20aug-4f09d26c"
SCENE_ID = "05/35FLASH"
SOURCE = "SC_01_05_ČK_1.6_NJ_FINAL.pdf"
ACTION_RAW = (
    "Je deň, kedy sa Jakub stratil, Sára a Jakub stoja pri rieke a pozerajú si do očí.\n\n"
    "Jakub a Sára sa objímu."
)
ACTION_MD = (
    "*Je deň, kedy sa Jakub stratil, Sára a Jakub stoja pri rieke a pozerajú si do očí.*\n\n"
    "*Jakub a Sára sa objímu.*"
)
FLASH_PATTERNS = (
    re.compile(r"\s*\(prestrih Flash pri rieke\)\s*Je de., kedy sa Jakub stratil,.*?\(prestrih Kremat.rium\)\s*", re.I | re.S),
    re.compile(r"\s*\(prestrih Flash pri rieke\)\s*Jakub a S.ra sa obj.mu\..*?\(prestrih Kremat.rium\)\s*", re.I | re.S),
)
HEADER_PATTERN = re.compile(
    r"\A(\s*\*)?\s*PARALELNE\s+5/35FLASH\s*\W\s*PRI RIEKE\s*\W\s*DAY X\s+S.RA,\s*JAKUB\s+S.ra a Jakub sa obj.maj. pri odchode\s*", re.I,
)
METADATA_START = "<!-- CIERNY-KAMEN-SCHEDULE-METADATA:START -->"
METADATA_END = "<!-- CIERNY-KAMEN-SCHEDULE-METADATA:END -->"


def split_parent_action(value):
    result, header_count = HEADER_PATTERN.subn(lambda m: m.group(1) or "", value or "", count=1)
    if header_count != 1:
        raise ValueError("05/35FLASH technical header not found exactly once")
    for pattern in FLASH_PATTERNS:
        result, count = pattern.subn(" ", result, count=1)
        if count != 1:
            raise ValueError("05/35FLASH passage not found exactly once")
    return re.sub(r"[ \t]+\n", "\n", result).strip()


def split_parent_description(desc):
    marker = re.search(r"(?m)^#{2,3}\s+AKCIA A DIALÓGY\s*$", desc or "")
    if not marker or (desc or "").count(METADATA_START) != 1:
        raise ValueError("05/34 action or metadata marker is ambiguous")
    metadata_at = desc.index(METADATA_START)
    if metadata_at <= marker.end():
        raise ValueError("05/34 metadata precedes action")
    desired_action = split_parent_action(desc[marker.end():metadata_at])
    return desc[:marker.end()] + "\n\n" + desired_action + "\n\n" + desc[metadata_at:]


def scene_0535flash():
    return {
        "scene_id": SCENE_ID, "episode": 5,
        "name": "05/35FLASH. PRI RIEKE – DAY X — SÁRA, JAKUB",
        "heading": "PRI RIEKE – DAY X", "prepis": "Sára a Jakub sa objímajú pri odchode",
        "location": "PRI RIEKE", "characters": ["SÁRA", "JAKUB"], "characters_raw": "SÁRA, JAKUB",
        "action_raw": ACTION_RAW, "action_markdown": ACTION_MD,
        "action_sha256": hashlib.sha256(ACTION_RAW.encode("utf-8")).hexdigest(),
        "source_pdf": SOURCE, "source_sha256": "updated-episode-05-v1.6",
        "order_in_episode": 33, "order": 249, "props": [],
        "set_items": [{"stable_name": "PRI RIEKE", "action": "prostredie obrazu 05/35FLASH",
                       "source_text": "PRI RIEKE — prostredie obrazu 05/35FLASH", "continuity": False}],
        "labels": [], "questions": [],
    }


def augment_payload(payload):
    result = copy.deepcopy(payload)
    if any(scene["scene_id"] == SCENE_ID for scene in result["scenes"]):
        return result
    parent = next(scene for scene in result["scenes"] if scene["scene_id"] == "05/34")
    parent["action_raw"] = split_parent_action(parent["action_raw"])
    parent["action_markdown"] = split_parent_action(parent["action_markdown"])
    parent["action_sha256"] = hashlib.sha256(parent["action_raw"].encode("utf-8")).hexdigest()
    index = result["scenes"].index(parent) + 1
    result["scenes"].insert(index, scene_0535flash())
    for scene in result["scenes"][index + 1:]:
        scene["order"] = int(scene.get("order", 0)) + 1
        if scene.get("episode") == 5:
            scene["order_in_episode"] = int(scene.get("order_in_episode", 0)) + 1
    return result


def _fold(value):
    return " ".join("".join(ch for ch in unicodedata.normalize("NFKD", value or "")
                            if not unicodedata.combining(ch)).casefold().split())


def _production_groups(api, state):
    groups, excluded = {}, []
    for card in state["cards"]:
        list_name = state["lists_by_id"].get(card.get("idList"), {}).get("name", "")
        info = api["cierny_kamen_scene_name_info"](card.get("name", ""))
        if not info or info.get("test"):
            continue
        row = {**card, "list_name": list_name}
        if "original screener" in _fold(list_name):
            excluded.append({"scene_id": info["scene_id"], "name": card.get("name"), "url": card.get("shortUrl"), "list": list_name})
            continue
        groups.setdefault(info["scene_id"], []).append(row)
    return groups, excluded


def _metadata_space_url(desc):
    match = re.search(r"(?m)^LOKÁCIA:\s*\[[^]]+\]\((https://trello\.com/c/[A-Za-z0-9]+)", desc or "")
    return match.group(1) if match else None


def _link(scene_id, card):
    title = re.sub(r"^#+\s*", "", (card.get("desc") or "").splitlines()[0]).strip()
    return f"[{scene_id} – {title}]({card['shortUrl']})"


def description_0535flash(space_url, links):
    return f"""## Sára a Jakub sa objímajú pri odchode

## NAVIGÁCIA

### Rovnaký priestor
- Predchádzajúci: {_link('03/54FLASH', links['03/54FLASH'])}
- Nasledujúci: —

### Rovnaké postavy
- SÁRA: ← {_link('05/34', links['05/34'])} | → {_link('05/39', links['05/39'])}
- JAKUB: ← {_link('05/02LP', links['05/02LP'])} | → {_link('05/45LP', links['05/45LP'])}

## RUČNÉ DOPLNENIA


## AKCIA A DIALÓGY

{ACTION_MD}

{METADATA_START}
ČÍSLO OBRAZU: 05/35FLASH
ZDROJ: {SOURCE}
NATÁČACÍ DEŇ: nenaplánované
DÁTUM: nenaplánované
PORADIE: nenaplánované
UNIT: nenaplánované
LOKÁCIA: [PRI RIEKE]({space_url})
POSTAVY: SÁRA, JAKUB{METADATA_END}"""


def _replace_character_navigation(desc, character, direction, new_link):
    pattern = re.compile(rf"(?m)^(-\s*{re.escape(character)}:\s*←\s*)(.*?)(\s*\|\s*→\s*)(.*?)$")
    matches = list(pattern.finditer(desc or ""))
    if len(matches) != 1:
        raise ValueError(f"{character} navigation line is not unique")
    match = matches[0]
    left = new_link if direction == "previous" else match.group(2)
    right = new_link if direction == "next" else match.group(4)
    return desc[:match.start()] + match.group(1) + left + match.group(3) + right + desc[match.end():]


def _replace_space_next(desc, new_link):
    matches = list(re.finditer(r"(?m)^- Nasledujúci:\s*.*$", desc or ""))
    if len(matches) != 1:
        raise ValueError("space next navigation line is not unique")
    match = matches[0]
    return desc[:match.start()] + "- Nasledujúci: " + new_link + desc[match.end():]


def _protected_without_desc(value):
    result = copy.deepcopy(value)
    result["card"].pop("desc", None)
    return result


def build_audit(api):
    payload = api["cierny_kamen_import_payload"]()
    state = api["cierny_kamen_import_state"](payload)
    groups, excluded = _production_groups(api, state)
    support = board_support_data(api, state["board"]["id"])
    blockers = []
    required = ("05/34", "05/36", "03/54FLASH", "05/39", "05/02LP", "05/45LP")
    for scene_id in required:
        if len(groups.get(scene_id, [])) != 1:
            blockers.append(f"{scene_id} production card missing or duplicated")
    variants = {key: value for key, value in groups.items() if key.startswith("05/35")}
    existing = variants.get(SCENE_ID, []) if set(variants) <= {SCENE_ID} else []
    completed = len(existing) == 1 and set(variants) == {SCENE_ID}
    if variants and not completed:
        blockers.append("05/35 production variant already exists")
    parent = groups.get("05/34", [None])[0]
    parent_after = None
    if parent:
        if completed:
            parent_after = parent.get("desc") or ""
            if "5/35FLASH" in parent_after or "Je deň, kedy sa Jakub stratil" in parent_after or "Jakub a Sára sa objímu." in parent_after:
                blockers.append("05/34 still contains 05/35FLASH content")
        else:
            try:
                parent_after = split_parent_description(parent.get("desc") or "")
            except ValueError as exc:
                blockers.append(str(exc))
    source_ids = [scene["scene_id"] for scene in payload["scenes"]]
    if source_ids.count(SCENE_ID) != 1 or source_ids.index(SCENE_ID) != source_ids.index("05/34") + 1:
        blockers.append("authoritative payload order is invalid")
    space_url = _metadata_space_url(groups.get("03/54FLASH", [{}])[0].get("desc")) if groups.get("03/54FLASH") else None
    space_matches = [card for card in state["cards"] if (card.get("shortUrl") or "").casefold() == (space_url or "").casefold()]
    if len(space_matches) != 1:
        blockers.append("PRI RIEKE registry URL missing or ambiguous")
    elif _fold(state["lists_by_id"].get(space_matches[0].get("idList"), {}).get("name")) != _fold("REGISTER PRIESTOROV"):
        blockers.append("PRI RIEKE URL does not target REGISTER PRIESTOROV")
    links = {scene_id: groups[scene_id][0] for scene_id in required if len(groups.get(scene_id, [])) == 1}
    neighbor_plan = {}
    if len(links) == len(required):
        placeholder = (_link(SCENE_ID, existing[0]) if completed else
                       "[05/35FLASH – Sára a Jakub sa objímajú pri odchode](<NEW_05_35FLASH_URL>)")
        operations = {
            "03/54FLASH": lambda d: _replace_space_next(d, placeholder),
            "05/34": lambda d: _replace_character_navigation(d, "SÁRA", "next", placeholder),
            "05/39": lambda d: _replace_character_navigation(d, "SÁRA", "previous", placeholder),
            "05/02LP": lambda d: _replace_character_navigation(d, "JAKUB", "next", placeholder),
            "05/45LP": lambda d: _replace_character_navigation(d, "JAKUB", "previous", placeholder),
        }
        for scene_id, operation in operations.items():
            try:
                base = parent_after if scene_id == "05/34" else links[scene_id].get("desc") or ""
                neighbor_plan[scene_id] = {"before": links[scene_id].get("desc") or "", "after": operation(base)}
            except ValueError as exc:
                blockers.append(f"{scene_id}: {exc}")
    scene_lists = [row for row in state["lists"] if not row.get("closed") and _fold(row.get("name")) == _fold("SCENÁRE")]
    if len(scene_lists) != 1:
        blockers.append("SCENÁRE target list missing or ambiguous")
    snapshots = {card["id"]: protected_card_value(card, support) for card in links.values()}
    if completed:
        existing_support = sorted(support["checklists"].get(existing[0]["id"], []), key=lambda row: row.get("pos", 0))
        expected_names = ["REKVIZITY", "SET", "INFO Z PORADY", "INFO Z NATÁČANIA", "OTÁZKY NA PORADU"]
        if [row.get("name") for row in existing_support] != expected_names:
            blockers.append("existing 05/35FLASH checklist structure mismatch")
        props = next((row for row in existing_support if row.get("name") == "REKVIZITY"), {})
        set_list = next((row for row in existing_support if row.get("name") == "SET"), {})
        if props.get("checkItems"):
            blockers.append("existing 05/35FLASH has unexpected prop items")
        if len(set_list.get("checkItems", [])) != 1 or space_url not in (set_list.get("checkItems", [{}])[0].get("name") or ""):
            blockers.append("existing 05/35FLASH SET link mismatch")
        desc = existing[0].get("desc") or ""
        if ACTION_RAW.split("\n\n")[0] not in desc or ACTION_RAW.split("\n\n")[1] not in desc:
            blockers.append("existing 05/35FLASH action read-back mismatch")
    return {
        "status": "read-only-dry-run", "writes": 0, "blockers": blockers,
        "board": state["board"], "payload_scene_count": len(payload["scenes"]),
        "production_variants_05_35": {key: [{"name": c["name"], "url": c["shortUrl"], "closed": c.get("closed"), "list": c["list_name"]} for c in value] for key, value in variants.items()},
        "excluded_original_screener_matches": [row for row in excluded if row["scene_id"].startswith("05/35")],
        "source": {"scene_id": SCENE_ID, "header": "5/35FLASH – PRI RIEKE – DAY X", "characters": ["SÁRA", "JAKUB"], "action": ACTION_RAW},
        "parent": {"url": parent.get("shortUrl") if parent else None,
                   "before_sha256": hashlib.sha256((parent.get("desc") or "").encode()).hexdigest() if parent else None,
                   "after_sha256": hashlib.sha256((parent_after or "").encode()).hexdigest() if parent_after else None,
                   "changed": bool(parent and parent_after != parent.get("desc"))},
        "space": {"url": space_url, "master": space_matches[0].get("name") if len(space_matches) == 1 else None},
        "neighbors": {scene_id: {"url": card["shortUrl"], "name": card["name"]} for scene_id, card in links.items()},
        "neighbor_updates": {scene_id: {"changed": row["before"] != row["after"]} for scene_id, row in neighbor_plan.items()},
        "completed": completed,
        "planned": {"create_cards": 0 if completed else 1, "create_checklists": 0 if completed else 5,
                    "create_set_items": 0 if completed else 1, "create_prop_items": 0,
                    "update_parent": int(bool(parent and parent_after != parent.get("desc"))),
                    "update_neighbor_navigation": sum(row["before"] != row["after"] for row in neighbor_plan.values())},
        "snapshots": snapshots, "_state": state, "_support": support, "_groups": groups,
        "_links": links, "_neighbor_plan": neighbor_plan, "_space_matches": space_matches, "_scene_lists": scene_lists,
    }


def _public_audit(audit):
    return {key: value for key, value in audit.items() if not key.startswith("_")}


def apply(api):
    audit = build_audit(api)
    if audit["blockers"]:
        return _public_audit(audit), 409
    if audit["completed"] and not any(audit["planned"].values()):
        card = audit["production_variants_05_35"][SCENE_ID][0]
        return {"status": "unchanged", "writes": 0, "new_card": card,
                "read_back": {"05_34": 1, "05_35": 0, "05_35FLASH": 1, "05_36": 1, "errors": []}}, 200
    state, support, groups = audit["_state"], audit["_support"], audit["_groups"]
    for card_id, before in audit["snapshots"].items():
        live = next(card for card in state["cards"] if card["id"] == card_id)
        if protected_card_value(live, support) != before:
            return {**_public_audit(audit), "error": f"protected card changed: {card_id}"}, 409
    card34, card36 = groups["05/34"][0], groups["05/36"][0]
    new_card = api["trello_post_body"]("/cards", {
        "idList": audit["_scene_lists"][0]["id"], "name": scene_0535flash()["name"],
        "desc": description_0535flash(audit["space"]["url"], audit["_links"]),
        "pos": (float(card34.get("pos") or 0) + float(card36.get("pos") or 0)) / 2,
    })
    writes = 1
    checklists = {}
    checklist_names = ("REKVIZITY", "SET", "INFO Z PORADY", "INFO Z NATÁČANIA", "OTÁZKY NA PORADU")
    for index, name in enumerate(checklist_names):
        checklists[name] = api["trello_post_body"](f"/cards/{new_card['id']}/checklists", {"name": name, "pos": (index + 1) * 16384})
        writes += 1
    api["trello_post_body"](f"/checklists/{checklists['SET']['id']}/checkItems", {
        "name": f"PRI RIEKE — prostredie obrazu 05/35FLASH | KARTA: {audit['space']['url']}", "pos": "bottom"})
    writes += 1
    writes += ensure_attachment(api, new_card, audit["space"]["url"], "PRI RIEKE")
    writes += ensure_attachment(api, audit["_space_matches"][0], new_card["shortUrl"], "05/35FLASH")
    placeholder = "[05/35FLASH – Sára a Jakub sa objímajú pri odchode](<NEW_05_35FLASH_URL>)"
    new_link = f"[05/35FLASH – Sára a Jakub sa objímajú pri odchode]({new_card['shortUrl']})"
    for scene_id, row in audit["_neighbor_plan"].items():
        api["trello_put_body"](f"/cards/{groups[scene_id][0]['id']}", {"desc": row["after"].replace(placeholder, new_link)})
        writes += 1
    after_payload = api["cierny_kamen_import_payload"]()
    after_state = api["cierny_kamen_import_state"](after_payload)
    after_groups, _ = _production_groups(api, after_state)
    support_after = board_support_data(api, after_state["board"]["id"])
    created = after_groups.get(SCENE_ID, [])
    errors = []
    if len(created) != 1 or created[0]["id"] != new_card["id"]:
        errors.append("created scene read-back mismatch")
    if after_groups.get("05/35"):
        errors.append("unexpected 05/35 base card")
    created_checklists = support_after["checklists"].get(new_card["id"], []) if created else []
    names = [row.get("name") for row in sorted(created_checklists, key=lambda row: row.get("pos", 0))]
    if names != list(checklist_names):
        errors.append("checklist read-back mismatch")
    for card_id, before in audit["snapshots"].items():
        live = next(card for card in after_state["cards"] if card["id"] == card_id)
        if _protected_without_desc(before) != _protected_without_desc(protected_card_value(live, support_after)):
            errors.append(f"protected non-description data changed: {card_id}")
    return {"status": "applied" if not errors else "audit-failed", "writes": writes,
            "new_card": {"id": new_card["id"], "url": new_card["shortUrl"], "name": new_card["name"]},
            "read_back": {"05_34": len(after_groups.get("05/34", [])), "05_35": len(after_groups.get("05/35", [])),
                          "05_35FLASH": len(created), "05_36": len(after_groups.get("05/36", [])),
                          "checklists": names, "errors": errors}}, 200 if not errors else 500


def register_routes(app, api):
    @app.route("/api/cierny-kamen-split-0535flash", methods=["POST"])
    def split_0535flash():
        if request.headers.get("X-Split-0535FLASH-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "dry-run").casefold()
        try:
            if mode in {"dry-run", "audit"}:
                audit = build_audit(api)
                return jsonify(_public_audit(audit)), 200 if not audit["blockers"] else 409
            if mode == "apply":
                result, status = apply(api)
                return jsonify(result), status
            return jsonify({"error": "invalid mode"}), 400
        except Exception as exc:
            app.logger.exception("05/35FLASH split failed")
            return jsonify({"status": "failed", "writes": 0, "error": f"{type(exc).__name__}: {exc}"}), 502
