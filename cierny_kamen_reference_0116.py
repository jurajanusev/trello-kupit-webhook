from __future__ import annotations

import copy
import hashlib
import json
import re

from flask import jsonify, request


KEY = "cierny-kamen-reference-0116-4aug-a91e64c3"
BOARD_REF = "CzuD55PR"
SCENE_ID = "01/16"
CARD_SHORT_URL = "https://trello.com/c/ggTQvhD2"
METADATA_START = "<!-- CIERNY-KAMEN-SCHEDULE-METADATA:START -->"
METADATA_END = "<!-- CIERNY-KAMEN-SCHEDULE-METADATA:END -->"
SECTIONS = (
    "### REKVIZITY V KONTEXTE",
    "### KONTINUITA",
    "### ODKAZY",
    "### RUČNÉ DOPLNENIA",
    "### AKCIA A DIALÓGY",
)
RELATED_HEADING = "### NADVÄZNÉ OBRAZY"
CARD_URL = re.compile(r"https://trello\.com/c/[A-Za-z0-9]+")


def stable_hash(value):
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def exact_heading_positions(text, headings):
    result = {}
    for heading in headings:
        matches = list(re.finditer(
            rf"(?m)^{re.escape(heading)}\s*$", text
        ))
        if len(matches) != 1:
            raise ValueError(f"expected one heading {heading}; found {len(matches)}")
        result[heading] = matches[0].start()
    return result


def parse_description(desc):
    if desc.count(METADATA_START) != 1 or desc.count(METADATA_END) != 1:
        raise ValueError("metadata markers are not unique")
    meta_start = desc.index(METADATA_START)
    meta_end = desc.index(METADATA_END) + len(METADATA_END)
    if meta_end <= meta_start:
        raise ValueError("metadata marker order invalid")
    metadata = desc[meta_start:meta_end]
    without = (desc[:meta_start] + desc[meta_end:]).strip("\r\n")
    headings = list(SECTIONS)
    related_count = len(list(re.finditer(
        rf"(?m)^{re.escape(RELATED_HEADING)}\s*$", without
    )))
    if related_count > 1:
        raise ValueError("multiple NADVÄZNÉ OBRAZY sections")
    if related_count == 1:
        headings.append(RELATED_HEADING)
    positions = exact_heading_positions(without, headings)
    ordered_required = [positions[item] for item in SECTIONS]
    if ordered_required != sorted(ordered_required):
        raise ValueError("required section order is ambiguous")
    if not (
        positions["### ODKAZY"]
        < positions.get(RELATED_HEADING, positions["### RUČNÉ DOPLNENIA"])
        < positions["### RUČNÉ DOPLNENIA"]
    ) and related_count:
        raise ValueError("NADVÄZNÉ OBRAZY is in an unexpected position")

    ordered = sorted(positions.items(), key=lambda item: item[1])
    chunks = {}
    title = without[:ordered[0][1]].rstrip("\r\n")
    if not title.strip():
        raise ValueError("scene title before first section is missing")
    for index, (heading, start) in enumerate(ordered):
        end = ordered[index + 1][1] if index + 1 < len(ordered) else len(without)
        chunks[heading] = without[start:end].rstrip("\r\n")
    return {"metadata": metadata, "title": title, "chunks": chunks}


def metadata_fields(metadata):
    fields = {}
    for line in metadata.splitlines():
        if ":" not in line or line.startswith("<!--"):
            continue
        key, value = line.split(":", 1)
        fields[key.strip().casefold()] = value.strip()
    return fields


def metadata_characters(metadata):
    value = metadata_fields(metadata).get("postavy")
    if not value:
        raise ValueError("POSTAVY metadata missing")
    result = [item.strip() for item in value.split(",") if item.strip()]
    if not result:
        raise ValueError("POSTAVY metadata empty")
    return result


def metadata_location_urls(metadata):
    fields = metadata_fields(metadata)
    values = [
        value for key, value in fields.items()
        if key in {"lokácia", "lokácie", "lokacia", "lokacie"}
    ]
    if len(values) != 1:
        raise ValueError("location metadata field is not unique")
    urls = CARD_URL.findall(values[0])
    if not urls:
        raise ValueError("location metadata has no registry URL")
    return urls


def normalize_name(value):
    return re.sub(r"\s+", " ", (value or "").strip()).casefold()


def display_link(scene, card):
    title = scene.get("prepis")
    if not title:
        raise ValueError(f"{scene['scene_id']} has no PREPIS title")
    return f"[{scene['scene_id']} – {title}]({card['shortUrl']})"


def find_neighbors(payload, scene_cards, target_desc):
    scenes = payload["scenes"]
    indexes = [index for index, item in enumerate(scenes)
               if item["scene_id"] == SCENE_ID]
    if len(indexes) != 1:
        raise ValueError("01/16 is not unique in authoritative order")
    index = indexes[0]
    target_scene = scenes[index]
    parsed_target = parse_description(target_desc)
    characters = metadata_characters(parsed_target["metadata"])
    target_space_urls = set(metadata_location_urls(parsed_target["metadata"]))

    if len(scene_cards) != len(scenes):
        raise ValueError(
            f"expected {len(scenes)} verified scene cards; found {len(scene_cards)}"
        )

    parsed_by_id = {}
    for scene in scenes:
        card = scene_cards.get(scene["scene_id"])
        if not card:
            raise ValueError(f"missing scene card {scene['scene_id']}")
        parsed_by_id[scene["scene_id"]] = parse_description(card.get("desc") or "")

    def nearest(predicate):
        previous = next(
            (item for item in reversed(scenes[:index]) if predicate(item)), None
        )
        following = next(
            (item for item in scenes[index + 1:] if predicate(item)), None
        )
        return previous, following

    def verified_characters(scene):
        return metadata_characters(parsed_by_id[scene["scene_id"]]["metadata"])

    def same_space(scene):
        urls = set(metadata_location_urls(
            parsed_by_id[scene["scene_id"]]["metadata"]
        ))
        return bool(target_space_urls & urls)

    space_previous, space_next = nearest(same_space)
    character_neighbors = []
    for character in characters:
        expected = normalize_name(character)
        previous, following = nearest(
            lambda scene, expected=expected: expected in {
                normalize_name(item) for item in verified_characters(scene)
            }
        )
        character_neighbors.append({
            "character": character, "previous": previous, "next": following,
        })

    target_set = {normalize_name(item) for item in characters}
    same_cast_previous, same_cast_next = nearest(
        lambda scene: (
            {normalize_name(item) for item in verified_characters(scene)}
            == target_set
        )
    )
    return {
        "target_scene": target_scene,
        "characters": characters,
        "space_previous": space_previous, "space_next": space_next,
        "character_neighbors": character_neighbors,
        "same_cast_previous": same_cast_previous,
        "same_cast_next": same_cast_next,
    }


def link_or_dash(scene, scene_cards):
    return display_link(scene, scene_cards[scene["scene_id"]]) if scene else "—"


def related_section(neighbors, scene_cards):
    lines = [
        RELATED_HEADING,
        "",
        "### Rovnaký priestor",
        f"- Predchádzajúci: {link_or_dash(neighbors['space_previous'], scene_cards)}",
        f"- Nasledujúci: {link_or_dash(neighbors['space_next'], scene_cards)}",
        "",
        "### Rovnaké postavy",
    ]
    for item in neighbors["character_neighbors"]:
        lines.append(
            f"- {item['character']}: ← {link_or_dash(item['previous'], scene_cards)}"
            f" | → {link_or_dash(item['next'], scene_cards)}"
        )
    if neighbors["same_cast_previous"] or neighbors["same_cast_next"]:
        lines.append(
            "- Rovnaká zostava postáv: ← "
            f"{link_or_dash(neighbors['same_cast_previous'], scene_cards)} | → "
            f"{link_or_dash(neighbors['same_cast_next'], scene_cards)}"
        )
    return "\n".join(lines)


def desired_description(desc, related):
    parsed = parse_description(desc)
    chunks = parsed["chunks"]
    ordered = [
        parsed["title"],
        chunks["### REKVIZITY V KONTEXTE"],
        chunks["### KONTINUITA"],
        chunks["### ODKAZY"],
        related,
        chunks["### RUČNÉ DOPLNENIA"],
        chunks["### AKCIA A DIALÓGY"],
        parsed["metadata"],
    ]
    return "\n\n".join(item.strip("\r\n") for item in ordered)


def normalized_snapshot(api, card_id):
    card = api["trello_get"](f"/cards/{card_id}", {
        "fields": "id,name,desc,idList,shortUrl,closed,idLabels,due,dueComplete,pos",
    })
    checklists = api["trello_get"](f"/cards/{card_id}/checklists", {
        "checkItems": "all", "fields": "id,name,pos",
    })
    attachments = api["trello_get"](f"/cards/{card_id}/attachments", {
        "fields": "id,name,url,bytes,date",
    })
    actions = api["trello_get"](f"/cards/{card_id}/actions", {
        "filter": "commentCard", "limit": 1000,
    })
    value = {
        "card": {
            **card, "idLabels": sorted(card.get("idLabels", [])),
        },
        "checklists": sorted(checklists, key=lambda item: item.get("id", "")),
        "attachments": sorted(attachments, key=lambda item: item.get("id", "")),
        "comments": sorted([{
            "id": item.get("id"), "date": item.get("date"),
            "member": item.get("idMemberCreator"),
            "text": (item.get("data") or {}).get("text"),
        } for item in actions], key=lambda item: item.get("id", "")),
    }
    return value, stable_hash(value)


def find_target_set_item(checklists):
    set_lists = [item for item in checklists
                 if normalize_name(item.get("name")) == "set"]
    if len(set_lists) != 1:
        raise ValueError(f"expected one SET checklist; found {len(set_lists)}")
    candidates = []
    for item in set_lists[0].get("checkItems", []):
        folded = normalize_name(item.get("name")).replace("–", "-").replace("—", "-")
        if "prostredie obrazu 01/16" in folded:
            candidates.append(item)
    if len(candidates) != 1:
        raise ValueError(
            "expected one 'Set — prostredie obrazu 01/16' item; "
            f"found {len(candidates)}; actual SET items: "
            f"{[item.get('name') for item in set_lists[0].get('checkItems', [])]}"
        )
    return set_lists[0], candidates[0]


def desired_set_item(original, location_urls):
    result = original
    for url in location_urls:
        if url not in result:
            result += f" | KARTA: {url}"
    return result


def register_routes(flask_app, api):
    @flask_app.route("/api/reference-cierny-kamen-0116", methods=["POST"])
    def reference_cierny_kamen_0116():
        if request.headers.get("X-Reference-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "audit").strip().casefold()
        if mode not in {"audit", "dry-run", "apply", "read-back"}:
            return jsonify({"error": "unsupported mode"}), 400

        payload = api["cierny_kamen_import_payload"]()
        state = api["cierny_kamen_import_state"](payload)
        groups = api["cierny_kamen_scene_cards_by_id"](state)
        collisions = {
            scene_id: len(cards) for scene_id, cards in groups.items()
            if len(cards) != 1
        }
        scene_cards = {
            scene_id: cards[0] for scene_id, cards in groups.items()
            if len(cards) == 1
        }
        blockers = []
        if collisions:
            blockers.append({"scene_card_collisions": collisions})
        if SCENE_ID not in scene_cards:
            blockers.append("01/16 card missing")
        elif scene_cards[SCENE_ID].get("shortUrl") != CARD_SHORT_URL:
            blockers.append("01/16 resolved to unexpected URL")
        if blockers:
            return jsonify({"status": "blocked", "writes": 0,
                            "blockers": blockers}), 409

        target = scene_cards[SCENE_ID]
        try:
            before, before_hash = normalized_snapshot(api, target["id"])
            parsed = parse_description(before["card"].get("desc") or "")
            neighbors = find_neighbors(
                payload, scene_cards, before["card"].get("desc") or ""
            )
            related = related_section(neighbors, scene_cards)
            new_desc = desired_description(before["card"].get("desc") or "", related)
            try:
                parsed_new = parse_description(new_desc)
            except ValueError as exc:
                raise ValueError(
                    f"{exc}; proposed marker counts: "
                    f"START={new_desc.count(METADATA_START)}, "
                    f"END={new_desc.count(METADATA_END)}"
                ) from exc
            set_checklist, set_item = find_target_set_item(before["checklists"])
            location_urls = metadata_location_urls(parsed["metadata"])
            new_set_item = desired_set_item(set_item.get("name") or "", location_urls)
        except Exception as exc:
            return jsonify({"status": "blocked", "writes": 0,
                            "blockers": [f"{type(exc).__name__}: {exc}"]}), 409

        neighbor_result = {
            "same_space": {
                "previous": (
                    {"scene_id": neighbors["space_previous"]["scene_id"],
                     "title": neighbors["space_previous"].get("prepis"),
                     "url": scene_cards[neighbors["space_previous"]["scene_id"]]["shortUrl"]}
                    if neighbors["space_previous"] else None
                ),
                "next": (
                    {"scene_id": neighbors["space_next"]["scene_id"],
                     "title": neighbors["space_next"].get("prepis"),
                     "url": scene_cards[neighbors["space_next"]["scene_id"]]["shortUrl"]}
                    if neighbors["space_next"] else None
                ),
            },
            "characters": [{
                "character": item["character"],
                "previous": ({
                    "scene_id": item["previous"]["scene_id"],
                    "title": item["previous"].get("prepis"),
                    "url": scene_cards[item["previous"]["scene_id"]]["shortUrl"],
                } if item["previous"] else None),
                "next": ({
                    "scene_id": item["next"]["scene_id"],
                    "title": item["next"].get("prepis"),
                    "url": scene_cards[item["next"]["scene_id"]]["shortUrl"],
                } if item["next"] else None),
            } for item in neighbors["character_neighbors"]],
            "same_cast": {
                "previous": neighbors["same_cast_previous"]["scene_id"]
                if neighbors["same_cast_previous"] else None,
                "next": neighbors["same_cast_next"]["scene_id"]
                if neighbors["same_cast_next"] else None,
            },
        }
        result = {
            "status": mode, "writes": 0,
            "board": {"id": state["board"]["id"],
                      "name": state["board"].get("name"),
                      "url": state["board"].get("url"), "ref": BOARD_REF},
            "card": {"id": target["id"], "name": target.get("name"),
                     "url": target.get("shortUrl")},
            "source_scenes": len(payload["scenes"]),
            "verified_scene_cards": len(scene_cards),
            "snapshot": {
                "sha256": before_hash,
                "checklists": len(before["checklists"]),
                "check_items": sum(len(item.get("checkItems", []))
                                   for item in before["checklists"]),
                "labels": len(before["card"].get("idLabels", [])),
                "attachments": len(before["attachments"]),
                "comments": len(before["comments"]),
            },
            "neighbors": neighbor_result,
            "related_section": related,
            "description_before": before["card"].get("desc"),
            "description_after": new_desc,
            "set_item": {
                "checklist_id": set_checklist["id"], "item_id": set_item["id"],
                "before": set_item.get("name"), "after": new_set_item,
            },
            "diff": {
                "metadata_content_unchanged": (
                    parsed_new["metadata"] == parsed["metadata"]
                ),
                "metadata_moved_to_end": new_desc.endswith(parsed["metadata"]),
                "related_section_inserted": related in new_desc,
                "set_item_suffix_only": new_set_item.startswith(
                    set_item.get("name") or ""
                ),
                "other_cards_planned": 0,
            },
            "pending": int(new_desc != before["card"].get("desc"))
            + int(new_set_item != set_item.get("name")),
        }
        if mode in {"audit", "dry-run", "read-back"}:
            return jsonify(result), 200

        if new_desc != before["card"].get("desc"):
            api["trello_put_body"](
                f"/cards/{target['id']}", {"desc": new_desc}
            )
            result["writes"] += 1
        if new_set_item != set_item.get("name"):
            api["trello_put_body"](
                f"/cards/{target['id']}/checkItem/{set_item['id']}",
                {"name": new_set_item},
            )
            result["writes"] += 1

        after, after_hash = normalized_snapshot(api, target["id"])
        expected = copy.deepcopy(before)
        expected["card"]["desc"] = new_desc
        for checklist in expected["checklists"]:
            for item in checklist.get("checkItems", []):
                if item.get("id") == set_item["id"]:
                    item["name"] = new_set_item
        protected_equal = after == expected
        result.update({
            "status": "applied" if protected_equal else "verification-failed",
            "after_sha256": after_hash,
            "protected_equal_to_exact_expected": protected_equal,
            "read_back_description_exact": after["card"].get("desc") == new_desc,
            "read_back_set_item_exact": any(
                item.get("id") == set_item["id"] and item.get("name") == new_set_item
                for checklist in after["checklists"]
                for item in checklist.get("checkItems", [])
            ),
        })
        return jsonify(result), 200 if protected_equal else 409
