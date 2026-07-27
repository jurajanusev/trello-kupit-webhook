from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path


EPISODE_FILES = [
    "cierny_kamen_ep01_cards.json",
    "cierny_kamen_ep02_cards.json",
    "cierny_kamen_ep03_cards.json",
    "cierny_kamen_ep04_cards.json",
    "cierny_kamen_ep05_cards.json",
]

AMBIGUOUS_PROP_IDENTITIES = {
    "auto",
    "batoh",
    "flasa",
    "flasa s vodou",
    "jedlo",
    "kava",
    "laptop",
    "mobil",
    "notebook",
    "obalky",
    "pivo",
    "taska",
    "telefon",
    "uterak",
    "vino",
}

PROP_ALIASES = {
    "gitara": "Alexova gitara",
}


def folded(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    normalized = "".join(
        character for character in normalized
        if not unicodedata.combining(character)
    ).casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def split_description(description: str) -> tuple[str, str]:
    match = re.search(
        r"\*\*PREPIS:\s*(?P<title>.*?)\*\*\s*(?P<body>.*)\Z",
        description or "",
        flags=re.S | re.I,
    )
    if not match:
        raise ValueError("missing PREPIS block")
    return match.group("title").strip(), match.group("body").strip()


def action_to_markdown(body: str) -> str:
    blocks = [
        block.strip()
        for block in re.split(r"\n\s*\n", body.strip())
        if block.strip()
    ]
    formatted = []
    for block in blocks:
        dialogue = re.match(
            r"^\*\*(?P<speaker>.+?):\*\*\s*(?P<text>.*)\Z",
            block,
            flags=re.S,
        )
        if dialogue:
            lines = [f"> **{dialogue.group('speaker').strip()}:**"]
            text = dialogue.group("text").strip()
            if text:
                lines.extend(
                    f"> {line}" if line else ">"
                    for line in text.splitlines()
                )
            formatted.append("\n".join(lines))
        else:
            formatted.append(f"*{block}*")
    return "\n\n".join(formatted)


def prop_parts(item: str) -> tuple[str, str]:
    parts = re.split(r"\s+(?:-|–|—)\s+", item.strip(), maxsplit=1)
    identity = parts[0].strip()
    action = parts[1].strip() if len(parts) == 2 else item.strip()
    canonical = PROP_ALIASES.get(folded(identity), identity)
    return canonical, action


def is_fixed_set_item(identity: str) -> bool:
    key = folded(identity)
    return key.startswith("automat ") or key.startswith("automaty ")


def set_identity_from_name(name: str) -> str:
    heading = re.sub(r"^\s*\d+\s*/\s*\d+[A-Za-z]*\.\s*", "", name)
    heading = heading.split(" — ", 1)[0].strip()
    heading = re.sub(
        r"^(?:INT\.?\s*/\s*EXT\.?|EXT\.?\s*/\s*INT\.?|INT\.|EXT\.)\s*",
        "",
        heading,
        flags=re.I,
    )
    heading = re.sub(
        r",\s*(?:DEŇ|DEN|NOC|RÁNO|RANO|VEČER|VECER|DAY|NIGHT)"
        r"(?:\s*/\s*(?:DEŇ|DEN|NOC|DAY|NIGHT))?"
        r"(?:\s+[0-9X]+)?\s*$",
        "",
        heading,
        flags=re.I,
    )
    return re.sub(r"\s+", " ", heading).strip()


def scene_sort_key(scene_id: str) -> tuple[int, int, str]:
    match = re.fullmatch(r"(\d+)/(\d+)([A-Za-z]*)", scene_id)
    if not match:
        raise ValueError(f"invalid scene ID: {scene_id}")
    return int(match.group(1)), int(match.group(2)), match.group(3).upper()


def previous_and_next(
    occurrences: list[dict], current_index: int
) -> tuple[dict | None, dict | None]:
    ordered = sorted(occurrences, key=lambda item: item["order"])
    position = next(
        index
        for index, item in enumerate(ordered)
        if item["order"] == current_index
    )
    previous = ordered[position - 1] if position else None
    following = ordered[position + 1] if position + 1 < len(ordered) else None
    return previous, following


def continuity_item(
    stable_name: str,
    action: str,
    previous: dict | None,
    following: dict | None,
) -> dict:
    return {
        "stable_name": stable_name,
        "action": action,
        "previous": (
            {
                "scene_id": previous["scene_id"],
                "state": previous["action"],
            }
            if previous else None
        ),
        "current_state": action,
        "next": (
            {
                "scene_id": following["scene_id"],
                "state": following["action"],
            }
            if following else None
        ),
    }


def build_payload(source_root: Path) -> dict:
    raw_scenes = []
    seen_scene_ids = set()
    episode_counts = {}
    for episode, filename in enumerate(EPISODE_FILES, start=1):
        source = json.loads((source_root / filename).read_text(encoding="utf-8"))
        cards = source["cards"]
        episode_counts[f"{episode:02d}"] = len(cards)
        for card in cards:
            scene_id = card["number"].strip()
            if scene_id in seen_scene_ids:
                raise ValueError(f"duplicate scene ID: {scene_id}")
            seen_scene_ids.add(scene_id)
            prepis, action = split_description(card["description"])
            props = []
            set_extras = []
            for original_item in card.get("checklist", []):
                identity, context = prop_parts(original_item)
                entry = {
                    "stable_name": identity,
                    "action": context,
                    "source_text": original_item.strip(),
                }
                if is_fixed_set_item(identity):
                    set_extras.append(entry)
                else:
                    props.append(entry)
            if scene_id == "02/28":
                set_extras = [
                    {
                        "stable_name": "Automat na jedlo",
                        "action": (
                            "Bety si z neho vyberá jedlo; v 02/28 je "
                            "nepoškodený, pred rozbitím v 02/41"
                        ),
                        "source_text": (
                            "Automat na jedlo — Bety si z neho vyberá jedlo; "
                            "v 02/28 je nepoškodený, pred rozbitím v 02/41"
                        ),
                    },
                    {
                        "stable_name": "Gauč",
                        "action": (
                            "Alex na ňom sedí, hrá na gitare a spieva; "
                            "Bety, Kiko a Veronika si k nemu prisadnú"
                        ),
                        "source_text": (
                            "Gauč — Alex na ňom sedí, hrá na gitare a spieva; "
                            "Bety, Kiko a Veronika si k nemu prisadnú"
                        ),
                    },
                    {
                        "stable_name": "Komparzová akcia",
                        "action": (
                            "študenti sa trúsia von a zostávajú v klubovni; "
                            "ich odchod odkryje výhľad na Alexa"
                        ),
                        "source_text": (
                            "Komparzová akcia — študenti sa trúsia von a "
                            "zostávajú v klubovni; ich odchod odkryje výhľad "
                            "na Alexa"
                        ),
                    },
                ]
            raw_scenes.append({
                "scene_id": scene_id,
                "episode": episode,
                "order": len(raw_scenes),
                "name": card["name"].strip(),
                "prepis": prepis,
                "action_raw": action,
                "action_markdown": action_to_markdown(action),
                "action_sha256": hashlib.sha256(
                    action.encode("utf-8")
                ).hexdigest(),
                "location": set_identity_from_name(card["name"]),
                "characters": list(card.get("characters", [])),
                "props": props,
                "set_extras": set_extras,
            })

    if len(raw_scenes) != 261:
        raise ValueError(f"expected 261 scenes, found {len(raw_scenes)}")

    prop_occurrences = defaultdict(list)
    set_occurrences = defaultdict(list)
    for scene in raw_scenes:
        for prop in scene["props"]:
            prop_occurrences[folded(prop["stable_name"])].append({
                "scene_id": scene["scene_id"],
                "order": scene["order"],
                "action": prop["action"],
                "stable_name": prop["stable_name"],
            })
        set_occurrences[folded(scene["location"])].append({
            "scene_id": scene["scene_id"],
            "order": scene["order"],
            "action": f"prostredie obrazu {scene['scene_id']}",
            "stable_name": scene["location"],
        })

    prop_registry = {}
    for key, occurrences in prop_occurrences.items():
        if len(occurrences) < 2 or key in AMBIGUOUS_PROP_IDENTITIES:
            continue
        prop_registry[key] = {
            "identity": occurrences[0]["stable_name"],
            "aliases": sorted({
                occurrence["stable_name"] for occurrence in occurrences
            }),
            "occurrences": occurrences,
        }

    set_registry = {}
    for key, occurrences in set_occurrences.items():
        if len(occurrences) < 2:
            continue
        set_registry[key] = {
            "identity": occurrences[0]["stable_name"],
            "aliases": sorted({
                occurrence["stable_name"] for occurrence in occurrences
            }),
            "occurrences": occurrences,
        }

    scenes = []
    for scene in raw_scenes:
        prop_items = []
        for prop in scene["props"]:
            key = folded(prop["stable_name"])
            if key in prop_registry:
                previous, following = previous_and_next(
                    prop_registry[key]["occurrences"], scene["order"]
                )
                item = continuity_item(
                    prop_registry[key]["identity"],
                    prop["action"],
                    previous,
                    following,
                )
                item["registry_key"] = key
                item["continuity"] = True
                if (
                    scene["scene_id"] == "02/28"
                    and key == "alexova gitara"
                ):
                    item["action"] = (
                        "Alex na nej sedí na gauči, hrá a spieva pred Bety, "
                        "Kikom a Veronikou"
                    )
                    item["previous"]["state"] = "Alex na nej hrá na terase"
                    item["current_state"] = (
                        "gitara je funkčná a nepoškodená; overiť rovnaký "
                        "konkrétny kus, farbu a popruh"
                    )
            else:
                item = {
                    **prop,
                    "continuity": False,
                }
            prop_items.append(item)

        set_key = folded(scene["location"])
        set_continuity = set_key in set_registry
        if set_continuity:
            previous, following = previous_and_next(
                set_registry[set_key]["occurrences"], scene["order"]
            )
            primary_set_item = continuity_item(
                set_registry[set_key]["identity"],
                f"prostredie obrazu {scene['scene_id']}",
                previous,
                following,
            )
            primary_set_item.update({
                "registry_key": set_key,
                "continuity": True,
            })
        else:
            primary_set_item = {
                "stable_name": scene["location"],
                "action": f"prostredie obrazu {scene['scene_id']}",
                "source_text": (
                    f"{scene['location']} — prostredie obrazu "
                    f"{scene['scene_id']}"
                ),
                "continuity": False,
            }

        auto = any(
            re.search(
                r"\b(auto|vozidlo|limuz[ií]na|dod[aá]vka|tax[ií]k)\b",
                folded(prop["stable_name"]),
            )
            for prop in scene["props"]
        )
        scenes.append({
            **scene,
            "props": prop_items,
            "set_items": [primary_set_item, *scene["set_extras"]],
            "labels": [
                label
                for label, enabled in (
                    (
                        "Nadväzná rekvizita",
                        any(item["continuity"] for item in prop_items),
                    ),
                    ("Nadväzný set", set_continuity),
                    ("Auto", auto),
                )
                if enabled
            ],
        })

    max_action = max(len(scene["action_markdown"]) for scene in scenes)
    return {
        "project": "Čierny Kameň",
        "board_ref": "CzuD55PR",
        "scene_list_name": "SCENÁRE",
        "prop_registry_list_name": "REGISTER REKVIZÍT",
        "set_registry_list_name": "REGISTER SETOV",
        "episode_counts": episode_counts,
        "scenes": scenes,
        "prop_registry": prop_registry,
        "set_registry": set_registry,
        "stats": {
            "scenes": len(scenes),
            "unique_scene_ids": len(seen_scene_ids),
            "prop_registry_cards": len(prop_registry),
            "set_registry_cards": len(set_registry),
            "continuity_prop_scenes": sum(
                "Nadväzná rekvizita" in scene["labels"] for scene in scenes
            ),
            "continuity_set_scenes": sum(
                "Nadväzný set" in scene["labels"] for scene in scenes
            ),
            "auto_scenes": sum("Auto" in scene["labels"] for scene in scenes),
            "missing_prepis": 0,
            "missing_action": sum(
                not scene["action_raw"].strip() for scene in scenes
            ),
            "max_action_markdown_length": max_action,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = build_payload(args.source_root.resolve())
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(payload["stats"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
