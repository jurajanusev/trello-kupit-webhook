from __future__ import annotations

import copy
import json
from pathlib import Path


MAP_PATH = Path(__file__).with_name("cierny_kamen_prop_identity_map.json")


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
            prop = {
                "stable_name": record["stable_name"],
                "action": record["action"],
                "source_text": f"{record['stable_name']} — {record['action']}",
                "continuity": bool(record["continuity_group"]),
            }
            group = record["continuity_group"]
            if group:
                prop.update({
                    "registry_key": group,
                    "current_state": record["current_state"],
                    "previous": None,
                    "next": None,
                })
                entry = registries.setdefault(group, {
                    "identity": record["stable_name"],
                    "aliases": [record["stable_name"]],
                    "occurrences": [],
                })
                if entry["identity"] != record["stable_name"]:
                    raise ValueError(
                        f"{group}: inconsistent stable names "
                        f"{entry['identity']!r} and {record['stable_name']!r}"
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
