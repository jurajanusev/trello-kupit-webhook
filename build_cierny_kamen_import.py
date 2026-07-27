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

STRICT_SET_CHAINS = [
    {
        "key": "imatrikulacna-party-telocvicna",
        "identity": (
            "Imatrikulačná párty – výzdoba a usporiadanie telocvične"
        ),
        "reason": (
            "Párty setup vzniká v 01/40 a pokračuje na tom istom podujatí "
            "cez pódium a parket do 01/43."
        ),
        "scenes": [
            ("01/40", "vzniká výzdoba, DJ, občerstvenie a parket"),
            ("01/41", "párty setup pokračuje počas rozhovoru pri akcii"),
            ("01/42", "setup pokračuje na pódiu počas vystúpenia"),
            ("01/43", "setup pokračuje na pódiu a parkete do konca akcie"),
        ],
    },
    {
        "key": "otvorenie-basketbalovej-sezony",
        "identity": (
            "Otvorenie basketbalovej sezóny – pódium, hľadisko a "
            "občerstvenie"
        ),
        "reason": (
            "Špecifický eventový setup je ustanovený v 02/43 a nesie sa "
            "cez bezprostredné obrazy otvorenia až po balenie v 02/53."
        ),
        "scenes": [
            ("02/43", "vzniká pódium, hľadisko a eventové usporiadanie"),
            ("02/44", "eventový setup pokračuje pri stole s občerstvením"),
            ("02/45", "eventový setup pokračuje pred začiatkom programu"),
            ("02/46", "setup pokračuje na pódiu pri hudobnom vystúpení"),
            ("02/47A", "setup pokračuje v hľadisku"),
            ("02/48", "setup pokračuje na pódiu pri otvorení sezóny"),
            ("02/47B", "setup pokračuje medzi pódiom a hľadiskom"),
            ("02/49", "setup pokračuje pri nástupe tímov na palubovku"),
            ("02/50", "setup pokračuje pri pódiu počas Sárinej reakcie"),
            ("02/51", "setup pokračuje na palubovke"),
            ("02/47C", "setup pokračuje v hľadisku po Sárinom úteku"),
            ("02/53", "event končí a tanečnice si pri pódiu balia tašky"),
        ],
    },
    {
        "key": "aktivovana-skolska-redakcia",
        "identity": (
            "Aktivovaná školská redakcia – uprataný a používaný priestor"
        ),
        "reason": (
            "V 03/11 sa roky nepoužívaná miestnosť uprace a zmení na "
            "aktívnu redakciu; tento stav nesú ďalšie konkrétne obrazy."
        ),
        "scenes": [
            ("03/11", "roky nepoužívaná miestnosť je uprataná a aktivovaná"),
            ("03/22", "uprataná redakcia sa používa na spoločné stretnutie"),
            ("03/27", "uprataná redakcia sa používa s pracovným stolom"),
            ("03/53", "aktívna redakcia pokračuje"),
            ("05/05", "v redakcii pribúda vyšetrovacia nástenka"),
            ("05/17", "redakcia s vyšetrovacím setupom pokračuje"),
            ("05/46", "redakcia s vyšetrovacím setupom pokračuje"),
            ("05/47LP", "postavy pracujú pred vyšetrovacou nástenkou"),
        ],
    },
    {
        "key": "kelerova-vysetrovacia-nastenka",
        "identity": "Kelerova vyšetrovacia nástenka a pracovňa",
        "reason": (
            "Rozsiahla nástenka a spisy sú ustanovené v 04/28; v 04/42 "
            "na ne priamo nadväzuje zničený a vykradnutý stav."
        ),
        "scenes": [
            (
                "04/28",
                "nástenka s mapou, fotkami, menami a červenými niťami "
                "je rozložená; stôl je plný spisov",
            ),
            (
                "04/42",
                "nástenka je dotrhaná, fotky a informácie chýbajú; "
                "stôl je rozhádzaný a spis prázdny",
            ),
        ],
    },
    {
        "key": "kar-revayovci-hala",
        "identity": "Kar u Révayovcov – výzdoba a eventové usporiadanie haly",
        "reason": (
            "Kvetinová výzdoba okolo Jakubovej fotografie vzniká v 05/13 "
            "pre kar a pokračuje v tej istej hale v 05/36–05/37."
        ),
        "scenes": [
            (
                "05/13",
                "vzniká kvetinová výzdoba okolo Jakubovej fotografie "
                "a setup pre kar",
            ),
            (
                "05/36",
                "setup karu pokračuje pri príchode hostí a šatni",
            ),
            (
                "05/37",
                "setup karu pokračuje pri stole s alkoholom a schodisku",
            ),
        ],
    },
]

SET_CONTINUITY_QUESTIONS = {
    "02/19LP": (
        "Má pietne miesto pri Jakubovej skrinke (kvety, fotografie a "
        "plyšové hračky) zostať aj v niektorom konkrétnom nasledujúcom "
        "obraze? Ak áno, určiť prvý a posledný obraz reťazca."
    ),
    "02/41": (
        "Má rozbité sklo automatu z 02/41 zostať viditeľne rozbité v "
        "03/10 alebo inom konkrétnom nasledujúcom obraze klubovne? "
        "Bez potvrdenia sa nenadväzuje."
    ),
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
    for scene in raw_scenes:
        for prop in scene["props"]:
            prop_occurrences[folded(prop["stable_name"])].append({
                "scene_id": scene["scene_id"],
                "order": scene["order"],
                "action": prop["action"],
                "stable_name": prop["stable_name"],
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

    scenes_by_id = {scene["scene_id"]: scene for scene in raw_scenes}
    set_registry = {}
    strict_set_by_scene = {}
    for chain in STRICT_SET_CHAINS:
        occurrences = []
        for scene_id, state in chain["scenes"]:
            if scene_id not in scenes_by_id:
                raise ValueError(
                    f"strict SET chain references missing scene {scene_id}"
                )
            occurrence = {
                "scene_id": scene_id,
                "order": scenes_by_id[scene_id]["order"],
                "action": state,
                "stable_name": chain["identity"],
            }
            occurrences.append(occurrence)
            if scene_id in strict_set_by_scene:
                raise ValueError(
                    f"scene belongs to multiple strict SET chains: {scene_id}"
                )
            strict_set_by_scene[scene_id] = chain["key"]
        set_registry[chain["key"]] = {
            "identity": chain["identity"],
            "aliases": [chain["identity"]],
            "reason": chain["reason"],
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

        set_key = strict_set_by_scene.get(scene["scene_id"])
        set_continuity = bool(set_key)
        if set_continuity:
            previous, following = previous_and_next(
                set_registry[set_key]["occurrences"], scene["order"]
            )
            primary_set_item = continuity_item(
                set_registry[set_key]["identity"],
                next(
                    occurrence["action"]
                    for occurrence in set_registry[set_key]["occurrences"]
                    if occurrence["scene_id"] == scene["scene_id"]
                ),
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
            "questions": (
                [SET_CONTINUITY_QUESTIONS[scene["scene_id"]]]
                if scene["scene_id"] in SET_CONTINUITY_QUESTIONS else []
            ),
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
            "set_items_total": sum(
                1 + len(scene["set_extras"]) for scene in raw_scenes
            ),
            "strict_set_chains": len(set_registry),
            "strict_set_chain_reasons": [
                {
                    "identity": entry["identity"],
                    "reason": entry["reason"],
                    "scenes": [
                        occurrence["scene_id"]
                        for occurrence in entry["occurrences"]
                    ],
                }
                for entry in set_registry.values()
            ],
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
