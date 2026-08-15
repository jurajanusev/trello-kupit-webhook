from __future__ import annotations

import re
import unicodedata
import hashlib
from collections import Counter, defaultdict
from pathlib import Path
import json

from flask import jsonify, request

from cierny_kamen_all_props_registry import (
    PROP_AUTO_END, PROP_AUTO_START,
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
CHECKLIST_NAMES = (
    "REKVIZITY", "SET", "INFO Z PORADY", "INFO Z NATÁČANIA",
    "OTÁZKY NA PORADU",
)
BOOTSTRAP_MARKER = "<!-- CIERNY-KAMEN-EP07-10-BOOTSTRAP -->"
SET_CHAIN_AUTO_START = "<!-- CIERNY-KAMEN-SET-CHAIN-AUTO:START -->"
SET_CHAIN_AUTO_END = "<!-- CIERNY-KAMEN-SET-CHAIN-AUTO:END -->"
SET_CHAINS = (
    {
        "name": "Veronikina vila – výzdoba a pohostenie Sofiinej baby shower",
        "occurrences": (
            ("08/30", "vzniká vyzdobený a pohostením prestretý priestor baby shower"),
            ("08/32", "baby shower pokračuje s hosťami, občerstvením a darčekmi"),
            ("08/34", "hostky pokračujú v baby shower a rozbaľovaní darčekov"),
            ("08/35", "po baby shower zostávajú poháre a neporiadok, ktoré sa upratujú"),
        ),
    },
    {
        "name": "Alexov dom – výzdoba a neporiadok po Dogyho oslave",
        "occurrences": (
            ("10/25", "vzniká výzdoba a občerstvenie na Dogyho prekvapivú oslavu"),
            ("10/26", "výzdoba a občerstvenie pokračujú pri príchode oslávenca"),
            ("10/28", "stav párty sa rozširuje o ďalších hostí, sud piva a hlasnú hudbu"),
            ("10/29", "párty v obývačke pokračuje v plnom prúde"),
            ("10/33", "v kuchyni zostáva párty neporiadok a použité umelé poháre"),
            ("10/39", "párty a rozmiestnenie hostí pokračujú až do záverečnej drámy"),
            ("10/42", "po skončení párty zostáva v obývačke explicitný neporiadok"),
        ),
    },
)
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


def runtime_state(api):
    """Load every active card even when archived board history exceeds 1000 cards."""
    board = api["trello_get"](f"/boards/{BOARD_REF}", {
        "fields": "id,name,url,closed,shortLink",
    })
    lists = api["trello_get"](f"/boards/{board['id']}/lists", {
        "fields": "id,name,pos,closed", "filter": "all",
    })
    labels = api["trello_get"](f"/boards/{board['id']}/labels", {
        "fields": "id,name,color", "limit": 1000,
    })
    cards_by_id = {
        card["id"]: card for card in api["trello_get"](
            f"/boards/{board['id']}/cards", {
                "fields": "id,name,desc,idList,shortUrl,closed,idLabels",
                "filter": "open", "limit": 1000,
            }
        )
    }
    # Supplement the capped board page with complete lists that contain the
    # source scenes and the one old master known to fall outside that page.
    # This keeps the request below Render's timeout while preserving coverage.
    supplement_names = {
        "SCENÁRE", PROP_LIST, SPACE_LIST, SET_LIST,
        "ALEX – OS. REKVIZITY",
    }
    for item in lists:
        if item.get("closed") or not any(
            folded(item.get("name")) == folded(name)
            for name in supplement_names
        ):
            continue
        for card in api["trello_get"](f"/lists/{item['id']}/cards", {
            "fields": "id,name,desc,idList,shortUrl,closed,idLabels",
            "filter": "open", "limit": 1000,
        }):
            cards_by_id[card["id"]] = card
    search = api["trello_get"]("/search", {
        "query": "Alexova gitara od Lukáša", "idBoards": board["id"],
        "modelTypes": "cards", "cards_limit": 100,
        "card_fields": "id,name,desc,idList,shortUrl,closed,idLabels",
    })
    for card in search.get("cards", []):
        if not card.get("closed"):
            cards_by_id[card["id"]] = card
    cards = list(cards_by_id.values())
    return {
        "board": board, "lists": lists, "labels": labels, "cards": cards,
        "lists_by_id": {item["id"]: item for item in lists},
    }


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
    allowed_ids = {
        item["id"] for item in state["lists"]
        if not item.get("closed") and "rekvizit" in folded(item.get("name"))
    }
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


def combined_scenes(api, new_payload):
    existing = api["cierny_kamen_import_payload"]()["scenes"]
    result = []
    seen = set()
    for scene in [*existing, *new_payload["scenes"]]:
        if scene["scene_id"] in seen:
            continue
        seen.add(scene["scene_id"])
        result.append(scene)
    return result


def card_map(api, state):
    groups = api["cierny_kamen_scene_cards_by_id"](state)
    return {
        scene_id: cards[0] for scene_id, cards in groups.items()
        if len(cards) == 1 and not cards[0].get("closed")
    }, {scene_id: cards for scene_id, cards in groups.items() if len(cards) > 1}


def location_names(scene, space_map):
    return space_map.get(scene.get("location", ""), [scene.get("location", "")])


def character_identity(value):
    value = re.sub(r"\s+(?:M\.?O\.?|V\.?O\.?)$", "", value or "", flags=re.I)
    return folded(value)


def display_link(scene, cards):
    card = cards.get(scene["scene_id"]) if scene else None
    if not scene or not card or not card.get("shortUrl"):
        return "—"
    return f"[{scene['scene_id']} – {scene['prepis']}]({card['shortUrl']})"


def continuity_sections(scene, all_scenes, cards, space_map):
    index = next(i for i, item in enumerate(all_scenes) if item["scene_id"] == scene["scene_id"])
    target_spaces = {folded(name) for name in location_names(scene, space_map)}
    def same_space(item):
        return bool(target_spaces & {folded(name) for name in location_names(item, space_map)})
    previous_space = next((item for item in reversed(all_scenes[:index]) if same_space(item)), None)
    next_space = next((item for item in all_scenes[index + 1:] if same_space(item)), None)
    space = (
        "### KONTINUITA PRIESTORU\n\n"
        f"- Predchádzajúci: {display_link(previous_space, cards)}\n"
        f"- Nasledujúci: {display_link(next_space, cards)}"
    )
    rows = ["### KONTINUITA POSTÁV", ""]
    characters = []
    for character in scene.get("characters", []):
        key = character_identity(character)
        if key and key not in {character_identity(item) for item in characters}:
            characters.append(character)
    for character in characters:
        key = character_identity(character)
        def has_character(item):
            return key in {character_identity(value) for value in item.get("characters", [])}
        previous = next((item for item in reversed(all_scenes[:index]) if has_character(item)), None)
        following = next((item for item in all_scenes[index + 1:] if has_character(item)), None)
        rows.append(f"- {character}: ← {display_link(previous, cards)} | → {display_link(following, cards)}")
    return space, "\n".join(rows)


def master_maps(state, identity_map, payload, space_map, scene_filter=None):
    prop_rows = registry_plan(state, identity_map)
    prop_cards = {}
    conflicts = []
    required_props = {
        record["stable_name"] for record in identity_map["records"]
        if record.get("physical_presence", True)
        and (not scene_filter or record["scene_id"] in scene_filter)
    }
    for row in prop_rows:
        if row["name"] not in required_props:
            continue
        if len(row["matches"]) == 1:
            prop_cards[row["name"]] = row["matches"][0]
        else:
            conflicts.append({"type": "prop", **row})
    spaces = space_plan(state, payload, space_map, scene_filter)
    space_cards = {}
    for row in spaces:
        if len(row["matches"]) == 1:
            space_cards[row["name"]] = row["matches"][0]
        else:
            conflicts.append({"type": "space", **row})
    return prop_cards, space_cards, conflicts


def records_by_scene(identity_map):
    result = defaultdict(list)
    for record in identity_map["records"]:
        if record.get("physical_presence", True):
            result[record["scene_id"]].append(record)
    return result


def prop_item_text(record, master_url):
    name = record["stable_name"]
    action = record["action"]
    if record.get("continuity_group") and (record.get("previous") or record.get("next") or "Nadväzná rekvizita" in record.get("categories", [])):
        previous = f"{record['previous']}" if record.get("previous") else "prvý výskyt"
        following = record.get("next") or "ďalší potvrdený obraz neurčený"
        return (
            f"<n> **{name}** — *{action} | ← {previous} | TU: {record['current_state']} | → {following}* "
            f"| KARTA: {master_url}"
        )
    return f"**{name}** — *{action}* | KARTA: {master_url}"


def desired_scene(scene, all_scenes, cards, prop_cards, space_cards, space_map, identity_map):
    records = records_by_scene(identity_map).get(scene["scene_id"], [])
    missing_props = [record["stable_name"] for record in records if record["stable_name"] not in prop_cards]
    missing_spaces = [name for name in location_names(scene, space_map) if name not in space_cards]
    if missing_props or missing_spaces:
        raise ValueError(f"missing registry cards props={missing_props} spaces={missing_spaces}")
    prop_context = [f"- **{record['stable_name']}** — {record['action']}" for record in records]
    if not prop_context:
        prop_context = ["- Bez samostatnej rekvizity určenej v zdroji."]
    continuity_records = [record for record in records if record.get("continuity_group") and (record.get("previous") or record.get("next") or "Nadväzná rekvizita" in record.get("categories", []))]
    continuity = [f"- <n> {record['stable_name']}" for record in continuity_records] or ["- Bez potvrdenej nadväznosti."]
    links = [f"- [{record['stable_name']}]({prop_cards[record['stable_name']]['url']})" for record in records]
    links.extend(f"- [{name}]({space_cards[name]['url']})" for name in location_names(scene, space_map))
    if not links:
        links = ["- Bez samostatného odkazu."]
    space_section, characters_section = continuity_sections(scene, all_scenes, cards, space_map)
    locations = location_names(scene, space_map)
    location_value = ", ".join(f"[{name}]({space_cards[name]['url']})" for name in locations)
    location_label = "LOKÁCIE" if len(locations) > 1 else "LOKÁCIA"
    characters = scene.get("characters_raw") or ", ".join(scene.get("characters", [])) or "neuvedené"
    questions = [item["question"] for item in identity_map["questions"] if item["scene_id"] == scene["scene_id"]]
    desc = (
        f"## {scene['prepis']}\n\n"
        "### REKVIZITY V KONTEXTE\n" + "\n".join(prop_context) + "\n\n"
        "### NADVAZNOSŤ\n\n" + "\n".join(continuity) + "\n\n"
        "### ODKAZY\n" + "\n".join(links) + "\n\n"
        f"{space_section}\n\n{characters_section}\n\n"
        "### RUČNÉ DOPLNENIA\n\n"
        "### AKCIA A DIALÓGY\n" + scene["action_markdown"] + "\n\n"
        "<!-- CIERNY-KAMEN-SCHEDULE-METADATA:START -->\n"
        f"ČÍSLO OBRAZU: {scene['scene_id']}\n"
        f"ZDROJ: {scene['source_pdf']}\n"
        "NATÁČACÍ DEŇ: nenaplánované\nDÁTUM: nenaplánované\nPORADIE: nenaplánované\nUNIT: nenaplánované\n"
        f"{location_label}: {location_value}\nPOSTAVY: {characters}\n"
        "<!-- CIERNY-KAMEN-SCHEDULE-METADATA:END -->"
    )
    checklists = {
        "REKVIZITY": [prop_item_text(record, prop_cards[record["stable_name"]]["url"]) for record in records],
        "SET": [f"{name} — prostredie obrazu {scene['scene_id']} | KARTA: {space_cards[name]['url']}" for name in locations],
        "INFO Z PORADY": [], "INFO Z NATÁČANIA": [],
        "OTÁZKY NA PORADU": questions,
    }
    labels = set()
    if continuity_records:
        labels.add("Nadväzná rekvizita")
    if any("Auto" in record.get("categories", []) for record in records):
        labels.add("Auto")
    return desc, checklists, labels


def read_checklists(api, card_id):
    return sorted(api["trello_get"](f"/cards/{card_id}/checklists", {
        "checkItems": "all", "fields": "id,name,pos",
    }), key=lambda item: item.get("pos", 0))


def compatible_sample_checklists(scene_id, actual, desired):
    return (
        scene_id in SAMPLE_SCENES
        and [item[0] for item in actual] == list(CHECKLIST_NAMES)
        and [len(item[1]) for item in actual] == [len(item[1]) for item in desired]
    )


def generated_checklist_prefix(actual, desired):
    if [item[0] for item in actual] != list(CHECKLIST_NAMES[:len(actual)]):
        return False
    for (name, actual_items), (_, desired_items) in zip(actual, desired):
        if actual_items != desired_items[:len(actual_items)]:
            return False
    return True


def apply_scene(api, state, scene, desired, label_ids, scene_list_id):
    desc, checklists, label_names = desired
    cards, collisions = card_map(api, state)
    if collisions.get(scene["scene_id"]):
        raise ValueError("scene collision")
    card = cards.get(scene["scene_id"])
    writes = 0
    created = False
    if not card:
        card = api["trello_post_body"]("/cards", {
            "idList": scene_list_id, "name": scene["name"], "desc": desc,
            "pos": "bottom", "idLabels": ",".join(label_ids[name] for name in label_names),
        })
        state["cards"].append(card)
        writes += 1
        created = True
    else:
        updates = {}
        if card.get("name") != scene["name"]:
            updates["name"] = scene["name"]
        if card.get("desc") != desc:
            if (
                card.get("desc")
                and "CIERNY-KAMEN-EP07-10-BOOTSTRAP" not in card.get("desc", "")
                and scene["scene_id"] not in SAMPLE_SCENES
            ):
                raise ValueError("existing non-bootstrap description conflict")
            updates["desc"] = desc
        expected_labels = sorted(label_ids[name] for name in label_names)
        if sorted(card.get("idLabels", [])) != expected_labels:
            updates["idLabels"] = ",".join(expected_labels)
        if updates:
            api["trello_put_body"](f"/cards/{card['id']}", updates)
            card.update(updates)
            if isinstance(card.get("idLabels"), str):
                card["idLabels"] = [
                    value for value in card["idLabels"].split(",") if value
                ]
            writes += 1
    actual = read_checklists(api, card["id"])
    if actual:
        actual_projection = [(item["name"], [entry["name"] for entry in sorted(item.get("checkItems", []), key=lambda value: value.get("pos", 0))]) for item in actual]
        desired_projection = [(name, checklists[name]) for name in CHECKLIST_NAMES]
        if actual_projection != desired_projection:
            resumable = (
                card.get("desc") == desc
                and generated_checklist_prefix(actual_projection, desired_projection)
            )
            if resumable:
                for checklist in actual:
                    items = sorted(checklist.get("checkItems", []), key=lambda value: value.get("pos", 0))
                    for desired_name in checklists[checklist["name"]][len(items):]:
                        api["trello_post_body"](
                            f"/checklists/{checklist['id']}/checkItems",
                            {"name": desired_name, "pos": "bottom"},
                        )
                        writes += 1
                for position, name in enumerate(CHECKLIST_NAMES[len(actual):], len(actual) + 1):
                    checklist = api["trello_post_body"](
                        f"/cards/{card['id']}/checklists",
                        {"name": name, "pos": position * 16384},
                    )
                    writes += 1
                    for item in checklists[name]:
                        api["trello_post_body"](
                            f"/checklists/{checklist['id']}/checkItems",
                            {"name": item, "pos": "bottom"},
                        )
                        writes += 1
                return card, writes, created
            compatible_sample = compatible_sample_checklists(
                scene["scene_id"], actual_projection, desired_projection
            )
            if not compatible_sample:
                raise ValueError("existing checklist conflict")
            for checklist in actual:
                wanted = checklists[checklist["name"]]
                items = sorted(checklist.get("checkItems", []), key=lambda value: value.get("pos", 0))
                for item, desired_name in zip(items, wanted):
                    if item["name"] == desired_name:
                        continue
                    api["trello_put_body"](
                        f"/cards/{card['id']}/checkItem/{item['id']}",
                        {"name": desired_name},
                    )
                    writes += 1
    else:
        for position, name in enumerate(CHECKLIST_NAMES, 1):
            checklist = api["trello_post_body"](f"/cards/{card['id']}/checklists", {"name": name, "pos": position * 16384})
            writes += 1
            for item in checklists[name]:
                api["trello_post_body"](f"/checklists/{checklist['id']}/checkItems", {"name": item, "pos": "bottom"})
                writes += 1
    return card, writes, created


def bootstrap_scene(api, state, scene, scene_list_id):
    cards, collisions = card_map(api, state)
    if collisions.get(scene["scene_id"]):
        raise ValueError("scene collision")
    card = cards.get(scene["scene_id"])
    if card:
        return card, False
    card = api["trello_post_body"]("/cards", {
        "idList": scene_list_id, "name": scene["name"],
        "desc": f"{BOOTSTRAP_MARKER}\n{scene['scene_id']}", "pos": "bottom",
    })
    state["cards"].append(card)
    return card, True


def scene_readback(api, card, desired):
    desc, checklists, label_names = desired
    actual_card = api["trello_get"](f"/cards/{card['id']}", {
        "fields": "id,name,desc,idList,shortUrl,closed,idLabels",
    })
    actual_lists = read_checklists(api, card["id"])
    projection = [
        (item["name"], [entry["name"] for entry in sorted(
            item.get("checkItems", []), key=lambda value: value.get("pos", 0)
        )]) for item in actual_lists
    ]
    expected = [(name, checklists[name]) for name in CHECKLIST_NAMES]
    return {
        "id": actual_card["id"], "url": actual_card.get("shortUrl"),
        "name_ok": actual_card.get("name") == card.get("name"),
        "description_ok": actual_card.get("desc") == desc,
        "description_sha256": hashlib.sha256(
            (actual_card.get("desc") or "").encode("utf-8")
        ).hexdigest(),
        "checklists_ok": projection == expected,
        "checklist_names": [item[0] for item in projection],
        "checklist_item_counts": {item[0]: len(item[1]) for item in projection},
        "expected_label_names": sorted(label_names, key=folded),
    }


def occurrence_link(scene, card):
    return f"- [{scene['scene_id']} – {scene['prepis']}]({card['shortUrl']})"


def merged_occurrence_links(existing_desc, new_links):
    existing = re.findall(
        r"(?m)^- \[[^\n]+\]\(https://trello\.com/c/[^)]+\)$",
        existing_desc or "",
    )
    result = []
    seen_urls = set()
    for line in [*existing, *new_links]:
        match = re.search(r"https://trello\.com/c/[^)]+", line)
        key = match.group(0) if match else line
        if key in seen_urls:
            continue
        seen_urls.add(key)
        result.append(line)
    return result


def ensure_attachments(api, card, links):
    existing = api["trello_get"](
        f"/cards/{card['id']}/attachments", {"fields": "id,name,url"}
    )
    urls = {item.get("url") for item in existing}
    added = 0
    for url, name in links:
        if url in urls:
            continue
        api["trello_post_body"](
            f"/cards/{card['id']}/attachments", {"url": url, "name": name}
        )
        urls.add(url)
        added += 1
    return added


def sync_prop_master(api, state, row, scenes_by_id, cards_by_id, label_ids):
    if len(row["matches"]) != 1:
        raise ValueError(f"prop master conflict: {row['name']}")
    master = next(card for card in state["cards"] if card["id"] == row["matches"][0]["id"])
    occurrence_ids = [scene_id for scene_id in row["scene_ids"] if scene_id in cards_by_id]
    occurrences = merged_occurrence_links(
        master.get("desc"),
        [occurrence_link(scenes_by_id[sid], cards_by_id[sid]) for sid in occurrence_ids],
    )
    block = prop_registry_block(row["name"], row["categories"], occurrences)
    desired_desc = replace_auto_block(master.get("desc"), PROP_AUTO_START, PROP_AUTO_END, block)
    desired_labels = sorted(set(master.get("idLabels", [])) | {
        label_ids[name] for name in row["categories"]
    })
    updates = {}
    target_lists = exact_named(state["lists"], row["target_list"])
    if len(target_lists) != 1:
        raise ValueError(f"prop target list conflict: {row['target_list']}")
    if master.get("idList") != target_lists[0]["id"]:
        updates["idList"] = target_lists[0]["id"]
    if master.get("desc") != desired_desc:
        updates["desc"] = desired_desc
    if sorted(master.get("idLabels", [])) != desired_labels:
        updates["idLabels"] = ",".join(desired_labels)
    if updates:
        api["trello_put_body"](f"/cards/{master['id']}", updates)
    attachments = ensure_attachments(api, master, [
        (cards_by_id[sid]["shortUrl"], scenes_by_id[sid]["name"])
        for sid in occurrence_ids
    ])
    for sid in occurrence_ids:
        attachments += ensure_attachments(
            api, cards_by_id[sid], [(master["shortUrl"], row["name"])]
        )
    return bool(updates), attachments


def sync_space_master(api, state, row, scenes, cards_by_id, space_map):
    if len(row["matches"]) != 1:
        raise ValueError(f"space master conflict: {row['name']}")
    master = next(card for card in state["cards"] if card["id"] == row["matches"][0]["id"])
    related = [scene for scene in scenes if row["name"] in location_names(scene, space_map) and scene["scene_id"] in cards_by_id]
    links = merged_occurrence_links(
        master.get("desc"),
        [occurrence_link(scene, cards_by_id[scene["scene_id"]]) for scene in related],
    )
    desired = space_registry_description(row["name"])
    desired = desired.replace(
        "- Odkazy sa doplnia po vytvorení obrazových kariet.",
        "\n".join(links) if links else "- Bez obrazového výskytu.",
    )
    desired_desc = replace_space_auto_block(master.get("desc"), desired)
    updated = master.get("desc") != desired_desc
    if updated:
        api["trello_put_body"](f"/cards/{master['id']}", {"desc": desired_desc})
    attachments = ensure_attachments(api, master, [
        (cards_by_id[scene["scene_id"]]["shortUrl"], scene["name"])
        for scene in related
    ])
    for scene in related:
        attachments += ensure_attachments(
            api, cards_by_id[scene["scene_id"]],
            [(master["shortUrl"], row["name"])],
        )
    return updated, attachments


def set_chain_plan(state):
    lists = exact_named(state["lists"], SET_LIST)
    cards = [card for card in state["cards"] if lists and card.get("idList") == lists[0]["id"]]
    rows = []
    for chain in SET_CHAINS:
        matches = [card for card in cards if folded(card.get("name")) == folded(chain["name"])]
        rows.append({
            **chain, "matches": matches,
            "status": "reuse" if len(matches) == 1 else "create" if not matches else "conflict",
        })
    return rows


def set_chain_block(chain, scenes_by_id, cards_by_id):
    links = [
        occurrence_link(scenes_by_id[scene_id], cards_by_id[scene_id])
        for scene_id, _ in chain["occurrences"]
    ]
    timeline = [
        f"- {scene_id}: {context}" for scene_id, context in chain["occurrences"]
    ]
    return (
        f"{SET_CHAIN_AUTO_START}\nKANONICKÝ NÁZOV: {chain['name']}\n"
        "TYP: priamo nadväzný fyzický stav scénografie\n\n"
        "### VÝSKYTY V OBRAZOCH\n" + "\n".join(links) + "\n\n"
        "### ČASOVÁ OS STAVU\n" + "\n".join(timeline) + "\n"
        f"{SET_CHAIN_AUTO_END}"
    )


def set_chain_item(chain, index, master_url):
    scene_id, context = chain["occurrences"][index]
    previous = chain["occurrences"][index - 1][0] if index else "prvý výskyt"
    following = (
        chain["occurrences"][index + 1][0]
        if index + 1 < len(chain["occurrences"])
        else "ďalší potvrdený obraz neurčený"
    )
    return (
        f"<n> **{chain['name']}** — *{context} | ← {previous} | "
        f"TU: {context} | → {following}* | KARTA: {master_url}"
    )


def append_description_link(desc, name, url):
    link = f"- [{name}]({url})"
    if url in (desc or ""):
        return desc
    marker = "\n\n### KONTINUITA PRIESTORU"
    if marker not in (desc or ""):
        raise ValueError("scene continuity section missing")
    return desc.replace(marker, f"\n{link}{marker}", 1)


def sync_set_chain(api, state, chain, scenes_by_id, cards_by_id, label_ids):
    if len(chain["matches"]) != 1:
        raise ValueError(f"set master conflict: {chain['name']}")
    master = next(card for card in state["cards"] if card["id"] == chain["matches"][0]["id"])
    desired_block = set_chain_block(chain, scenes_by_id, cards_by_id)
    desired_desc = replace_auto_block(
        master.get("desc"), SET_CHAIN_AUTO_START, SET_CHAIN_AUTO_END,
        desired_block,
    )
    desired_labels = sorted(set(master.get("idLabels", [])) | {label_ids["Nadväzný priestor"]})
    master_updates = {}
    if master.get("desc") != desired_desc:
        master_updates["desc"] = desired_desc
    if sorted(master.get("idLabels", [])) != desired_labels:
        master_updates["idLabels"] = ",".join(desired_labels)
    if master_updates:
        api["trello_put_body"](f"/cards/{master['id']}", master_updates)
    writes = int(bool(master_updates))
    scene_urls = []
    for index, (scene_id, _) in enumerate(chain["occurrences"]):
        card = cards_by_id[scene_id]
        checklists = read_checklists(api, card["id"])
        set_lists = [item for item in checklists if item["name"] == "SET"]
        if len(set_lists) != 1:
            raise ValueError(f"SET checklist conflict on {scene_id}")
        desired_item = set_chain_item(chain, index, master["shortUrl"])
        existing_items = [item["name"] for item in set_lists[0].get("checkItems", [])]
        related = [item for item in existing_items if chain["name"] in item or master["shortUrl"] in item]
        if related and related != [desired_item]:
            raise ValueError(f"set item conflict on {scene_id}")
        if not related:
            api["trello_post_body"](
                f"/checklists/{set_lists[0]['id']}/checkItems",
                {"name": desired_item, "pos": "bottom"},
            )
            writes += 1
        new_desc = append_description_link(card.get("desc"), chain["name"], master["shortUrl"])
        scene_labels = sorted(set(card.get("idLabels", [])) | {label_ids["Nadväzný set"]})
        updates = {}
        if new_desc != card.get("desc"):
            updates["desc"] = new_desc
        if sorted(card.get("idLabels", [])) != scene_labels:
            updates["idLabels"] = ",".join(scene_labels)
        if updates:
            api["trello_put_body"](f"/cards/{card['id']}", updates)
            writes += 1
        scene_urls.append((card["shortUrl"], scenes_by_id[scene_id]["name"]))
    attachments = ensure_attachments(api, master, scene_urls)
    for scene_id, _ in chain["occurrences"]:
        attachments += ensure_attachments(
            api, cards_by_id[scene_id], [(master["shortUrl"], chain["name"])]
        )
    return writes, attachments


def scene_summary(scene):
    return {
        "scene_id": scene["scene_id"], "name": scene["name"],
        "prepis": scene["prepis"], "location": scene["location"],
        "characters": scene["characters"], "source_page": scene["source_page"],
        "source_pdf": scene["source_pdf"], "action_sha256": scene["action_sha256"],
    }


def build_audit(api, state=None):
    payload = json.loads(PAYLOAD_PATH.read_text(encoding="utf-8"))
    identity_map = json.loads(IDENTITY_PATH.read_text(encoding="utf-8"))
    space_map = json.loads(SPACE_MAP_PATH.read_text(encoding="utf-8"))
    state = state or runtime_state(api)
    board = state["board"]
    lists = state["lists"]
    labels = state["labels"]
    cards = state["cards"]
    prop_plan = registry_plan(state, identity_map)
    spaces_plan = space_plan(state, payload, space_map)
    sets_plan = set_chain_plan(state)
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
    if any(row["status"] == "conflict" for row in sets_plan):
        blockers.append("set continuity identity conflicts")
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
            "set_continuity_chains": len(SET_CHAINS),
            "set_continuity_items": sum(len(item["occurrences"]) for item in SET_CHAINS),
            "set_continuity_note": "Only two explicit carried physical states are included; ordinary repeated locations are not labelled.",
            "set_registry": {
                "reuse": sum(row["status"] == "reuse" for row in sets_plan),
                "create": sum(row["status"] == "create" for row in sets_plan),
                "conflict": [row["name"] for row in sets_plan if row["status"] == "conflict"],
            },
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
            "registry-init", "space-init", "sample-scenes-dry-run",
            "sample-scenes", "bootstrap", "finalize", "registry-sync",
            "space-sync", "set-dry-run", "set-init", "set-sync",
            "final-audit",
        }
        if mode not in allowed:
            return jsonify({"error": "unsupported mode"}), 409
        state = runtime_state(api)
        audit = build_audit(api, state)
        if mode in {"audit", "dry-run"}:
            return jsonify(audit), 200 if not audit["blockers"] else 409
        if audit["blockers"]:
            return jsonify(audit), 409
        payload = json.loads(PAYLOAD_PATH.read_text(encoding="utf-8"))
        identity_map = json.loads(IDENTITY_PATH.read_text(encoding="utf-8"))
        space_map = json.loads(SPACE_MAP_PATH.read_text(encoding="utf-8"))
        try:
            start = int(request.args.get("start", "0"))
            limit = int(request.args.get("limit", "5"))
        except ValueError:
            return jsonify({"error": "invalid start/limit"}), 400
        if start < 0 or limit < 1 or limit > 10:
            return jsonify({"error": "invalid start/limit"}), 400
        sample_only = mode.startswith("sample-")
        scene_filter = set(SAMPLE_SCENES) if sample_only else None
        scenes = payload["scenes"]
        scenes_by_id = {scene["scene_id"]: scene for scene in scenes}
        selected_scenes = (
            [scenes_by_id[scene_id] for scene_id in SAMPLE_SCENES]
            if sample_only else scenes[start:start + limit]
        )
        label_ids = {
            name: exact_named(state["labels"], name)[0]["id"]
            for name in CATEGORY_LABELS
        }

        if mode == "sample-scenes-dry-run":
            prop_cards, space_cards, conflicts = master_maps(
                state, identity_map, payload, space_map, scene_filter
            )
            if conflicts:
                return jsonify({"status": "blocked", "conflicts": conflicts}), 409
            cards, card_collisions = card_map(api, state)
            all_scenes = combined_scenes(api, payload)
            planned = []
            for scene in selected_scenes:
                desired = desired_scene(
                    scene, all_scenes, cards, prop_cards, space_cards,
                    space_map, identity_map,
                )
                planned.append({
                    "scene_id": scene["scene_id"], "name": scene["name"],
                    "description_sha256": hashlib.sha256(desired[0].encode("utf-8")).hexdigest(),
                    "description_chars": len(desired[0]),
                    "checklist_item_counts": {name: len(desired[1][name]) for name in CHECKLIST_NAMES},
                    "labels": sorted(desired[2], key=folded),
                    "existing": scene["scene_id"] in cards,
                })
            return jsonify({
                "status": "sample-dry-run", "writes": 0,
                "card_collisions": list(card_collisions), "planned": planned,
            }), 200 if not card_collisions else 409

        if mode in {"sample-scenes", "finalize"}:
            prop_cards, space_cards, conflicts = master_maps(
                state, identity_map, payload, space_map,
                scene_filter if sample_only else None,
            )
            if conflicts:
                return jsonify({"status": "blocked", "conflicts": conflicts}), 409
            scene_lists = exact_named(state["lists"], "SCENÁRE")
            if len(scene_lists) != 1:
                return jsonify({"status": "blocked", "scene_lists": len(scene_lists)}), 409
            cards, card_collisions = card_map(api, state)
            if card_collisions:
                return jsonify({"status": "blocked", "card_collisions": list(card_collisions)}), 409
            all_scenes = combined_scenes(api, payload)
            results = []
            total_writes = 0
            for scene in selected_scenes:
                desired = desired_scene(
                    scene, all_scenes, cards, prop_cards, space_cards,
                    space_map, identity_map,
                )
                try:
                    card, writes, created = apply_scene(
                        api, state, scene, desired, label_ids, scene_lists[0]["id"]
                    )
                except Exception as error:
                    return jsonify({
                        "status": "blocked", "mode": mode,
                        "failed_scene_id": scene["scene_id"],
                        "error": f"{type(error).__name__}: {error}",
                        "completed_results": results,
                        "writes_before_failure": total_writes,
                    }), 409
                cards[scene["scene_id"]] = card
                total_writes += writes
                results.append({
                    "scene_id": scene["scene_id"], "created": created,
                    "writes": writes, "readback": scene_readback(api, card, desired),
                })
            return jsonify({
                "status": "applied", "mode": mode, "start": start,
                "selected": len(selected_scenes), "writes": total_writes,
                "remaining": 0 if sample_only else max(0, len(scenes) - start - len(selected_scenes)),
                "results": results,
            }), 200

        if mode == "bootstrap":
            scene_lists = exact_named(state["lists"], "SCENÁRE")
            if len(scene_lists) != 1:
                return jsonify({"status": "blocked", "scene_lists": len(scene_lists)}), 409
            results = []
            for scene in selected_scenes:
                card, created = bootstrap_scene(api, state, scene, scene_lists[0]["id"])
                results.append({"scene_id": scene["scene_id"], "created": created, "url": card.get("shortUrl")})
            return jsonify({
                "status": "applied", "mode": mode, "start": start,
                "selected": len(selected_scenes), "created": sum(item["created"] for item in results),
                "writes": sum(item["created"] for item in results),
                "remaining": max(0, len(scenes) - start - len(selected_scenes)),
                "results": results,
            }), 200

        if mode in {"set-dry-run", "set-init", "set-sync"}:
            rows = set_chain_plan(state)
            if any(row["status"] == "conflict" for row in rows):
                return jsonify({
                    "status": "blocked",
                    "conflicts": [row["name"] for row in rows if row["status"] == "conflict"],
                }), 409
            if mode == "set-dry-run":
                return jsonify({
                    "status": "dry-run", "writes": 0,
                    "chains": [{
                        "name": row["name"], "status": row["status"],
                        "scene_ids": [item[0] for item in row["occurrences"]],
                    } for row in rows],
                    "scene_count": sum(len(row["occurrences"]) for row in rows),
                }), 200
            set_lists = exact_named(state["lists"], SET_LIST)
            if len(set_lists) != 1:
                return jsonify({"status": "blocked", "set_lists": len(set_lists)}), 409
            if mode == "set-init":
                created = []
                for row in rows:
                    if row["status"] == "reuse":
                        continue
                    card = api["trello_post_body"]("/cards", {
                        "idList": set_lists[0]["id"], "name": row["name"],
                        "desc": f"{SET_CHAIN_AUTO_START}\nOdkazy sa doplnia po prepojení scén.\n{SET_CHAIN_AUTO_END}",
                        "idLabels": label_ids["Nadväzný priestor"], "pos": "bottom",
                    })
                    created.append({"name": row["name"], "id": card["id"], "url": card.get("shortUrl")})
                return jsonify({
                    "status": "applied", "mode": mode, "created": created,
                    "writes": len(created), "unchanged": len(rows) - len(created),
                }), 200
            cards, card_collisions = card_map(api, state)
            source_cards = {sid: cards[sid] for sid in scenes_by_id if sid in cards}
            if card_collisions or len(source_cards) != len(scenes):
                return jsonify({
                    "status": "blocked", "card_collisions": list(card_collisions),
                    "source_cards": len(source_cards), "expected": len(scenes),
                }), 409
            results = []
            selected_set_rows = rows[start:start + limit]
            for row in selected_set_rows:
                try:
                    writes, attachments = sync_set_chain(
                        api, state, row, scenes_by_id, source_cards, label_ids
                    )
                except Exception as error:
                    return jsonify({
                        "status": "blocked", "failed_master": row["name"],
                        "error": f"{type(error).__name__}: {error}",
                        "completed": results,
                    }), 409
                results.append({
                    "name": row["name"], "writes": writes,
                    "attachments_added": attachments,
                })
            return jsonify({
                "status": "applied", "mode": mode, "results": results,
                "writes": sum(item["writes"] + item["attachments_added"] for item in results),
                "start": start, "selected": len(selected_set_rows),
                "remaining": max(0, len(rows) - start - len(selected_set_rows)),
            }), 200

        if mode in {"registry-sync", "space-sync"}:
            cards, card_collisions = card_map(api, state)
            source_cards = {sid: cards[sid] for sid in scenes_by_id if sid in cards}
            if card_collisions or len(source_cards) != len(scenes):
                return jsonify({
                    "status": "blocked", "card_collisions": list(card_collisions),
                    "source_cards": len(source_cards), "expected": len(scenes),
                }), 409
            updated = attachments = 0
            if mode == "registry-sync":
                rows = registry_plan(state, identity_map)
                selected = rows[start:start + limit]
                for row in selected:
                    try:
                        changed, added = sync_prop_master(
                            api, state, row, scenes_by_id, source_cards, label_ids
                        )
                    except Exception as error:
                        return jsonify({
                            "status": "blocked", "mode": mode,
                            "failed_master": row["name"],
                            "error": f"{type(error).__name__}: {error}",
                            "completed": selected[:selected.index(row)],
                            "updated_before_failure": updated,
                            "attachments_before_failure": attachments,
                        }), 409
                    updated += int(changed)
                    attachments += added
            else:
                rows = space_plan(state, payload, space_map)
                selected = rows[start:start + limit]
                for row in selected:
                    try:
                        changed, added = sync_space_master(
                            api, state, row, scenes, source_cards, space_map
                        )
                    except Exception as error:
                        return jsonify({
                            "status": "blocked", "mode": mode,
                            "failed_master": row["name"],
                            "error": f"{type(error).__name__}: {error}",
                            "completed": selected[:selected.index(row)],
                            "updated_before_failure": updated,
                            "attachments_before_failure": attachments,
                        }), 409
                    updated += int(changed)
                    attachments += added
            return jsonify({
                "status": "applied", "mode": mode, "start": start,
                "selected": len(selected), "updated": updated,
                "attachments_added": attachments, "writes": updated + attachments,
                "remaining": max(0, len(rows) - start - len(selected)),
            }), 200

        if mode == "final-audit":
            cards, card_collisions = card_map(api, state)
            source_cards = {sid: cards[sid] for sid in scenes_by_id if sid in cards}
            missing = sorted(set(scenes_by_id) - set(source_cards))
            bootstrap = [sid for sid, card in source_cards.items() if BOOTSTRAP_MARKER in (card.get("desc") or "")]
            selected_audit = scenes[start:start + limit]
            checklist_errors = []
            description_errors = []
            verbatim_errors = []
            link_errors = []
            name_errors = []
            for scene in selected_audit:
                sid = scene["scene_id"]
                card = source_cards.get(sid)
                if not card:
                    continue
                if card.get("name") != scene["name"]:
                    name_errors.append(sid)
                actual = read_checklists(api, card["id"])
                if [item["name"] for item in actual] != list(CHECKLIST_NAMES):
                    checklist_errors.append(sid)
                desc = card.get("desc") or ""
                required = (
                    "### REKVIZITY V KONTEXTE", "### NADVAZNOSŤ", "### ODKAZY",
                    "### KONTINUITA PRIESTORU", "### KONTINUITA POSTÁV",
                    "### RUČNÉ DOPLNENIA", "### AKCIA A DIALÓGY",
                    "<!-- CIERNY-KAMEN-SCHEDULE-METADATA:START -->",
                )
                if not all(marker in desc for marker in required):
                    description_errors.append(sid)
                if scene["action_markdown"] not in desc:
                    verbatim_errors.append(sid)
                for checklist in actual:
                    if checklist["name"] not in {"REKVIZITY", "SET"}:
                        continue
                    for item in checklist.get("checkItems", []):
                        if "KARTA:" in item["name"] and not re.search(
                            r"\| KARTA: https://trello\.com/c/[A-Za-z0-9]+", item["name"]
                        ):
                            link_errors.append({"scene_id": sid, "item": item["name"]})
            ok = not (
                missing or card_collisions or bootstrap or checklist_errors
                or description_errors or verbatim_errors or link_errors or name_errors
            )
            return jsonify({
                "status": "verified" if ok else "blocked", "writes": 0,
                "source_count": len(scenes), "source_cards": len(source_cards),
                "missing": missing, "duplicates": list(card_collisions),
                "bootstrap_remaining": bootstrap,
                "checklist_errors": checklist_errors,
                "description_errors": description_errors,
                "verbatim_errors": verbatim_errors,
                "link_errors": link_errors, "name_errors": name_errors,
                "checked_start": start, "checked": len(selected_audit),
                "remaining": max(0, len(scenes) - start - len(selected_audit)),
            }), 200 if ok else 409

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
