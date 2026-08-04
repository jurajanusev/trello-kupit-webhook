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
            "sample-audit",
        }:
            return jsonify({
                "error": "unsupported mode"
            }), 400

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

            def ensure_attachment(card, url, name):
                attachments = api["trello_get"](
                    f"/cards/{card['id']}/attachments",
                    {"fields": "id,name,url"},
                )
                if any(item.get("url") == url for item in attachments):
                    return False
                api["trello_post_body"](
                    f"/cards/{card['id']}/attachments",
                    {"url": url, "name": name},
                )
                return True

            parent = sample_cards[SAMPLE_SPACE_NAMES[0]]
            attachment_pairs = (
                (sample_scene, leaf.get("shortUrl"), SAMPLE_SPACE_NAMES[-1]),
                (leaf, sample_scene.get("shortUrl"), SAMPLE_SCENE_ID),
                (parent, leaf.get("shortUrl"), SAMPLE_SPACE_NAMES[-1]),
                (leaf, parent.get("shortUrl"), SAMPLE_SPACE_NAMES[0]),
            )
            for card, url, name in attachment_pairs:
                if ensure_attachment(card, url, name):
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
