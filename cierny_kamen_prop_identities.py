from __future__ import annotations

import copy
import json
import re
import unicodedata
from pathlib import Path


MAP_PATH = Path(__file__).with_name("cierny_kamen_prop_identity_map.json")


SOURCE_CATEGORY_BY_TYPE = {
    "Auto / vozidlo": ("Auto",),
    "Sofiino auto": ("Auto", "Osobná rekvizita"),
    "Mobilný telefón": ("Osobná rekvizita",),
    "Notebook / laptop": ("Osobná rekvizita",),
    "Taška / batoh": ("Osobná rekvizita",),
    "Kľúče": ("Osobná rekvizita",),
    "Pištoľ / zbraň": ("Osobná rekvizita",),
    "Slúchadlá": ("Osobná rekvizita",),
    "Alexova gitara": ("Osobná rekvizita",),
    "Betin denník": ("Osobná rekvizita", "Dokument"),
    "Denník": ("Osobná rekvizita", "Dokument"),
    "Dokumenty / zmluva / spis": ("Dokument",),
    "Fotografie / fotoalbum": ("Dokument",),
}


SCREEN_IDENTITIES = {
    "Diktafón v Alicinom mobile",
    "Dogyho fotografie dôkazov zo Sofiinho auta",
    "Dogyho mobil s oznámením mesta",
    "Fotografia Jakubovej klubovej bundy s číslom 9",
    "Fotografia Olasovej na falošnom občianskom preukaze",
    "Fotografie z Alicinho internet bankingu",
    "Ivanov mobil s videom malej Sofie",
    "Rodinné fotografie Révayovcov na Sárinom tablete",
    "Slutshamingová fotografia Veroniky",
    "Slutshamingové fotografie obetí",
    "Sárina fotografia Laury a Andyho",
    "Tímová selfie tanečnej skupiny",
}


def registry_key(value):
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    if not value:
        raise ValueError("empty prop registry key")
    return value


def record_categories(record):
    result = set(SOURCE_CATEGORY_BY_TYPE.get(
        record["original_stable_name"], (),
    ))
    if record["stable_name"] in SCREEN_IDENTITIES:
        result.add("Screen")
    if record.get("continuity_group"):
        result.add("Nadväzná rekvizita")
    return sorted(result)


def load_identity_map():
    return json.loads(MAP_PATH.read_text(encoding="utf-8"))


def apply_identity_map(payload):
    result = copy.deepcopy(payload)
    identity_map = load_identity_map()
    records = {record["record_id"]: record for record in identity_map["records"]}
    consumed = set()
    registries = {}
    for scene in result["scenes"]:
        props = []
        questions = list(scene.get("questions", []))
        for index, original in enumerate(scene["props"]):
            record_id = f"{scene['scene_id']}#{index}"
            record = records[record_id]
            consumed.add(record_id)
            if record["ambiguity_question"] and record["ambiguity_question"] not in questions:
                questions.append(record["ambiguity_question"])
            if not record["include"]:
                continue
            group = record["continuity_group"]
            key = group or registry_key(record["stable_name"])
            prop = {
                "stable_name": record["stable_name"],
                "action": record["action"],
                "source_text": f"{record['stable_name']} — {record['action']}",
                "registry_key": key,
                "continuity": bool(group),
            }
            if group:
                prop.update({
                    "current_state": record["current_state"],
                    "previous": None,
                    "next": None,
                })
            entry = registries.setdefault(key, {
                "identity": record["stable_name"],
                "aliases": [record["stable_name"]],
                "categories": record_categories(record),
                "continuity": bool(group),
                "occurrences": [],
            })
            if entry["identity"] != record["stable_name"]:
                raise ValueError(
                    f"{key}: inconsistent stable names "
                    f"{entry['identity']!r} and {record['stable_name']!r}"
                )
            entry["categories"] = sorted(
                set(entry["categories"]) | set(record_categories(record))
            )
            entry["occurrences"].append({
                "scene_id": scene["scene_id"],
                "action": record["action"],
            })
            props.append(prop)
        scene["props"] = props
        scene["questions"] = questions
        labels = [
            label for label in scene.get("labels", [])
            if label not in {"Nadväzná rekvizita", "Auto"}
        ]
        scene_records = [
            r for r in records.values()
            if r["scene_id"] == scene["scene_id"] and r["include"]
        ]
        if any(r["continuity_group"] for r in scene_records):
            labels.append("Nadväzná rekvizita")
        if any(
            r["original_stable_name"] in {"Auto / vozidlo", "Sofiino auto"}
            for r in scene_records
        ):
            labels.append("Auto")
        scene["labels"] = labels
    if consumed != set(records):
        raise ValueError("identity map contains orphan records")

    order = {
        scene["scene_id"]: (scene["episode"], scene["order_in_episode"])
        for scene in result["scenes"]
    }
    props_by_group = {}
    for scene in result["scenes"]:
        for prop in scene["props"]:
            if prop.get("continuity"):
                props_by_group.setdefault(prop["registry_key"], []).append(
                    (scene["scene_id"], prop)
                )
    for group, occurrences in props_by_group.items():
        occurrences.sort(key=lambda item: order[item[0]])
        for index, (scene_id, prop) in enumerate(occurrences):
            prop["previous"] = (
                None if index == 0 else {
                    "scene_id": occurrences[index - 1][0],
                    "state": occurrences[index - 1][1]["current_state"],
                }
            )
            prop["next"] = (
                None if index == len(occurrences) - 1 else {
                    "scene_id": occurrences[index + 1][0],
                    "state": occurrences[index + 1][1]["current_state"],
                }
            )
    for entry in registries.values():
        entry["occurrences"].sort(key=lambda item: order[item["scene_id"]])
    result["prop_registry"] = registries
    result["stats"]["reviewed_prop_items"] = identity_map["reviewed_current_items"]
    result["stats"]["included_prop_items"] = sum(
        len(scene["props"]) for scene in result["scenes"]
    )
    result["stats"]["excluded_prop_false_positives"] = sum(
        not record["include"] for record in records.values()
    )
    return result
