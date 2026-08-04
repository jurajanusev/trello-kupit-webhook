from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from flask import jsonify, request


KEY = "cierny-kamen-spaces-props-4aug-7e3c1a9d"
BOARD_REF = "CzuD55PR"
SPACE_LIST_NAME = "REGISTER PRIESTOROV"
SPACE_MARKER_PREFIX = "<!-- CIERNY-KAMEN-SPACE:"
SPACE_AUTO_START = "<!-- CIERNY-KAMEN-SPACE-AUTO:START -->"
SPACE_AUTO_END = "<!-- CIERNY-KAMEN-SPACE-AUTO:END -->"
METADATA_START = "<!-- CIERNY-KAMEN-SCHEDULE-METADATA:START -->"
METADATA_END = "<!-- CIERNY-KAMEN-SCHEDULE-METADATA:END -->"
LAST_PROP_SYNC_UTC = datetime(2026, 7, 30, 20, 42, 43, tzinfo=timezone.utc)
SAMPLE_SCENE_ID = "01/16"
SAMPLE_SPACE_NAMES = ("DOM BETY", "DOM BETY – IZBA BETY")
SAMPLE_PROP_ORIGINAL = "infatilna magnetky z Barcelony - I love Barcelona"
SAMPLE_PROP_COMPANION = (
    "↳ Magnetka „I love Barcelona“ pre Kika — Bety ju dá Kikovi ako "
    "suvenír z Barcelony; infantilný vzhľad podľa scenára."
)

# Explicitly reviewed against the six authoritative PDFs.  Keys are Trello
# check-item IDs, so no keyword classifier can silently reinterpret a new item.
CURATED_PROP_ACTIONS = {
    "6a71945fbc40caec67ceb03a": {
        "companion": "↳ Čln Jakuba a Sáry — Jakub vesluje a Sára sedí v člne počas plavby po rieke.",
    },
    "6a7194669299d97a3395d3f4": {
        "companion": "↳ Veslá v člne Jakuba a Sáry — Jakub nimi vesluje počas plavby po rieke.",
    },
    "6a719625fdc7c5f40f736f11": {
        "companion": "↳ Výbava Matejovej skupiny na kurz prežitia — vybavenie skupiny pri výprave do lesa.",
    },
    "6a71965dfaec94d790c9ceae": {"continuity": "police_boat"},
    "6a719865853d630a4b816323": {
        "companion": "↳ Policajné pásky na brehu rieky — ohraničujú priestor pátrania po Jakubovi.",
    },
    "6a719875a0129510eedba095": {
        "companion": "↳ Výbava Alice a Ivana ako miestnych novinárov — používajú ju pri sledovaní diania na brehu rieky.",
    },
    "6a7198bef4efd47a99107f28": {
        "question": "01/09 — Upresniť konkrétny typ a vzhľad notesu pre Kelera; scenár ho explicitne neuvádza.",
    },
    "6a719943ae45a59dca37e89d": {
        "question": "01/09 — Upresniť, či má byť samostatný maják na policajné auto alebo na čln; scenár uvádza blikajúce policajné auto a policajný čln, nie samostatný maják.",
    },
    "6a71998e8737ac1319f5f5d8": {
        "companion": "↳ Dogyho spisovateľský notebook — Dogy pri ňom vo Fefe Beef píše román; rovnaký konkrétny kus v ďalších obrazoch nie je potvrdený.",
    },
    "6a719b1394c726c5945694fd": {
        "companion": "↳ Sárina šatka — pláva vo vode v paralelnom prestrihu k Sárinej verzii udalostí.",
        "question": "01/11FLASH — Potvrdiť, v ktorých obrazoch 01/02LP–01/06LP je Sárina šatka fyzicky viditeľná ako rovnaký konkrétny kus; scenár ju tam priamo neopisuje.",
    },
    "6a71b12dd19c73c066b975de": {
        "question": "01/13 — Potvrdiť, či Veronika a Laura pri príchode fyzicky vykladajú kufre a či majú priamo pokračovať do 01/14.",
    },
    "6a71b14b3bb3ecb82450baa3": {
        "question": "01/14 — Potvrdiť počet, vzhľad a fyzickú prítomnosť kufrov nadväzujúcich z 01/13.",
    },
    "6a71b4e68238aa681a30a4f7": {"companion": SAMPLE_PROP_COMPANION},
    "6a71b6331158d41e172d4a08": {
        "companion": "↳ Fefeho farebné limonády pre Bety a Alexa — obaja ich popíjajú počas stretnutia vo Fefe Beef.",
    },
    "6a71b6b07593f469c6b731b4": {
        "companion": "↳ Dva burgre v objednávke Veroniky — Fefe ich pripraví a zabalí na odnesenie.",
    },
    "6a71b6f7a303c93c2f504ce4": {
        "companion": "↳ Taška na objednávku Veroniky — Fefe do nej zabalí dva burgre a cibuľové krúžky na odnesenie.",
    },
    "6a71b7642006c9e606a0ad71": {
        "question": "01/17 — Upresniť konkrétne pitie, jedlo a počet kusov určených pre komparz; scenár ich explicitne neuvádza.",
    },
}

POLICE_BOAT_KEY = "policajny-cln-patracieho-timu"
POLICE_BOAT_NAME = "Policajný čln pátracieho tímu"
POLICE_BOAT_SCENES = ("01/08LP", "01/09")

# These are source-specific, reviewed equivalences.  This is intentionally not
# a fuzzy matcher: an unlisted spelling remains a separate dry-run candidate.
EXPLICIT_ALIASES = {
    "ALEXOVA DOM – ALEXOVA IZBA": "ALEXOV DOM – ALEXOVA IZBA",
    "BETIN DOM – BETINA IZBA": "DOM BETY – IZBA BETY",
    "BETIN DOM – OBÝVAČKA": "DOM BETY – OBÝVAČKA",
    "IZBA BETY": "DOM BETY – IZBA BETY",
    "KELEROV DOM – PRACOVŇA": "KELEROV DOM – PRACOVŇA",
    "RÉVAYOVA VILA – HALA SO SCHODISKOM": "VILA RÉVAYOVCOV – HALA (SCHODISKO)",
    "RÉVAYOVA VILA – OBÝVAČKA": "VILA RÉVAYOVCOV – OBÝVAČKA",
    "VILA RÉVEYOVCOV – SÁRINA IZBA (ŠATNÍK)": "VILA RÉVAYOVCOV – SÁRINA IZBA (ŠATNÍK)",
    "VERONIKIN DOM – OBÝVAČKA": "VERONIKINA VILA – OBÝVAČKA",
    "DOM VERONIKA": "VERONIKINA VILA",
    "KANCELÁRIA PRIMÁTORKY": "RADNICA – KANCELÁRIA PRIMÁTORKY",
    "ŠKOLA HUDOBNÁ MIESTNOSŤ": "ŠKOLA – HUDOBNÁ MIESTNOSŤ",
    "ŠKOLA – DIVADELNÁ SÁLA (HĽADISKO)": "ŠKOLA – DIVADELNÁ SÁLA – HĽADISKO",
    "ŠKOLA – DIVADELNÁ SÁLA (PÓDIUM)": "ŠKOLA – DIVADELNÁ SÁLA – PÓDIUM",
}

# A slash or plus is not globally treated as a separator.  Only combinations
# explicitly present and reviewed in the six authoritative PDFs are split.
EXPLICIT_MULTI_SPACES = {
    "BREH RIEKY + LES": ("BREH RIEKY", "LES"),
    "ŠKOLA – CHODBA S UČEBŇAMI/HUDOBNÁ MIESTNOSŤ": (
        "ŠKOLA – CHODBA S UČEBŇAMI",
        "ŠKOLA – HUDOBNÁ MIESTNOSŤ",
    ),
    "VERONIKINA VILA – VSTUP/JEDÁLEŇ": (
        "VERONIKINA VILA – VSTUP",
        "VERONIKINA VILA – JEDÁLEŇ",
    ),
    "FEFE BEEF – VSTUP/PRI STOLE": (
        "FEFE BEEF – VSTUP",
        "FEFE BEEF – PRI STOLE",
    ),
    "DOM BETY – OBÝVAČKA/KUCHYŇA": (
        "DOM BETY – OBÝVAČKA",
        "DOM BETY – KUCHYŇA",
    ),
    "DOM BETY – OBÝVAČKA/VSTUP": (
        "DOM BETY – OBÝVAČKA",
        "DOM BETY – VSTUP",
    ),
    "ÚSTAV – CHODBA/VSTUP": ("ÚSTAV – CHODBA", "ÚSTAV – VSTUP"),
    "ÚSTAV – CHODBA/SOFIINA IZBA": (
        "ÚSTAV – CHODBA",
        "ÚSTAV – SOFIINA IZBA",
    ),
}

# Similar-looking names that must not be silently merged by the first run.
AMBIGUOUS_SOURCE_NAMES = {
    "AMFITEÁTER – PREMIETACIA MESTNOSŤ": (
        "Je to tá istá miestnosť ako AMFITEÁTER – PREMIETACIA KABÍNKA?"
    ),
    "ŠKOLA – HUDOBNÁ TRIEDA": (
        "Je HUDOBNÁ TRIEDA totožná s HUDOBNOU MIESTNOSŤOU?"
    ),
    "ŠKOLSKÉ DIVADLO": (
        "Je ŠKOLSKÉ DIVADLO totožné so ŠKOLA – DIVADELNÁ SÁLA?"
    ),
}


def folded(value):
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", value).strip().casefold()


def slug(value):
    value = folded(value)
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "space"


def normalize_source_location(value):
    value = (value or "").strip()
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\s*[-–—]\s*", " – ", value)
    value = re.sub(r"\s*,\s*", ", ", value)
    # PDF shooting-day remnants, not part of the story-space identity.
    value = re.sub(
        r"\s+–\s+(?:DAY|NIGHT)\s+[A-Z0-9]+$", "", value,
        flags=re.I,
    )
    value = re.sub(r",\s*NIGHT\s+\d+$", "", value, flags=re.I)
    return value.strip()


def canonical_locations(raw):
    normalized = normalize_source_location(raw)
    normalized = EXPLICIT_ALIASES.get(normalized, normalized)
    values = EXPLICIT_MULTI_SPACES.get(normalized, (normalized,))
    return tuple(EXPLICIT_ALIASES.get(item, item) for item in values)


def parent_space(name):
    if " – " not in name:
        return None
    parent = name.split(" – ", 1)[0].strip()
    if parent in {
        "ŠKOLA", "DOM BETY", "ALEXOV DOM", "VERONIKINA VILA",
        "VILA RÉVAYOVCOV", "EVINA VILA", "KELEROV DOM", "FEFE BEEF",
        "AMFITEÁTER", "LUKÁŠOVA FIRMA", "RADNICA", "ÚSTAV",
    }:
        return parent
    return None


def build_space_catalog(payload):
    entries = {}
    ambiguous = []
    scene_locations = {}
    for scene in payload["scenes"]:
        raw = scene.get("location", "").strip()
        normalized = normalize_source_location(raw)
        names = canonical_locations(raw)
        if normalized in AMBIGUOUS_SOURCE_NAMES:
            ambiguous.append({
                "scene_id": scene["scene_id"],
                "source": raw,
                "question": AMBIGUOUS_SOURCE_NAMES[normalized],
            })
            scene_locations[scene["scene_id"]] = []
            continue
        scene_locations[scene["scene_id"]] = list(names)
        for name in names:
            entry = entries.setdefault(name, {
                "key": slug(name),
                "name": name,
                "aliases": set(),
                "parent": parent_space(name),
                "scenes": [],
                "int_ext": set(),
            })
            entry["aliases"].add(raw)
            entry["scenes"].append(scene["scene_id"])
            heading = (scene.get("heading") or "").strip().upper()
            if heading.startswith("INT."):
                entry["int_ext"].add("INT")
            elif heading.startswith("EXT."):
                entry["int_ext"].add("EXT")
        for name in names:
            parent = parent_space(name)
            if parent and parent not in entries:
                entries[parent] = {
                    "key": slug(parent),
                    "name": parent,
                    "aliases": {parent},
                    "parent": None,
                    "scenes": [],
                    "int_ext": set(),
                }
    # Set insertion can add a parent while iterating later scenes; normalize all.
    for entry in entries.values():
        entry["aliases"] = sorted(entry["aliases"])
        entry["scenes"] = sorted(set(entry["scenes"]))
        entry["int_ext"] = sorted(entry["int_ext"]) or ["NEURČENÉ"]
    key_groups = defaultdict(list)
    for entry in entries.values():
        key_groups[entry["key"]].append(entry["name"])
    key_collisions = {
        key: names for key, names in key_groups.items() if len(names) > 1
    }
    return {
        "entries": entries,
        "scene_locations": scene_locations,
        "ambiguous": ambiguous,
        "key_collisions": key_collisions,
    }


def stable_json_hash(value):
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def trello_object_created_at(object_id):
    if not re.fullmatch(r"[0-9a-fA-F]{24}", object_id or ""):
        return None
    return datetime.fromtimestamp(int(object_id[:8], 16), timezone.utc)


def description_without_location(desc):
    if METADATA_START not in (desc or "") or METADATA_END not in desc:
        return None
    before, tail = desc.split(METADATA_START, 1)
    metadata, after = tail.split(METADATA_END, 1)
    lines = metadata.splitlines()
    location_indexes = [
        index for index, line in enumerate(lines)
        if folded(line).startswith("lokacia:")
        or folded(line).startswith("lokacie:")
    ]
    if len(location_indexes) != 1:
        return None
    lines[location_indexes[0]] = "LOKÁCIA: <AUTOMATICKÁ-HODNOTA>"
    return before + METADATA_START + "\n".join(lines) + METADATA_END + after


def replace_location_value(desc, markdown_value):
    if description_without_location(desc) is None:
        raise RuntimeError("metadata boundary/location mismatch")
    before, tail = desc.split(METADATA_START, 1)
    metadata, after = tail.split(METADATA_END, 1)
    lines = metadata.splitlines()
    location_indexes = [
        index for index, line in enumerate(lines)
        if folded(line).startswith("lokacia:")
        or folded(line).startswith("lokacie:")
    ]
    label = "LOKÁCIE" if ", " in markdown_value else "LOKÁCIA"
    lines[location_indexes[0]] = f"{label}: {markdown_value}"
    return before + METADATA_START + "\n".join(lines) + METADATA_END + after


def space_marker(key):
    return f"<!-- CIERNY-KAMEN-SPACE:{key} -->"


def replace_space_auto_block(actual, desired):
    if SPACE_AUTO_START not in desired or SPACE_AUTO_END not in desired:
        raise RuntimeError("desired space auto boundary missing")
    desired_auto = desired[
        desired.index(SPACE_AUTO_START):
        desired.index(SPACE_AUTO_END) + len(SPACE_AUTO_END)
    ]
    if SPACE_AUTO_START in (actual or "") and SPACE_AUTO_END in actual:
        current_auto = actual[
            actual.index(SPACE_AUTO_START):
            actual.index(SPACE_AUTO_END) + len(SPACE_AUTO_END)
        ]
        return actual.replace(current_auto, desired_auto, 1)
    return desired


def space_description(entry, scene_cards, space_urls, catalog, payload):
    parent = entry.get("parent")
    parent_text = (
        f"[{parent}]({space_urls[parent]})"
        if parent and space_urls.get(parent) else (parent or "—")
    )
    children = sorted(
        item["name"] for item in catalog["entries"].values()
        if item.get("parent") == entry["name"] and space_urls.get(item["name"])
    )
    child_text = ", ".join(
        f"[{name}]({space_urls[name]})" for name in children
    ) or "—"
    aliases = ", ".join(entry.get("aliases") or [entry["name"]])
    scenes = [
        f"- [{scene_id}]({scene_cards[scene_id].get('shortUrl')})"
        for scene_id in entry.get("scenes", []) if scene_id in scene_cards
    ] or ["- Bez priamej obrazovej karty; hierarchický rodič."]
    source_by_id = {scene["scene_id"]: scene for scene in payload["scenes"]}
    changes = []
    for scene_id in entry.get("scenes", []):
        for item in source_by_id.get(scene_id, {}).get("set_items", []):
            if item.get("continuity"):
                changes.append(
                    f"- [{scene_id}]({scene_cards[scene_id].get('shortUrl')}) — "
                    f"{item.get('current_state') or item.get('action')}"
                )
    if not changes:
        changes = ["- Bez potvrdenej špecifickej zmeny stavu priestoru."]
    return (
        f"{space_marker(entry['key'])}\n"
        f"{SPACE_AUTO_START}\n"
        "# REGISTER PRIESTORU\n\n"
        f"**KANONICKÝ NÁZOV:** {entry['name']}\n\n"
        f"**ALIASY:** {aliases}\n\n"
        f"**NADRADENÝ PRIESTOR:** {parent_text}\n\n"
        f"**PODPRIESTORY:** {child_text}\n\n"
        f"**INT/EXT:** {', '.join(entry.get('int_ext') or ['NEURČENÉ'])}\n\n"
        "**ZÁKLADNÝ VZHĽAD/DRESSING:** V autoritatívnom PDF nie je "
        "jednoznačne určený; ručné poznámky, fotografie a pôdorysy sú "
        "chránené.\n\n"
        "## ODKAZY NA OBRAZOVÉ KARTY\n"
        f"{chr(10).join(scenes)}\n\n"
        "## ČASOVÁ OS ŠPECIFICKÝCH ZMIEN\n"
        f"{chr(10).join(changes)}\n"
        f"{SPACE_AUTO_END}\n\n"
        "## NATÁČACIA LOKÁCIA (RUČNE)\n\n"
        "## RUČNÉ POZNÁMKY / FOTKY / PÔDORYSY\n"
    )


def original_checklist_projection(checklists):
    return {
        checklist.get("id"): {
            "name": checklist.get("name"),
            "pos": checklist.get("pos"),
            "items": {
                item.get("id"): {
                    "name": item.get("name"),
                    "state": item.get("state"),
                    "pos": item.get("pos"),
                }
                for item in checklist.get("checkItems", [])
            },
        }
        for checklist in checklists
    }


def projection_is_preserved(before, after):
    after_projection = original_checklist_projection(after)
    for checklist_id, expected in before.items():
        actual = after_projection.get(checklist_id)
        if not actual or actual["name"] != expected["name"]:
            return False
        for item_id, expected_item in expected["items"].items():
            if actual["items"].get(item_id) != expected_item:
                return False
    return True


def ensure_attachment(api, card, url, name):
    attachments = api["trello_get"](
        f"/cards/{card['id']}/attachments", {"fields": "id,name,url"}
    )
    if any(item.get("url") == url for item in attachments):
        return False
    api["trello_post_body"](
        f"/cards/{card['id']}/attachments", {"url": url, "name": name}
    )
    return True


def expected_prop_names(api, payload, state):
    prop_cards, prop_duplicates = api["cierny_kamen_registry_cards"](
        state, "PROP", payload
    )
    set_cards, set_duplicates = api["cierny_kamen_registry_cards"](
        state, "SET", payload
    )
    if prop_duplicates or set_duplicates:
        return {}, {"PROP": prop_duplicates, "SET": set_duplicates}
    prop_urls = {key: card.get("shortUrl") for key, card in prop_cards.items()}
    set_urls = {key: card.get("shortUrl") for key, card in set_cards.items()}
    result = {}
    for scene in payload["scenes"]:
        try:
            result[scene["scene_id"]] = set(
                api["cierny_kamen_scene_checklists"](
                    scene, prop_urls, set_urls
                )["REKVIZITY"]
            )
        except KeyError:
            result[scene["scene_id"]] = set()
    return result, {}


def checklist_map(api, board_id):
    checklists = api["trello_get"](f"/boards/{board_id}/checklists", {
        "checkItems": "all", "fields": "id,name,idCard,pos", "filter": "all",
    })
    result = defaultdict(list)
    for checklist in checklists:
        result[checklist.get("idCard")].append(checklist)
    return result


def protected_snapshot(
    scene_cards, checklists_by_card, attachments_by_card, comments_by_card
):
    cards = []
    invalid_metadata = []
    for scene_id, card in sorted(scene_cards.items()):
        protected_desc = description_without_location(card.get("desc") or "")
        if protected_desc is None:
            invalid_metadata.append(scene_id)
        checklists = sorted(
            checklists_by_card.get(card["id"], []),
            key=lambda item: item.get("pos", 0),
        )
        cards.append({
            "scene_id": scene_id,
            "card_id": card["id"],
            "protected_description": protected_desc,
            "labels": sorted(card.get("idLabels", [])),
            "attachments": sorted(
                attachments_by_card.get(card["id"], []),
                key=lambda item: item.get("id", ""),
            ),
            "comments": sorted(
                comments_by_card.get(card["id"], []),
                key=lambda item: item.get("id", ""),
            ),
            "checklists": [
                {
                    "id": checklist.get("id"),
                    "name": checklist.get("name"),
                    "pos": checklist.get("pos"),
                    "items": [
                        {
                            "id": item.get("id"),
                            "name": item.get("name"),
                            "state": item.get("state"),
                            "pos": item.get("pos"),
                        }
                        for item in sorted(
                            checklist.get("checkItems", []),
                            key=lambda value: value.get("pos", 0),
                        )
                    ],
                }
                for checklist in checklists
            ],
        })
    return {
        "sha256": stable_json_hash(cards),
        "cards": len(cards),
        "checklists": sum(len(card["checklists"]) for card in cards),
        "items": sum(
            len(checklist["items"])
            for card in cards for checklist in card["checklists"]
        ),
        "attachments": sum(len(card["attachments"]) for card in cards),
        "comments": sum(len(card["comments"]) for card in cards),
        "invalid_metadata": invalid_metadata,
    }


def register_routes(flask_app, api):
    root = Path(api["__file__"]).parent

    @flask_app.route("/api/audit-cierny-kamen-spaces-props", methods=["POST"])
    def audit_cierny_kamen_spaces_props():
        if request.headers.get("X-Spaces-Props-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "dry-run").strip().casefold()
        if mode not in {
            "audit", "dry-run", "sample-dry-run", "sample-apply",
            "sample-audit", "registry-create-dry-run",
            "registry-create-apply", "registry-update-dry-run",
            "registry-update-apply", "scene-links-dry-run",
            "scene-links-apply", "props-dry-run", "props-apply",
            "ambiguity-dry-run", "ambiguity-apply", "final-audit",
        }:
            return jsonify({
                "error": "unsupported mode"
            }), 400
        try:
            start = int(request.args.get("start", "0"))
            limit = int(request.args.get("limit", "10"))
        except ValueError:
            return jsonify({"error": "start and limit must be integers"}), 400
        if start < 0 or limit < 1 or limit > 10:
            return jsonify({"error": "invalid start/limit"}), 400

        payload = api["cierny_kamen_import_payload"]()
        state = api["cierny_kamen_import_state"](payload)
        source_ids = {scene["scene_id"] for scene in payload["scenes"]}
        raw_scene_cards = api["cierny_kamen_scene_cards_by_id"](state)
        collisions = {
            scene_id: [
                {"name": card.get("name"), "url": card.get("shortUrl")}
                for card in cards
            ]
            for scene_id, cards in raw_scene_cards.items()
            if scene_id in source_ids and len(cards) != 1
        }
        missing = sorted(source_ids - set(raw_scene_cards))
        unexpected = sorted(set(raw_scene_cards) - source_ids)
        scene_cards = {
            scene_id: cards[0]
            for scene_id, cards in raw_scene_cards.items()
            if scene_id in source_ids and len(cards) == 1
        }

        lists = state["lists"]
        space_lists = api["cierny_kamen_exact_named"](
            lists, SPACE_LIST_NAME
        )
        space_cards = [
            card for card in state["cards"]
            if space_lists and card.get("idList") == space_lists[0]["id"]
            and not card.get("closed")
        ]
        marker_cards = defaultdict(list)
        for card in space_cards:
            match = re.search(
                r"<!-- CIERNY-KAMEN-SPACE:([^>]+) -->",
                card.get("desc") or "",
            )
            if match:
                marker_cards[match.group(1)].append(card)

        catalog = build_space_catalog(payload)
        existing_space_duplicates = {
            key: [
                {"name": card.get("name"), "url": card.get("shortUrl")}
                for card in cards
            ]
            for key, cards in marker_cards.items() if len(cards) > 1
        }
        existing_space_keys = {
            key for key, cards in marker_cards.items() if len(cards) == 1
        }

        try:
            checklists_by_card = checklist_map(api, state["board"]["id"])
        except Exception as exc:
            return jsonify({
                "status": "blocked",
                "writes": 0,
                "blockers": [f"board checklist read failed: {exc}"],
            }), 409

        try:
            attachment_cards = api["trello_get"](
                f"/boards/{state['board']['id']}/cards", {
                    "fields": "id", "filter": "open", "limit": 1000,
                    "attachments": "true",
                    "attachment_fields": "id,name,url,bytes,date",
                },
            )
            attachments_by_card = {
                card["id"]: [
                    {
                        "id": item.get("id"), "name": item.get("name"),
                        "url": item.get("url"), "bytes": item.get("bytes"),
                        "date": item.get("date"),
                    }
                    for item in card.get("attachments", [])
                ]
                for card in attachment_cards
            }
            comment_actions = api["trello_get"](
                f"/boards/{state['board']['id']}/actions", {
                    "filter": "commentCard", "limit": 1000,
                    "fields": "id,data,date,idMemberCreator",
                },
            )
            comments_by_card = defaultdict(list)
            for action in comment_actions:
                card_id = (action.get("data") or {}).get("card", {}).get("id")
                if card_id:
                    comments_by_card[card_id].append({
                        "id": action.get("id"),
                        "text": (action.get("data") or {}).get("text"),
                        "date": action.get("date"),
                        "member": action.get("idMemberCreator"),
                    })
        except Exception as exc:
            return jsonify({
                "status": "blocked", "writes": 0,
                "blockers": [f"protected attachments/comments read failed: {exc}"],
            }), 409

        expected_props, registry_duplicates = expected_prop_names(
            api, payload, state
        )
        manual_prop_candidates = []
        cards_with_required_checklists = 0
        checklist_order_conflicts = []
        required = api["CIERNY_KAMEN_IMPORT_CHECKLISTS"]
        for scene_id, card in sorted(scene_cards.items()):
            checklists = sorted(
                checklists_by_card.get(card["id"], []),
                key=lambda item: item.get("pos", 0),
            )
            names = [item.get("name") for item in checklists]
            if names == required:
                cards_with_required_checklists += 1
            else:
                checklist_order_conflicts.append({
                    "scene_id": scene_id, "names": names,
                    "url": card.get("shortUrl"),
                })
            prop_lists = [
                item for item in checklists
                if folded(item.get("name")) == folded("REKVIZITY")
            ]
            if len(prop_lists) != 1:
                continue
            known = expected_props.get(scene_id, set())
            for item in sorted(
                prop_lists[0].get("checkItems", []),
                key=lambda value: value.get("pos", 0),
            ):
                name = item.get("name") or ""
                if name in known or name.startswith("↳ "):
                    continue
                manual_prop_candidates.append({
                    "scene_id": scene_id,
                    "card_name": card.get("name"),
                    "card_url": card.get("shortUrl"),
                    "checklist_id": prop_lists[0].get("id"),
                    "item_id": item.get("id"),
                    "name": name,
                    "state": item.get("state"),
                    "created_at": (
                        trello_object_created_at(item.get("id")).isoformat()
                        if trello_object_created_at(item.get("id")) else None
                    ),
                    "eligible_new_since_last_sync": bool(
                        trello_object_created_at(item.get("id"))
                        and trello_object_created_at(item.get("id"))
                        > LAST_PROP_SYNC_UTC
                    ),
                })

        snapshot = protected_snapshot(
            scene_cards, checklists_by_card,
            attachments_by_card, comments_by_card,
        )
        planned_location_updates = sum(
            bool(catalog["scene_locations"].get(scene_id))
            for scene_id in scene_cards
        )
        blockers = []
        if len(scene_cards) != len(source_ids):
            blockers.append("scene card count is not 313/313")
        if collisions:
            blockers.append("scene ID collisions exist")
        if missing:
            blockers.append("source scene IDs are missing")
        if len(space_lists) > 1:
            blockers.append("multiple open REGISTER PRIESTOROV lists")
        if existing_space_duplicates:
            blockers.append("duplicate space registry markers")
        if catalog["key_collisions"]:
            blockers.append("space key collisions")
        if snapshot["invalid_metadata"]:
            blockers.append("scene metadata boundary/location mismatch")
        if registry_duplicates:
            blockers.append("existing prop/set registry marker duplicates")
        if checklist_order_conflicts:
            blockers.append("scene checklist order/name conflicts")
        if len(comment_actions) >= 1000:
            blockers.append("comment snapshot reached Trello limit")

        result = {
            "status": "read-only-dry-run",
            "writes": 0,
            "board": {
                "id": state["board"]["id"],
                "name": state["board"].get("name"),
                "url": state["board"].get("url"),
                "ref": BOARD_REF,
            },
            "source": {
                "scene_cards_expected": len(source_ids),
                "source_pdfs": len(payload.get("source_pdfs", [])),
                "raw_location_values": len({
                    scene.get("location", "") for scene in payload["scenes"]
                }),
            },
            "scenes": {
                "matched_unique": len(scene_cards),
                "missing": missing,
                "collisions": collisions,
                "unexpected_scene_ids": unexpected,
                "complete_checklist_structure": cards_with_required_checklists,
                "checklist_conflicts_count": len(checklist_order_conflicts),
                "checklist_conflicts": checklist_order_conflicts[:30],
            },
            "spaces": {
                "target_list": [
                    {"id": item["id"], "name": item.get("name")}
                    for item in space_lists
                ],
                "target_list_will_be_created": not space_lists,
                "canonical_cards_proposed": len(catalog["entries"]),
                "existing_marked_cards": len(existing_space_keys),
                "cards_to_create": len(
                    set(item["key"] for item in catalog["entries"].values())
                    - existing_space_keys
                ),
                "unambiguous_scene_matches": planned_location_updates,
                "ambiguous_scene_matches": len(catalog["ambiguous"]),
                "ambiguous": catalog["ambiguous"],
                "key_collisions": catalog["key_collisions"],
                "existing_marker_duplicates": existing_space_duplicates,
                "location_updates_planned": planned_location_updates,
                "sample": [
                    {
                        "name": entry["name"],
                        "aliases": entry["aliases"],
                        "parent": entry["parent"],
                        "int_ext": entry["int_ext"],
                        "scene_count": len(entry["scenes"]),
                    }
                    for entry in list(sorted(
                        catalog["entries"].values(),
                        key=lambda item: item["name"],
                    ))[:25]
                ],
            },
            "props": {
                "manual_or_changed_candidates": len(manual_prop_candidates),
                "new_since_last_sync": sum(
                    item["eligible_new_since_last_sync"]
                    for item in manual_prop_candidates
                ),
                "legacy_conflicts_not_eligible": sum(
                    not item["eligible_new_since_last_sync"]
                    for item in manual_prop_candidates
                ),
                "last_sync_utc": LAST_PROP_SYNC_UTC.isoformat(),
                "candidates": manual_prop_candidates,
                "automatic_action_planned": 0,
                "reason": (
                    "No persisted prior manual-item sync state exists; "
                    "candidates require explicit evidence review before apply."
                ),
            },
            "protected_snapshot": snapshot,
            "planned_writes": {
                "lists": 1 if not space_lists else 0,
                "space_cards": len(
                    set(item["key"] for item in catalog["entries"].values())
                    - existing_space_keys
                ),
                "scene_location_fields": planned_location_updates,
                "prop_items": 0,
                "manual_items_modified": 0,
                "scene_labels_modified": 0,
            },
            "blockers": blockers,
            "valid_for_sample": not blockers,
        }
        if mode in {"audit", "dry-run"}:
            return jsonify(result), 200
        if blockers:
            return jsonify({**result, "status": "blocked"}), 409

        ordered_entries = sorted(
            catalog["entries"].values(), key=lambda item: item["name"]
        )
        if mode in {"registry-create-dry-run", "registry-create-apply"}:
            if len(space_lists) != 1:
                return jsonify({
                    "status": "blocked", "writes": 0,
                    "errors": ["expected existing REGISTER PRIESTOROV list"],
                }), 409
            selected = ordered_entries[start:start + limit]
            operations = []
            errors = []
            writes = 0
            for entry in selected:
                matches = marker_cards.get(entry["key"], [])
                if len(matches) == 1:
                    operations.append({"name": entry["name"], "action": "unchanged"})
                    continue
                exact_unmarked = [
                    card for card in space_cards
                    if folded(card.get("name")) == folded(entry["name"])
                    and SPACE_MARKER_PREFIX not in (card.get("desc") or "")
                ]
                if exact_unmarked:
                    errors.append({
                        "name": entry["name"], "error": "unmarked exact-name card exists",
                    })
                    continue
                operations.append({"name": entry["name"], "action": "create"})
                if mode == "registry-create-apply":
                    api["trello_post_body"]("/cards", {
                        "idList": space_lists[0]["id"],
                        "name": entry["name"],
                        "desc": space_marker(entry["key"]), "pos": "bottom",
                    })
                    writes += 1
            return jsonify({
                "status": mode, "writes": writes, "start": start,
                "selected": len(selected), "operations": operations,
                "errors": errors,
                "remaining": max(0, len(ordered_entries) - start - len(selected)),
            }), 200 if not errors else 409

        all_space_cards = {}
        for entry in ordered_entries:
            matches = marker_cards.get(entry["key"], [])
            if len(matches) == 1:
                all_space_cards[entry["name"]] = matches[0]
        if mode in {
            "registry-update-dry-run", "registry-update-apply",
            "scene-links-dry-run", "scene-links-apply",
            "ambiguity-dry-run", "ambiguity-apply", "final-audit",
        } and len(all_space_cards) != len(ordered_entries):
            return jsonify({
                "status": "blocked", "writes": 0,
                "errors": [
                    f"expected {len(ordered_entries)} unique space cards, found "
                    f"{len(all_space_cards)}"
                ],
            }), 409
        all_space_urls = {
            name: card.get("shortUrl") for name, card in all_space_cards.items()
        }

        if mode in {"registry-update-dry-run", "registry-update-apply"}:
            selected = ordered_entries[start:start + limit]
            operations = []
            writes = 0
            for entry in selected:
                card = all_space_cards[entry["name"]]
                desired = space_description(
                    entry, scene_cards, all_space_urls, catalog, payload
                )
                desired = replace_space_auto_block(card.get("desc") or "", desired)
                changed = card.get("name") != entry["name"] or card.get("desc") != desired
                operations.append({"name": entry["name"], "changed": changed})
                if mode == "registry-update-apply" and changed:
                    api["trello_put_body"](
                        f"/cards/{card['id']}",
                        {"name": entry["name"], "desc": desired},
                    )
                    writes += 1
                if mode == "registry-update-apply" and entry.get("parent"):
                    parent_card = all_space_cards[entry["parent"]]
                    if ensure_attachment(
                        api, parent_card, card.get("shortUrl"), entry["name"]
                    ):
                        writes += 1
                    if ensure_attachment(
                        api, card, parent_card.get("shortUrl"), entry["parent"]
                    ):
                        writes += 1
            return jsonify({
                "status": mode, "writes": writes, "start": start,
                "selected": len(selected), "operations": operations,
                "remaining": max(0, len(ordered_entries) - start - len(selected)),
            }), 200

        ordered_scenes = [
            scene for scene in payload["scenes"]
            if catalog["scene_locations"].get(scene["scene_id"])
        ]
        if mode in {"scene-links-dry-run", "scene-links-apply"}:
            selected = ordered_scenes[start:start + limit]
            operations = []
            errors = []
            writes = 0
            for scene in selected:
                scene_id = scene["scene_id"]
                card = scene_cards[scene_id]
                names = catalog["scene_locations"][scene_id]
                markdown = ", ".join(
                    f"[{name}]({all_space_urls[name]})" for name in names
                )
                desired = replace_location_value(card.get("desc") or "", markdown)
                changed = desired != card.get("desc")
                operations.append({
                    "scene_id": scene_id, "changed": changed,
                    "spaces": names, "url": card.get("shortUrl"),
                })
                if mode != "scene-links-apply":
                    continue
                before_desc = description_without_location(card.get("desc") or "")
                before_labels = sorted(card.get("idLabels", []))
                before_checklists = original_checklist_projection(
                    checklists_by_card.get(card["id"], [])
                )
                before_attachments = {
                    item.get("id"): item
                    for item in attachments_by_card.get(card["id"], [])
                }
                before_comments = sorted(
                    comments_by_card.get(card["id"], []),
                    key=lambda item: item.get("id", ""),
                )
                if changed:
                    api["trello_put_body"](
                        f"/cards/{card['id']}", {"desc": desired}
                    )
                    writes += 1
                for name in names:
                    space_card = all_space_cards[name]
                    if ensure_attachment(
                        api, card, space_card.get("shortUrl"), name
                    ):
                        writes += 1
                    if ensure_attachment(
                        api, space_card, card.get("shortUrl"), scene_id
                    ):
                        writes += 1
                after_card = api["trello_get"](
                    f"/cards/{card['id']}",
                    {"fields": "id,desc,idLabels,shortUrl"},
                )
                after_checklists = api["trello_get"](
                    f"/cards/{card['id']}/checklists",
                    {"checkItems": "all", "fields": "id,name,pos"},
                )
                after_attachments_list = api["trello_get"](
                    f"/cards/{card['id']}/attachments",
                    {"fields": "id,name,url,bytes,date"},
                )
                after_attachments = {
                    item.get("id"): {
                        "id": item.get("id"), "name": item.get("name"),
                        "url": item.get("url"), "bytes": item.get("bytes"),
                        "date": item.get("date"),
                    }
                    for item in after_attachments_list
                }
                actions = api["trello_get"](
                    f"/cards/{card['id']}/actions",
                    {"filter": "commentCard", "limit": 1000},
                )
                after_comments = sorted([
                    {
                        "id": action.get("id"),
                        "text": (action.get("data") or {}).get("text"),
                        "date": action.get("date"),
                        "member": action.get("idMemberCreator"),
                    }
                    for action in actions
                ], key=lambda item: item.get("id", ""))
                protected = (
                    before_desc == description_without_location(after_card.get("desc") or "")
                    and before_labels == sorted(after_card.get("idLabels", []))
                    and projection_is_preserved(before_checklists, after_checklists)
                    and all(after_attachments.get(key) == value
                            for key, value in before_attachments.items())
                    and before_comments == after_comments
                )
                if not protected:
                    errors.append({"scene_id": scene_id, "error": "protected data changed"})
                    break
            return jsonify({
                "status": mode, "writes": writes, "start": start,
                "selected": len(selected), "operations": operations,
                "errors": errors,
                "remaining": max(0, len(ordered_scenes) - start - len(selected)),
            }), 200 if not errors else 409

        if mode in {"ambiguity-dry-run", "ambiguity-apply"}:
            selected = catalog["ambiguous"][start:start + limit]
            operations = []
            errors = []
            writes = 0
            for ambiguous in selected:
                scene_id = ambiguous["scene_id"]
                card = scene_cards[scene_id]
                question = (
                    f"{scene_id} — Nejednoznačná identita priestoru „"
                    f"{ambiguous['source']}“: {ambiguous['question']}"
                )
                checklists = checklists_by_card.get(card["id"], [])
                question_checklist = next(
                    item for item in checklists
                    if folded(item.get("name")) == folded("OTÁZKY NA PORADU")
                )
                existing = {
                    item.get("name")
                    for item in question_checklist.get("checkItems", [])
                }
                operations.append({
                    "scene_id": scene_id, "source": ambiguous["source"],
                    "question": question, "already_present": question in existing,
                })
                if mode != "ambiguity-apply" or question in existing:
                    continue
                before = original_checklist_projection(checklists)
                api["trello_post_body"](
                    f"/checklists/{question_checklist['id']}/checkItems",
                    {"name": question, "pos": "bottom"},
                )
                writes += 1
                after = api["trello_get"](
                    f"/cards/{card['id']}/checklists",
                    {"checkItems": "all", "fields": "id,name,pos"},
                )
                if not projection_is_preserved(before, after):
                    errors.append({
                        "scene_id": scene_id,
                        "error": "pre-existing checklist data changed",
                    })
                    break
            return jsonify({
                "status": mode, "writes": writes, "start": start,
                "selected": len(selected), "operations": operations,
                "errors": errors,
                "remaining": max(
                    0, len(catalog["ambiguous"]) - start - len(selected)
                ),
            }), 200 if not errors else 409

        eligible_props = sorted(
            [
                item for item in manual_prop_candidates
                if item["eligible_new_since_last_sync"]
            ],
            key=lambda item: (item["created_at"] or "", item["item_id"]),
        )
        missing_curation = [
            item for item in eligible_props
            if item["item_id"] not in CURATED_PROP_ACTIONS
        ]
        if mode in {"props-dry-run", "props-apply"}:
            if missing_curation:
                return jsonify({
                    "status": "blocked", "writes": 0,
                    "errors": [{"item": item["name"], "id": item["item_id"]}
                               for item in missing_curation],
                }), 409
            selected = eligible_props[start:start + limit]
            operations = []
            writes = 0
            errors = []
            protected_before = {}
            if mode == "props-apply":
                touched_scene_ids = {item["scene_id"] for item in selected}
                if any(
                    CURATED_PROP_ACTIONS[item["item_id"]].get("continuity")
                    == "police_boat" for item in selected
                ):
                    touched_scene_ids.update(POLICE_BOAT_SCENES)
                for scene_id in touched_scene_ids:
                    protected_card = scene_cards[scene_id]
                    protected_before[protected_card["id"]] = {
                        "scene_id": scene_id,
                        "desc": protected_card.get("desc") or "",
                        "labels": set(protected_card.get("idLabels", [])),
                        "checklists": original_checklist_projection(
                            checklists_by_card.get(protected_card["id"], [])
                        ),
                        "attachments": {
                            item.get("id"): item
                            for item in attachments_by_card.get(
                                protected_card["id"], []
                            )
                        },
                        "comments": sorted(
                            comments_by_card.get(protected_card["id"], []),
                            key=lambda item: item.get("id", ""),
                        ),
                    }

            police_master = None
            police_url = None
            if any(
                CURATED_PROP_ACTIONS[item["item_id"]].get("continuity")
                == "police_boat" for item in selected
            ):
                prop_lists = api["cierny_kamen_exact_named"](
                    state["lists"], payload["prop_registry_list_name"]
                )
                if len(prop_lists) != 1:
                    return jsonify({"status": "blocked", "writes": 0,
                                    "errors": ["prop registry list mismatch"]}), 409
                prop_cards = [
                    card for card in state["cards"]
                    if card.get("idList") == prop_lists[0]["id"]
                    and not card.get("closed")
                    and (
                        f"<!-- CIERNY-KAMEN-NATURAL-PROP:{POLICE_BOAT_KEY} -->"
                        in (card.get("desc") or "")
                        or folded(card.get("name")) == folded(POLICE_BOAT_NAME)
                    )
                ]
                if len(prop_cards) > 1:
                    return jsonify({"status": "blocked", "writes": 0,
                                    "errors": ["duplicate police boat registry"]}), 409
                if prop_cards:
                    police_master = prop_cards[0]
                elif mode == "props-apply":
                    police_master = api["trello_post_body"]("/cards", {
                        "idList": prop_lists[0]["id"], "name": POLICE_BOAT_NAME,
                        "desc": f"<!-- CIERNY-KAMEN-NATURAL-PROP:{POLICE_BOAT_KEY} -->",
                        "pos": "bottom",
                    })
                    writes += 1
                if police_master:
                    police_url = police_master.get("shortUrl")
                    desired_master = (
                        f"<!-- CIERNY-KAMEN-NATURAL-PROP:{POLICE_BOAT_KEY} -->\n"
                        "<!-- CIERNY-KAMEN-NATURAL-PROP-AUTO:START -->\n"
                        "# HLAVNÁ KARTA NADVÄZNEJ REKVIZITY\n\n"
                        f"**STABILNÁ IDENTITA:** {POLICE_BOAT_NAME}\n\n"
                        "**ALIASY:** policajny čln, policajný čln\n\n"
                        "**FIXNÉ VLASTNOSTI:** Policajný čln používaný pátracím tímom "
                        "pri hľadaní Jakubovho tela.\n\n"
                        "## ČASOVÁ OS A ODKAZY\n"
                        f"- [01/08LP]({scene_cards['01/08LP'].get('shortUrl')}) — "
                        "policajt z člna koordinuje potápačov.\n"
                        f"- [01/09]({scene_cards['01/09'].get('shortUrl')}) — "
                        "ten istý policajný čln stále pláva na hladine.\n"
                        "<!-- CIERNY-KAMEN-NATURAL-PROP-AUTO:END -->\n\n"
                        "## RUČNÉ POZNÁMKY\n"
                    )
                    actual = police_master.get("desc") or ""
                    auto_start = "<!-- CIERNY-KAMEN-NATURAL-PROP-AUTO:START -->"
                    auto_end = "<!-- CIERNY-KAMEN-NATURAL-PROP-AUTO:END -->"
                    if auto_start in actual and auto_end in actual:
                        old = actual[actual.index(auto_start):actual.index(auto_end) + len(auto_end)]
                        new = desired_master[desired_master.index(auto_start):desired_master.index(auto_end) + len(auto_end)]
                        desired_master = actual.replace(old, new, 1)
                    if mode == "props-apply" and (
                        police_master.get("name") != POLICE_BOAT_NAME
                        or actual != desired_master
                    ):
                        api["trello_put_body"](
                            f"/cards/{police_master['id']}",
                            {"name": POLICE_BOAT_NAME, "desc": desired_master},
                        )
                        writes += 1

            for candidate in selected:
                action = CURATED_PROP_ACTIONS[candidate["item_id"]]
                card = scene_cards[candidate["scene_id"]]
                lists_for_card = checklists_by_card[card["id"]]
                prop_checklist = next(
                    item for item in lists_for_card
                    if folded(item.get("name")) == folded("REKVIZITY")
                )
                question_checklist = next(
                    item for item in lists_for_card
                    if folded(item.get("name")) == folded("OTÁZKY NA PORADU")
                )
                companion = action.get("companion")
                if action.get("continuity") == "police_boat":
                    if not police_url:
                        companion = "<n> " + POLICE_BOAT_NAME + " — pending registry URL"
                    else:
                        companion = (
                            f"<n> {POLICE_BOAT_NAME} — policajt z člna koordinuje "
                            "potápačov pri hľadaní Jakubovho tela | ← prvý výskyt | "
                            "TU: čln je na hladine a koordinuje pátranie | → 01/09: "
                            f"stále pláva na hladine | KARTA: {police_url}"
                        )
                operations.append({
                    "scene_id": candidate["scene_id"],
                    "original": candidate["name"], "companion": companion,
                    "question": action.get("question"),
                    "continuity": action.get("continuity"),
                })
                if mode != "props-apply":
                    continue
                existing_prop_names = {
                    item.get("name") for item in prop_checklist.get("checkItems", [])
                }
                if companion and companion not in existing_prop_names:
                    api["trello_post_body"](
                        f"/checklists/{prop_checklist['id']}/checkItems",
                        {"name": companion, "pos": "bottom"},
                    )
                    writes += 1
                question = action.get("question")
                existing_questions = {
                    item.get("name") for item in question_checklist.get("checkItems", [])
                }
                if question and question not in existing_questions:
                    api["trello_post_body"](
                        f"/checklists/{question_checklist['id']}/checkItems",
                        {"name": question, "pos": "bottom"},
                    )
                    writes += 1
                if action.get("continuity") == "police_boat" and police_master:
                    for scene_id in POLICE_BOAT_SCENES:
                        target_card = scene_cards[scene_id]
                        target_checklists = checklists_by_card[target_card["id"]]
                        target_props = next(
                            item for item in target_checklists
                            if folded(item.get("name")) == folded("REKVIZITY")
                        )
                        if scene_id == "01/08LP":
                            text = companion
                        else:
                            text = (
                                f"<n> {POLICE_BOAT_NAME} — policajný čln stále "
                                "pláva na hladine počas pátrania | ← 01/08LP: policajt "
                                "z člna koordinuje potápačov | TU: čln pokračuje v "
                                "pátraní na hladine | → ďalší potvrdený obraz neurčený | "
                                f"KARTA: {police_url}"
                            )
                        if text not in {
                            item.get("name") for item in target_props.get("checkItems", [])
                        }:
                            api["trello_post_body"](
                                f"/checklists/{target_props['id']}/checkItems",
                                {"name": text, "pos": "bottom"},
                            )
                            writes += 1
                        label_matches = api["cierny_kamen_exact_named"](
                            state["labels"], "Nadväzná rekvizita", True
                        )
                        if len(label_matches) == 1:
                            desired_labels = sorted(
                                set(target_card.get("idLabels", []))
                                | {label_matches[0]["id"]}
                            )
                            if desired_labels != sorted(target_card.get("idLabels", [])):
                                api["trello_put_body"](
                                    f"/cards/{target_card['id']}",
                                    {"idLabels": ",".join(desired_labels)},
                                )
                                writes += 1
                        if ensure_attachment(
                            api, target_card, police_master.get("shortUrl"),
                            POLICE_BOAT_NAME,
                        ):
                            writes += 1
                        if ensure_attachment(
                            api, police_master, target_card.get("shortUrl"), scene_id
                        ):
                            writes += 1

            if mode == "props-apply":
                refreshed = checklist_map(api, state["board"]["id"])
                for candidate in selected:
                    card = scene_cards[candidate["scene_id"]]
                    items = [
                        item
                        for checklist in refreshed.get(card["id"], [])
                        for item in checklist.get("checkItems", [])
                    ]
                    if not any(
                        item.get("id") == candidate["item_id"]
                        and item.get("name") == candidate["name"]
                        and item.get("state") == candidate["state"]
                        for item in items
                    ):
                        errors.append({
                            "scene_id": candidate["scene_id"],
                            "error": "original manual item changed",
                        })
                for card_id, before in protected_before.items():
                    after_card = api["trello_get"](
                        f"/cards/{card_id}",
                        {"fields": "id,desc,idLabels"},
                    )
                    after_attachments_list = api["trello_get"](
                        f"/cards/{card_id}/attachments",
                        {"fields": "id,name,url,bytes,date"},
                    )
                    after_attachments = {
                        item.get("id"): {
                            "id": item.get("id"), "name": item.get("name"),
                            "url": item.get("url"), "bytes": item.get("bytes"),
                            "date": item.get("date"),
                        }
                        for item in after_attachments_list
                    }
                    actions = api["trello_get"](
                        f"/cards/{card_id}/actions",
                        {"filter": "commentCard", "limit": 1000},
                    )
                    after_comments = sorted([{
                        "id": action.get("id"),
                        "text": (action.get("data") or {}).get("text"),
                        "date": action.get("date"),
                        "member": action.get("idMemberCreator"),
                    } for action in actions], key=lambda item: item.get("id", ""))
                    protected = (
                        (after_card.get("desc") or "") == before["desc"]
                        and before["labels"].issubset(
                            set(after_card.get("idLabels", []))
                        )
                        and projection_is_preserved(
                            before["checklists"], refreshed.get(card_id, [])
                        )
                        and all(
                            after_attachments.get(key) == value
                            for key, value in before["attachments"].items()
                        )
                        and before["comments"] == after_comments
                    )
                    if not protected:
                        errors.append({
                            "scene_id": before["scene_id"],
                            "error": "protected card data changed",
                        })
            return jsonify({
                "status": mode, "writes": writes, "start": start,
                "selected": len(selected), "operations": operations,
                "errors": errors,
                "remaining": max(0, len(eligible_props) - start - len(selected)),
            }), 200 if not errors else 409

        if mode == "final-audit":
            linked_scenes = 0
            ambiguous_untouched = 0
            ambiguity_questions = 0
            for scene in payload["scenes"]:
                card = scene_cards[scene["scene_id"]]
                names = catalog["scene_locations"].get(scene["scene_id"])
                if names:
                    expected = all(
                        f"[{name}]({all_space_urls[name]})" in (card.get("desc") or "")
                        for name in names
                    )
                    linked_scenes += bool(expected)
                elif scene["scene_id"] in {
                    item["scene_id"] for item in catalog["ambiguous"]
                }:
                    ambiguous_untouched += not bool(re.search(
                        r"LOKÁCI(?:A|E):\s*\[", card.get("desc") or ""
                    ))
                    ambiguous = next(
                        item for item in catalog["ambiguous"]
                        if item["scene_id"] == scene["scene_id"]
                    )
                    expected_question = (
                        f"{scene['scene_id']} — Nejednoznačná identita priestoru „"
                        f"{ambiguous['source']}“: {ambiguous['question']}"
                    )
                    ambiguity_questions += any(
                        item.get("name") == expected_question
                        for checklist in checklists_by_card.get(card["id"], [])
                        if folded(checklist.get("name"))
                        == folded("OTÁZKY NA PORADU")
                        for item in checklist.get("checkItems", [])
                    )
            refreshed_checklists = checklist_map(api, state["board"]["id"])
            original_items_preserved = 0
            curated_results = []
            for candidate in eligible_props:
                card = scene_cards[candidate["scene_id"]]
                all_items = [
                    item for checklist in refreshed_checklists.get(card["id"], [])
                    for item in checklist.get("checkItems", [])
                ]
                original_ok = any(
                    item.get("id") == candidate["item_id"]
                    and item.get("name") == candidate["name"]
                    and item.get("state") == candidate["state"]
                    for item in all_items
                )
                original_items_preserved += original_ok
                action = CURATED_PROP_ACTIONS[candidate["item_id"]]
                expected_texts = [
                    value for value in (action.get("companion"), action.get("question"))
                    if value
                ]
                if action.get("continuity") == "police_boat":
                    expected_texts = [POLICE_BOAT_NAME]
                curated_results.append({
                    "item_id": candidate["item_id"],
                    "original_preserved": original_ok,
                    "automatic_output_present": all(
                        any(text in (item.get("name") or "") for item in all_items)
                        for text in expected_texts
                    ),
                })
            valid = (
                len(all_space_cards) == len(ordered_entries)
                and linked_scenes == len(ordered_scenes)
                and ambiguous_untouched == len(catalog["ambiguous"])
                and ambiguity_questions == len(catalog["ambiguous"])
                and original_items_preserved == len(eligible_props)
                and all(item["automatic_output_present"] for item in curated_results)
            )
            return jsonify({
                "status": "final-audit", "writes": 0, "valid": valid,
                "scene_cards": len(scene_cards),
                "space_cards": len(all_space_cards),
                "linked_scenes": linked_scenes,
                "ambiguous_untouched": ambiguous_untouched,
                "ambiguity_questions": ambiguity_questions,
                "new_prop_items": len(eligible_props),
                "original_prop_items_preserved": original_items_preserved,
                "curated_results": curated_results,
                "legacy_conflicts_untouched": sum(
                    not item["eligible_new_since_last_sync"]
                    for item in manual_prop_candidates
                ),
            }), 200 if valid else 409

        sample_scene = scene_cards[SAMPLE_SCENE_ID]
        sample_entry_map = {
            name: catalog["entries"][name] for name in SAMPLE_SPACE_NAMES
        }
        sample_candidate = next(
            (
                item for item in manual_prop_candidates
                if item["scene_id"] == SAMPLE_SCENE_ID
                and item["name"] == SAMPLE_PROP_ORIGINAL
                and item["eligible_new_since_last_sync"]
            ),
            None,
        )
        sample_plan = {
            "scene_id": SAMPLE_SCENE_ID,
            "scene_url": sample_scene.get("shortUrl"),
            "space_list_create": not space_lists,
            "space_cards": list(SAMPLE_SPACE_NAMES),
            "location": SAMPLE_SPACE_NAMES[-1],
            "original_prop_item": SAMPLE_PROP_ORIGINAL,
            "companion_prop_item": SAMPLE_PROP_COMPANION,
            "continuity": False,
            "prop_registry_card": None,
            "scene_labels_change": False,
            "protected_before": {
                "description": stable_json_hash(
                    description_without_location(sample_scene.get("desc") or "")
                ),
                "labels": stable_json_hash(sorted(sample_scene.get("idLabels", []))),
                "checklists": stable_json_hash(original_checklist_projection(
                    checklists_by_card.get(sample_scene["id"], [])
                )),
                "attachments": stable_json_hash(
                    attachments_by_card.get(sample_scene["id"], [])
                ),
                "comments": stable_json_hash(
                    comments_by_card.get(sample_scene["id"], [])
                ),
            },
        }
        sample_errors = []
        if sample_candidate is None:
            sample_errors.append("sample natural prop item is missing or not new")
        for name, entry in sample_entry_map.items():
            matches = marker_cards.get(entry["key"], [])
            if len(matches) > 1:
                sample_errors.append(f"duplicate sample space marker: {name}")
        if sample_errors:
            return jsonify({
                "status": "blocked", "writes": 0,
                "sample": sample_plan, "errors": sample_errors,
            }), 409
        if mode == "sample-dry-run":
            return jsonify({
                "status": "sample-dry-run", "writes": 0,
                "sample": sample_plan, "errors": [], "safe": True,
            }), 200

        writes = []
        sample_cards = {}
        if mode == "sample-apply":
            if space_lists:
                target_list = space_lists[0]
            else:
                target_list = api["trello_post_body"]("/lists", {
                    "name": SPACE_LIST_NAME,
                    "idBoard": state["board"]["id"],
                    "pos": "bottom",
                })
                writes.append("created_space_list")
            for name in SAMPLE_SPACE_NAMES:
                entry = sample_entry_map[name]
                matches = marker_cards.get(entry["key"], [])
                if matches:
                    sample_cards[name] = matches[0]
                    continue
                exact_unmarked = [
                    card for card in space_cards
                    if folded(card.get("name")) == folded(name)
                    and SPACE_MARKER_PREFIX not in (card.get("desc") or "")
                ]
                if exact_unmarked:
                    return jsonify({
                        "status": "blocked", "writes": len(writes),
                        "errors": [f"unmarked exact-name space card exists: {name}"],
                    }), 409
                card = api["trello_post_body"]("/cards", {
                    "idList": target_list["id"], "name": name,
                    "desc": space_marker(entry["key"]), "pos": "bottom",
                })
                sample_cards[name] = card
                writes.append(f"created_space:{name}")
            space_urls = {
                name: card.get("shortUrl") for name, card in sample_cards.items()
            }
            for name in SAMPLE_SPACE_NAMES:
                card = sample_cards[name]
                desired = space_description(
                    sample_entry_map[name], scene_cards, space_urls,
                    catalog, payload,
                )
                desired = replace_space_auto_block(card.get("desc") or "", desired)
                if card.get("desc") != desired or card.get("name") != name:
                    api["trello_put_body"](
                        f"/cards/{card['id']}", {"name": name, "desc": desired}
                    )
                    card["desc"] = desired
                    writes.append(f"updated_space:{name}")

            leaf = sample_cards[SAMPLE_SPACE_NAMES[-1]]
            desired_location = (
                f"[{SAMPLE_SPACE_NAMES[-1]}]({leaf.get('shortUrl')})"
            )
            desired_scene_desc = replace_location_value(
                sample_scene.get("desc") or "", desired_location
            )
            if sample_scene.get("desc") != desired_scene_desc:
                api["trello_put_body"](
                    f"/cards/{sample_scene['id']}", {"desc": desired_scene_desc}
                )
                writes.append("updated_sample_location")

            prop_checklist = next(
                item for item in checklists_by_card[sample_scene["id"]]
                if folded(item.get("name")) == folded("REKVIZITY")
            )
            existing_companions = [
                item for item in prop_checklist.get("checkItems", [])
                if item.get("name") == SAMPLE_PROP_COMPANION
            ]
            if not existing_companions:
                api["trello_post_body"](
                    f"/checklists/{prop_checklist['id']}/checkItems",
                    {"name": SAMPLE_PROP_COMPANION, "pos": "bottom"},
                )
                writes.append("added_sample_prop_companion")

            parent = sample_cards[SAMPLE_SPACE_NAMES[0]]
            attachment_pairs = (
                (sample_scene, leaf.get("shortUrl"), SAMPLE_SPACE_NAMES[-1]),
                (leaf, sample_scene.get("shortUrl"), SAMPLE_SCENE_ID),
                (parent, leaf.get("shortUrl"), SAMPLE_SPACE_NAMES[-1]),
                (leaf, parent.get("shortUrl"), SAMPLE_SPACE_NAMES[0]),
            )
            for card, url, name in attachment_pairs:
                if ensure_attachment(api, card, url, name):
                    writes.append(f"attachment:{card['id']}:{name}")

        # Read-back is used both after apply and by the standalone sample audit.
        refreshed_state = api["cierny_kamen_import_state"](payload)
        refreshed_scene_cards = api["cierny_kamen_scene_cards_by_id"](
            refreshed_state
        )
        refreshed_scene = refreshed_scene_cards[SAMPLE_SCENE_ID][0]
        refreshed_checklists = api["trello_get"](
            f"/cards/{refreshed_scene['id']}/checklists",
            {"checkItems": "all", "fields": "id,name,pos"},
        )
        refreshed_attachments = api["trello_get"](
            f"/cards/{refreshed_scene['id']}/attachments",
            {"fields": "id,name,url,bytes,date"},
        )
        refreshed_comments = api["trello_get"](
            f"/cards/{refreshed_scene['id']}/actions",
            {"filter": "commentCard", "limit": 1000},
        )
        refreshed_space_lists = api["cierny_kamen_exact_named"](
            refreshed_state["lists"], SPACE_LIST_NAME
        )
        refreshed_space_cards = [
            card for card in refreshed_state["cards"]
            if refreshed_space_lists
            and card.get("idList") == refreshed_space_lists[0]["id"]
            and not card.get("closed")
        ]
        refreshed_by_key = defaultdict(list)
        for card in refreshed_space_cards:
            match = re.search(
                r"<!-- CIERNY-KAMEN-SPACE:([^>]+) -->",
                card.get("desc") or "",
            )
            if match:
                refreshed_by_key[match.group(1)].append(card)
        sample_space_readback = {
            name: refreshed_by_key.get(sample_entry_map[name]["key"], [])
            for name in SAMPLE_SPACE_NAMES
        }
        prop_checklist_after = next(
            item for item in refreshed_checklists
            if folded(item.get("name")) == folded("REKVIZITY")
        )
        before_projection = original_checklist_projection(
            checklists_by_card.get(sample_scene["id"], [])
        )
        original_attachments = {
            item.get("id"): item
            for item in attachments_by_card.get(sample_scene["id"], [])
        }
        after_attachments = {
            item.get("id"): {
                "id": item.get("id"), "name": item.get("name"),
                "url": item.get("url"), "bytes": item.get("bytes"),
                "date": item.get("date"),
            }
            for item in refreshed_attachments
        }
        comments_after = [
            {
                "id": action.get("id"),
                "text": (action.get("data") or {}).get("text"),
                "date": action.get("date"),
                "member": action.get("idMemberCreator"),
            }
            for action in refreshed_comments
        ]
        protected_checks = {
            "description_outside_location": (
                description_without_location(sample_scene.get("desc") or "")
                == description_without_location(refreshed_scene.get("desc") or "")
            ),
            "labels": sorted(sample_scene.get("idLabels", []))
            == sorted(refreshed_scene.get("idLabels", [])),
            "original_checklists_and_items": projection_is_preserved(
                before_projection, refreshed_checklists
            ),
            "original_attachments": all(
                after_attachments.get(item_id) == item
                for item_id, item in original_attachments.items()
            ),
            "comments": sorted(
                comments_by_card.get(sample_scene["id"], []),
                key=lambda item: item.get("id", ""),
            ) == sorted(comments_after, key=lambda item: item.get("id", "")),
            "original_prop_item_literal": any(
                item.get("id") == sample_candidate["item_id"]
                and item.get("name") == SAMPLE_PROP_ORIGINAL
                and item.get("state") == sample_candidate["state"]
                for item in prop_checklist_after.get("checkItems", [])
            ),
        }
        functional_checks = {
            "space_list_exactly_one": len(refreshed_space_lists) == 1,
            "space_cards_exactly_one_each": all(
                len(cards) == 1 for cards in sample_space_readback.values()
            ),
            "location_named_link": bool(re.search(
                r"LOKÁCIA:\s*\[DOM BETY – IZBA BETY\]\(https://trello.com/c/[^)]+\)",
                refreshed_scene.get("desc") or "",
            )),
            "companion_exactly_once": sum(
                item.get("name") == SAMPLE_PROP_COMPANION
                for item in prop_checklist_after.get("checkItems", [])
            ) == 1,
            "no_continuity_marker_added": not any(
                item.get("name") == SAMPLE_PROP_COMPANION
                and item.get("name", "").lstrip().startswith("<n>")
                for item in prop_checklist_after.get("checkItems", [])
            ),
        }
        valid = all(protected_checks.values()) and all(functional_checks.values())
        return jsonify({
            "status": "sample-applied" if mode == "sample-apply" else "sample-audit",
            "writes": len(writes), "write_actions": writes,
            "scene": {"id": SAMPLE_SCENE_ID, "url": refreshed_scene.get("shortUrl")},
            "spaces": {
                name: [
                    {"name": card.get("name"), "url": card.get("shortUrl")}
                    for card in cards
                ] for name, cards in sample_space_readback.items()
            },
            "protected_checks": protected_checks,
            "functional_checks": functional_checks,
            "valid": valid,
        }), 200 if valid else 409


def read_catalog_for_tests():
    path = Path(__file__).with_name("cierny_kamen_pdf_payload.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return build_space_catalog(payload)
