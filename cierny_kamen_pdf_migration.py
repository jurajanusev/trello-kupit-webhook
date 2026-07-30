from __future__ import annotations

import json
import re
from pathlib import Path

from flask import jsonify, request


KEY = "cierny-kamen-pdf-migration-30jul-4f7c2a91"
RENAME = {"01/12LP": "01/12FLASH"}
AUTOMATION_LABELS = ("Nadväzná rekvizita", "Nadväzný set", "Auto")


class Migration:
    def __init__(self, api):
        self.api = api
        self.root = Path(api["__file__"]).parent

    def payload(self):
        return json.loads(
            (self.root / "cierny_kamen_pdf_payload.json").read_text(
                encoding="utf-8"
            )
        )

    def old_payload(self):
        return self.api["cierny_kamen_import_payload"]()

    def diff(self):
        return json.loads(
            (
                self.root / "cierny_kamen_pdf_migration_diff.json"
            ).read_text(encoding="utf-8")
        )

    def state(self, payload):
        return self.api["cierny_kamen_import_state"](payload)

    def audit(self, payload, state):
        return self.api["cierny_kamen_target_audit"](payload, state)

    def scene_maps(self, payload, state):
        raw = self.api["cierny_kamen_scene_cards_by_id"](state)
        mapped = {}
        collisions = {}
        for scene in payload["scenes"]:
            scene_id = scene["scene_id"]
            aliases = [scene_id]
            if scene_id in RENAME:
                aliases.append(RENAME[scene_id])
            matches = {
                card["id"]: card
                for alias in aliases
                for card in raw.get(alias, [])
            }
            if len(matches) == 1:
                mapped[scene_id] = next(iter(matches.values()))
            elif len(matches) > 1:
                collisions[scene_id] = [
                    {
                        "id": card["id"],
                        "name": card.get("name"),
                        "url": card.get("shortUrl"),
                    }
                    for card in matches.values()
                ]
        return mapped, collisions, raw

    def registry_maps(self, payload, state):
        prop, prop_duplicates = self.api[
            "cierny_kamen_registry_cards"
        ](state, "PROP", payload)
        sets, set_duplicates = self.api[
            "cierny_kamen_registry_cards"
        ](state, "SET", payload)
        return {
            "PROP": prop,
            "SET": sets,
            "duplicates": {
                "PROP": prop_duplicates,
                "SET": set_duplicates,
            },
        }

    def urls(self, payload, registry_maps, allow_fake=False):
        result = {}
        missing = {}
        for kind, source in (
            ("PROP", payload["prop_registry"]),
            ("SET", payload["set_registry"]),
        ):
            result[kind] = {}
            missing[kind] = []
            for key in source:
                card = registry_maps[kind].get(key)
                if card and card.get("shortUrl"):
                    result[kind][key] = card["shortUrl"]
                else:
                    missing[kind].append(key)
                    if allow_fake:
                        result[kind][key] = (
                            f"https://trello.com/c/DRYRUN-{kind}-{key}"
                        )
        return result, missing

    def old_scene(self, scene, old_payload):
        scene_id = RENAME.get(scene["scene_id"], scene["scene_id"])
        return next(
            (
                item for item in old_payload["scenes"]
                if item["scene_id"] == scene_id
            ),
            None,
        )

    def preserve_scene_manual(self, actual, desired):
        if not actual:
            return desired
        return self.api["cierny_kamen_preserve_manual_description"](
            actual, desired
        )

    def preserve_registry_manual(self, actual, desired):
        boundary = "## RUČNÉ POZNÁMKY\n"
        if boundary not in desired:
            raise RuntimeError("registry manual boundary missing")
        manual = ""
        if boundary in (actual or ""):
            manual = actual.split(boundary, 1)[1]
        return desired.split(boundary, 1)[0] + boundary + manual

    def checklist_plan(
        self,
        card,
        scene,
        old_scene,
        urls,
        old_urls,
    ):
        checklists = self.api["trello_get"](
            f"/cards/{card['id']}/checklists",
            {"checkItems": "all", "fields": "id,name,pos"},
        )
        checklists = sorted(
            checklists, key=lambda item: item.get("pos", 0)
        )
        names = [item.get("name") for item in checklists]
        required = self.api["CIERNY_KAMEN_IMPORT_CHECKLISTS"]
        if names != required[:len(names)]:
            return {
                "errors": [f"checklist order/name mismatch: {names}"],
                "operations": [],
                "manual_items": 0,
            }
        expected = self.api["cierny_kamen_scene_checklists"](
            scene, urls["PROP"], urls["SET"]
        )
        old_expected = (
            self.api["cierny_kamen_scene_checklists"](
                old_scene, old_urls["PROP"], old_urls["SET"]
            )
            if old_scene
            else {name: [] for name in required}
        )
        by_name = {item["name"]: item for item in checklists}
        operations = []
        manual_count = 0
        for name in ("REKVIZITY", "SET"):
            if name not in by_name:
                continue
            checklist = by_name[name]
            actual_items = sorted(
                checklist.get("checkItems", []),
                key=lambda item: item.get("pos", 0),
            )
            old_auto = set(old_expected[name])
            new_auto = set(expected[name])
            manual = [
                item for item in actual_items
                if item.get("name") not in old_auto
                and item.get("name") not in new_auto
            ]
            manual_count += len(manual)
            desired_names = expected[name] + [
                item.get("name") for item in manual
            ]
            if [item.get("name") for item in actual_items] == desired_names:
                continue
            operations.append({
                "type": "replace",
                "card_id": card["id"],
                "checklist_id": checklist["id"],
                "name": name,
                "remove": [
                    item for item in actual_items
                    if item.get("name") in old_auto
                    or item.get("name") in new_auto
                ],
                "add": expected[name],
            })
        if "OTÁZKY NA PORADU" in by_name:
            questions = by_name["OTÁZKY NA PORADU"]
            existing_questions = {
                item.get("name")
                for item in questions.get("checkItems", [])
            }
            additions = [
                item for item in expected["OTÁZKY NA PORADU"]
                if item not in existing_questions
            ]
            if additions:
                operations.append({
                    "type": "append",
                    "checklist_id": questions["id"],
                    "name": "OTÁZKY NA PORADU",
                    "add": additions,
                })
        for name in required[len(names):]:
            operations.append({
                "type": "create_checklist",
                "card_id": card["id"],
                "name": name,
                "add": expected[name],
            })
        return {
            "errors": [],
            "operations": operations,
            "manual_items": manual_count,
        }

    def scene_plan(
        self,
        payload,
        old_payload,
        state,
        audit,
        scene_cards,
        registry_maps,
        scene,
        allow_fake=False,
    ):
        urls, missing = self.urls(
            payload, registry_maps, allow_fake=allow_fake
        )
        card = scene_cards.get(scene["scene_id"])
        label_ids = {
            name: matches[0]["id"]
            for name, matches in audit["desired_labels"].items()
        }
        required_props = {
            item["registry_key"]
            for item in scene["props"]
            if item.get("continuity")
        }
        required_sets = {
            item["registry_key"]
            for item in scene["set_items"]
            if item.get("continuity")
        }
        missing_required = {
            "PROP": sorted(required_props & set(missing["PROP"])),
            "SET": sorted(required_sets & set(missing["SET"])),
        }
        errors = []
        if (
            not allow_fake
            and (missing_required["PROP"] or missing_required["SET"])
        ):
            errors.append(f"missing registry URLs: {missing_required}")
            return {
                "scene_id": scene["scene_id"],
                "card": card,
                "create": card is None,
                "errors": errors,
            }
        expected_desc = self.api["cierny_kamen_scene_description"](
            scene, urls["PROP"], urls["SET"]
        )
        desired_desc = self.preserve_scene_manual(
            card.get("desc") if card else "", expected_desc
        )
        automation_ids = {
            label_ids[name] for name in AUTOMATION_LABELS
        }
        existing_labels = set(card.get("idLabels", [])) if card else set()
        desired_labels = sorted(
            (existing_labels - automation_ids)
            | {label_ids[name] for name in scene["labels"]}
        )
        plan = {
            "scene_id": scene["scene_id"],
            "card": card,
            "create": card is None,
            "name_changed": bool(
                card and card.get("name") != scene["name"]
            ),
            "description_changed": bool(
                card and card.get("desc") != desired_desc
            ),
            "labels_changed": bool(
                card
                and sorted(card.get("idLabels", [])) != desired_labels
            ),
            "desired_name": scene["name"],
            "desired_desc": desired_desc,
            "desired_labels": desired_labels,
            "checklist_operations": [],
            "manual_items": 0,
            "errors": errors,
        }
        if not card:
            return plan
        old_registry_maps = self.registry_maps(old_payload, state)
        old_urls, old_missing = self.urls(
            old_payload, old_registry_maps, allow_fake=True
        )
        if old_missing["PROP"] or old_missing["SET"]:
            errors.append(f"old registry URLs missing: {old_missing}")
        checklist = self.checklist_plan(
            card,
            scene,
            self.old_scene(scene, old_payload),
            urls,
            old_urls,
        )
        plan["checklist_operations"] = checklist["operations"]
        plan["manual_items"] = checklist["manual_items"]
        plan["errors"].extend(checklist["errors"])
        return plan

    def apply_checklists(self, operations):
        writes = 0
        for operation in operations:
            if operation["type"] == "create_checklist":
                checklist = self.api["trello_post_body"](
                    f"/cards/{operation['card_id']}/checklists",
                    {"name": operation["name"], "pos": "bottom"},
                )
                writes += 1
                for name in operation["add"]:
                    self.api["trello_post_body"](
                        f"/checklists/{checklist['id']}/checkItems",
                        {"name": name, "pos": "bottom"},
                    )
                    writes += 1
            elif operation["type"] == "replace":
                for item in operation["remove"]:
                    self.api["trello_delete"](
                        f"/cards/{operation['card_id']}/checkItem/"
                        f"{item['id']}"
                    )
                    writes += 1
                for name in reversed(operation["add"]):
                    self.api["trello_post_body"](
                        f"/checklists/{operation['checklist_id']}"
                        "/checkItems",
                        {"name": name, "pos": "top"},
                    )
                    writes += 1
            else:
                for name in operation["add"]:
                    self.api["trello_post_body"](
                        f"/checklists/{operation['checklist_id']}"
                        "/checkItems",
                        {"name": name, "pos": "bottom"},
                    )
                    writes += 1
        return writes

    def stale_candidates(self, payload, state):
        desired = {
            self.api["cierny_kamen_registry_marker"](kind, key)
            for kind, entries in (
                ("PROP", payload["prop_registry"]),
                ("SET", payload["set_registry"]),
            )
            for key in entries
        }
        candidates = []
        for card in state["cards"]:
            if card.get("closed"):
                continue
            description = card.get("desc") or ""
            match = re.search(
                r"<!-- CIERNY-KAMEN-REGISTRY:(PROP|SET):(.*?) -->",
                description,
            )
            if not match or match.group(0) in desired:
                continue
            boundary = "## RUČNÉ POZNÁMKY\n"
            manual = (
                description.split(boundary, 1)[1].strip()
                if boundary in description
                else ""
            )
            candidates.append({
                "id": card["id"],
                "name": card.get("name"),
                "url": card.get("shortUrl"),
                "kind": match.group(1),
                "key": match.group(2),
                "manual_description": bool(manual),
            })
        return candidates


def register_routes(flask_app, api):
    migration = Migration(api)

    @flask_app.route("/api/migrate-cierny-kamen-pdfs", methods=["POST"])
    def migrate_cierny_kamen_pdfs():
        if request.headers.get("X-PDF-Migration-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        phase = request.args.get("phase", "overview").strip().casefold()
        try:
            start = int(request.args.get("start", "0"))
            limit = int(request.args.get("limit", "10"))
        except ValueError:
            return jsonify({"error": "start and limit must be integers"}), 400
        if start < 0 or limit < 1 or limit > 10:
            return jsonify({"error": "invalid start/limit"}), 400

        payload = migration.payload()
        old_payload = migration.old_payload()
        state = migration.state(payload)
        audit = migration.audit(payload, state)
        scene_cards, collisions, raw_scene_cards = migration.scene_maps(
            payload, state
        )
        registry_maps = migration.registry_maps(payload, state)
        blockers = list(audit["blockers"])
        if collisions:
            blockers.append("rename/card collisions exist")
        if any(registry_maps["duplicates"].values()):
            blockers.append("registry marker duplicates exist")
        if blockers:
            return jsonify({
                "status": "blocked",
                "blockers": blockers,
                "collisions": collisions,
            }), 409

        if phase == "overview":
            stale = migration.stale_candidates(payload, state)
            _urls, missing = migration.urls(
                payload, registry_maps, allow_fake=False
            )
            return jsonify({
                "status": "dry-run",
                "writes": 0,
                "board": {
                    "id": state["board"]["id"],
                    "name": state["board"].get("name"),
                    "url": state["board"].get("url"),
                },
                "source": payload["stats"],
                "source_pdfs": payload["source_pdfs"],
                "diff": migration.diff(),
                "existing_scene_ids": len(raw_scene_cards),
                "matched_target_cards": len(scene_cards),
                "create_count": 313 - len(scene_cards),
                "rename": {
                    "from": "01/12FLASH",
                    "to": "01/12LP",
                    "source_count": len(
                        raw_scene_cards.get("01/12FLASH", [])
                    ),
                    "target_count": len(
                        raw_scene_cards.get("01/12LP", [])
                    ),
                },
                "registry": {
                    "required_props": len(payload["prop_registry"]),
                    "required_sets": len(payload["set_registry"]),
                    "existing_props": len(registry_maps["PROP"]),
                    "existing_sets": len(registry_maps["SET"]),
                    "missing": missing,
                    "stale_candidates": stale,
                },
                "labels": {
                    name: [
                        {"id": item["id"], "name": item.get("name")}
                        for item in matches
                    ]
                    for name, matches in audit[
                        "desired_labels"
                    ].items()
                },
                "duplicates": 0,
                "collisions": collisions,
            }), 200

        if phase in {"dry-run", "apply", "audit"}:
            selected = payload["scenes"][start:start + limit]
            plans = [
                migration.scene_plan(
                    payload,
                    old_payload,
                    state,
                    audit,
                    scene_cards,
                    registry_maps,
                    scene,
                    allow_fake=phase == "dry-run",
                )
                for scene in selected
            ]
            errors = [
                {
                    "scene_id": plan["scene_id"],
                    "errors": plan["errors"],
                }
                for plan in plans
                if plan["errors"]
            ]
            result = {
                "start": start,
                "selected": len(selected),
                "create": sum(plan["create"] for plan in plans),
                "name_change": sum(
                    plan.get("name_changed", False) for plan in plans
                ),
                "description_change": sum(
                    plan.get("description_changed", False)
                    for plan in plans
                ),
                "label_change": sum(
                    plan.get("labels_changed", False) for plan in plans
                ),
                "checklist_change": sum(
                    bool(plan.get("checklist_operations"))
                    for plan in plans
                ),
                "manual_items_preserved": sum(
                    plan.get("manual_items", 0) for plan in plans
                ),
                "errors": errors,
                "remaining": max(
                    0, len(payload["scenes"]) - start - len(selected)
                ),
                "writes": 0,
            }
            if errors:
                return jsonify({"status": "blocked", **result}), 409
            if phase == "dry-run":
                return jsonify({"status": phase, **result}), 200
            pending = any(
                plan["create"]
                or plan.get("name_changed")
                or plan.get("description_changed")
                or plan.get("labels_changed")
                or plan.get("checklist_operations")
                for plan in plans
            )
            if phase == "audit":
                return jsonify({
                    "status": "audit",
                    "valid": not pending,
                    **result,
                }), 200 if not pending else 409

            writes = 0
            created = []
            updated = []
            urls, _missing = migration.urls(
                payload, registry_maps, allow_fake=False
            )
            for scene, plan in zip(selected, plans):
                if plan["create"]:
                    card = api["cierny_kamen_create_card"](
                        audit["scene_lists"][0]["id"],
                        plan["desired_name"],
                        plan["desired_desc"],
                        plan["desired_labels"],
                    )
                    api["cierny_kamen_create_checklists"](
                        card["id"],
                        api["cierny_kamen_scene_checklists"](
                            scene, urls["PROP"], urls["SET"]
                        ),
                    )
                    created.append({
                        "scene_id": scene["scene_id"],
                        "id": card["id"],
                        "url": card.get("shortUrl"),
                    })
                    writes += 6
                    continue
                card_update = {}
                if plan["name_changed"]:
                    card_update["name"] = plan["desired_name"]
                if plan["description_changed"]:
                    card_update["desc"] = plan["desired_desc"]
                if plan["labels_changed"]:
                    card_update["idLabels"] = ",".join(
                        plan["desired_labels"]
                    )
                if card_update:
                    api["trello_put_body"](
                        f"/cards/{plan['card']['id']}", card_update
                    )
                    writes += 1
                checklist_writes = migration.apply_checklists(
                    plan["checklist_operations"]
                )
                writes += checklist_writes
                if card_update or checklist_writes:
                    updated.append(scene["scene_id"])
            return jsonify({
                "status": "applied",
                **result,
                "writes": writes,
                "created": created,
                "updated": updated,
            }), 200

        if phase == "registry-init":
            entries = [
                (kind, key, entry)
                for kind, source in (
                    ("PROP", payload["prop_registry"]),
                    ("SET", payload["set_registry"]),
                )
                for key, entry in sorted(source.items())
            ]
            selected = entries[start:start + limit]
            list_ids = {
                "PROP": audit["prop_lists"][0]["id"],
                "SET": audit["set_lists"][0]["id"],
            }
            created = []
            unchanged = []
            for kind, key, entry in selected:
                if registry_maps[kind].get(key):
                    unchanged.append({"kind": kind, "key": key})
                    continue
                marker = api["cierny_kamen_registry_marker"](kind, key)
                card = api["cierny_kamen_create_card"](
                    list_ids[kind],
                    entry["identity"],
                    (
                        f"{marker}\n# HLAVNÁ KARTA KONTINUITY\n\n"
                        f"**IDENTITA:** `{entry['identity']}`\n\n"
                        "## RUČNÉ POZNÁMKY\n"
                    ),
                )
                created.append({
                    "kind": kind,
                    "key": key,
                    "id": card["id"],
                    "url": card.get("shortUrl"),
                })
            return jsonify({
                "status": "applied",
                "start": start,
                "selected": len(selected),
                "created": created,
                "unchanged": unchanged,
                "remaining": max(
                    0, len(entries) - start - len(selected)
                ),
            }), 200

        if phase in {
            "registry-dry-run",
            "registry-sync",
            "registry-audit",
        }:
            entries = [
                (kind, key, entry)
                for kind, source in (
                    ("PROP", payload["prop_registry"]),
                    ("SET", payload["set_registry"]),
                )
                for key, entry in sorted(source.items())
            ]
            selected = entries[start:start + limit]
            scene_urls = {
                scene_id: card.get("shortUrl")
                for scene_id, card in scene_cards.items()
            }
            required_scene_ids = {
                occurrence["scene_id"]
                for _kind, _key, entry in selected
                for occurrence in entry["occurrences"]
            }
            missing_scenes = sorted(required_scene_ids - set(scene_urls))
            if missing_scenes:
                return jsonify({
                    "status": "blocked",
                    "missing_scene_urls": missing_scenes,
                }), 409
            changed = []
            errors = []
            for kind, key, entry in selected:
                card = registry_maps[kind].get(key)
                if not card:
                    errors.append({
                        "kind": kind,
                        "key": key,
                        "error": "registry card missing",
                    })
                    continue
                desired = migration.preserve_registry_manual(
                    card.get("desc"),
                    api["cierny_kamen_registry_description"](
                        kind, key, entry, scene_urls
                    ),
                )
                if "karta obrazu zatiaľ" in desired:
                    errors.append({
                        "kind": kind,
                        "key": key,
                        "error": "placeholder scene link",
                    })
                needs_change = (
                    card.get("name") != entry["identity"]
                    or card.get("desc") != desired
                )
                if needs_change:
                    changed.append({"kind": kind, "key": key})
                    if phase == "registry-sync":
                        api["trello_put_body"](
                            f"/cards/{card['id']}",
                            {
                                "name": entry["identity"],
                                "desc": desired,
                            },
                        )
            valid = not errors and (
                phase != "registry-audit" or not changed
            )
            return jsonify({
                "status": phase,
                "valid": valid,
                "start": start,
                "selected": len(selected),
                "changed": changed,
                "errors": errors,
                "writes": (
                    len(changed) if phase == "registry-sync" else 0
                ),
                "remaining": max(
                    0, len(entries) - start - len(selected)
                ),
            }), 200 if valid or phase != "registry-audit" else 409

        if phase in {
            "stale-registry-dry-run",
            "stale-registry-archive",
        }:
            candidates = migration.stale_candidates(payload, state)
            selected = candidates[start:start + limit]
            results = []
            for candidate in selected:
                checklists = api["trello_get"](
                    f"/cards/{candidate['id']}/checklists",
                    {"checkItems": "all", "fields": "id,name,pos"},
                )
                attachments = api["trello_get"](
                    f"/cards/{candidate['id']}/attachments",
                    {"fields": "id,name,url"},
                )
                manual = (
                    candidate["manual_description"]
                    or bool(checklists)
                    or bool(attachments)
                )
                result = {**candidate, "manual_data": manual}
                results.append(result)
                if phase == "stale-registry-archive" and not manual:
                    api["trello_put_body"](
                        f"/cards/{candidate['id']}",
                        {"closed": "true"},
                    )
            return jsonify({
                "status": phase,
                "start": start,
                "selected": len(selected),
                "results": results,
                "archived": (
                    sum(not item["manual_data"] for item in results)
                    if phase == "stale-registry-archive"
                    else 0
                ),
                "preserved": sum(
                    item["manual_data"] for item in results
                ),
                "remaining": max(
                    0, len(candidates) - start - len(selected)
                ),
            }), 200

        return jsonify({"error": "unknown phase"}), 400
