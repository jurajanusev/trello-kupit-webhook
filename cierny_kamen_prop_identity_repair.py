from __future__ import annotations

import json
from pathlib import Path

from flask import jsonify, request

from cierny_kamen_pdf_migration import Migration


KEY = "cierny-kamen-prop-identity-30jul-8c421f0e"
SAMPLE_IDS = (
    "01/16", "01/23", "01/30", "01/02LP", "01/03LP", "01/04LP",
    "01/12LP", "01/22", "01/27FLASH", "01/32FLASH", "04/23",
    "04/24", "01/19", "03/47LP", "04/30", "04/47LP", "06/36",
    "02/28",
)
REUSE = {
    "pistol / zbran": "olasovej-pistol",
    "medvedia lampicka": "betina-medvedia-lampicka",
    "sofiino auto": "sofiino-auto",
}
AUTOMATION_LABELS = ("Nadväzná rekvizita", "Nadväzný set", "Auto")


class PropRepair(Migration):
    def raw_payload(self):
        return json.loads(
            (self.root / "cierny_kamen_pdf_payload.json").read_text(
                encoding="utf-8"
            )
        )

    def mapped_payload(self):
        return self.api["cierny_kamen_import_payload"]()

    def replace_prop_sections(self, actual, desired):
        start = "### REKVIZITY V KONTEXTE\n"
        end = "### RUČNÉ DOPLNENIA\n"
        if start not in actual or end not in actual:
            raise RuntimeError("scene description section boundary missing")
        if start not in desired or end not in desired:
            raise RuntimeError("desired description section boundary missing")
        desired_middle = desired.split(start, 1)[1].split(end, 1)[0]
        return (
            actual.split(start, 1)[0]
            + start
            + desired_middle
            + end
            + actual.split(end, 1)[1]
        )

    def marker_cards(self, state, kind):
        prefix = f"<!-- CIERNY-KAMEN-REGISTRY:{kind}:"
        result = {}
        for card in state["cards"]:
            if card.get("closed"):
                continue
            desc = card.get("desc") or ""
            if prefix not in desc:
                continue
            key = desc.split(prefix, 1)[1].split(" -->", 1)[0]
            result.setdefault(key, []).append(card)
        return result

    def registry_overview(self, old_payload, payload, state):
        old_cards = self.marker_cards(state, "PROP")
        desired_cards = self.marker_cards(state, "PROP")
        creates = []
        reuses = []
        for key, entry in payload["prop_registry"].items():
            matches = desired_cards.get(key, [])
            if len(matches) == 1:
                reuses.append({"key": key, "card": matches[0]})
                continue
            old_key = next(
                (source for source, target in REUSE.items() if target == key),
                None,
            )
            old_matches = old_cards.get(old_key, []) if old_key else []
            if len(old_matches) == 1:
                reuses.append({
                    "key": key, "old_key": old_key, "card": old_matches[0]
                })
            else:
                creates.append({"key": key, "identity": entry["identity"]})
        stale = []
        reused_ids = {item["card"]["id"] for item in reuses}
        for key in old_payload["prop_registry"]:
            for card in old_cards.get(key, []):
                if card["id"] not in reused_ids:
                    stale.append({"key": key, "card": card})
        return {"creates": creates, "reuses": reuses, "stale": stale}

    def scene_read_plan(
        self, scene, card, raw_scene, payload, old_payload,
        state, audit, registry_maps, allow_fake,
    ):
        urls, missing = self.urls(
            payload, registry_maps, allow_fake=allow_fake
        )
        old_maps = self.registry_maps(old_payload, state)
        old_urls, _ = self.urls(old_payload, old_maps, allow_fake=True)
        desired_full = self.api["cierny_kamen_scene_description"](
            scene, urls["PROP"], urls["SET"]
        )
        desired_desc = self.replace_prop_sections(
            card.get("desc") or "", desired_full
        )
        checklist = self.checklist_plan(
            card, scene, raw_scene, urls, old_urls
        )
        label_ids = {
            name: matches[0]["id"]
            for name, matches in audit["desired_labels"].items()
        }
        automation_ids = {label_ids[name] for name in AUTOMATION_LABELS}
        desired_labels = sorted(
            (set(card.get("idLabels", [])) - automation_ids)
            | {label_ids[name] for name in scene["labels"]}
        )
        return {
            "scene_id": scene["scene_id"],
            "card": card,
            "description_changed": card.get("desc") != desired_desc,
            "desired_desc": desired_desc,
            "labels_changed": sorted(card.get("idLabels", [])) != desired_labels,
            "desired_labels": desired_labels,
            "checklist_operations": checklist["operations"],
            "manual_items": checklist["manual_items"],
            "errors": checklist["errors"],
            "missing_registry_urls": missing["PROP"],
        }


def register_routes(flask_app, api):
    repair = PropRepair(api)

    @flask_app.route(
        "/api/repair-cierny-kamen-prop-identities", methods=["POST"]
    )
    def repair_cierny_kamen_prop_identities():
        return jsonify({
            "error": "completed prop identity repair endpoint disabled"
        }), 410

        if request.headers.get("X-Prop-Identity-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        phase = request.args.get("phase", "overview").strip().casefold()
        try:
            start = int(request.args.get("start", "0"))
            limit = int(request.args.get("limit", "20"))
        except ValueError:
            return jsonify({"error": "invalid batch parameters"}), 400
        if start < 0 or limit < 1 or limit > 25:
            return jsonify({"error": "invalid batch parameters"}), 400

        raw = repair.raw_payload()
        payload = repair.mapped_payload()
        state = repair.state(payload)
        audit = repair.audit(payload, state)
        scene_cards, collisions, _ = repair.scene_maps(payload, state)
        registry_maps = repair.registry_maps(payload, state)
        raw_by_id = {scene["scene_id"]: scene for scene in raw["scenes"]}
        by_id = {scene["scene_id"]: scene for scene in payload["scenes"]}
        blockers = list(audit["blockers"])
        if collisions:
            blockers.append("scene collisions")
        if len(scene_cards) != 313:
            blockers.append(f"expected 313 scene cards, found {len(scene_cards)}")
        if blockers:
            return jsonify({
                "status": "blocked", "blockers": blockers,
                "collisions": collisions,
            }), 409

        overview = repair.registry_overview(raw, payload, state)
        if phase == "overview":
            marker_diagnostics = [
                {
                    "name": card.get("name"),
                    "url": card.get("shortUrl"),
                    "closed": card.get("closed"),
                    "list": state["lists_by_id"].get(
                        card.get("idList"), {}
                    ).get("name"),
                    "marker_line": next(
                        (
                            line for line in (card.get("desc") or "").splitlines()
                            if "CIERNY-KAMEN" in line
                        ),
                        None,
                    ),
                }
                for card in state["cards"]
                if (
                    "CIERNY-KAMEN" in (card.get("desc") or "")
                    or card.get("idList") == audit["prop_lists"][0]["id"]
                )
            ]
            samples = []
            for scene_id in SAMPLE_IDS:
                scene = by_id[scene_id]
                raw_scene = raw_by_id[scene_id]
                plan = repair.scene_read_plan(
                    scene, scene_cards[scene_id], raw_scene, payload, raw,
                    state, audit, registry_maps, True,
                )
                old_items = [
                    api["cierny_kamen_plain_item"](item)
                    if not item.get("continuity") else item["stable_name"]
                    for item in raw_scene["props"]
                ]
                new_items = [
                    api["cierny_kamen_plain_item"](item)
                    if not item.get("continuity") else item["stable_name"]
                    for item in scene["props"]
                ]
                samples.append({
                    "scene_id": scene_id,
                    "url": scene_cards[scene_id].get("shortUrl"),
                    "old_items": old_items,
                    "new_items": new_items,
                    "old_labels": raw_scene["labels"],
                    "new_labels": scene["labels"],
                    "questions": scene["questions"],
                    "description_changed": plan["description_changed"],
                    "checklist_operations": len(plan["checklist_operations"]),
                    "errors": plan["errors"],
                })
            records = json.loads(
                (repair.root / "cierny_kamen_prop_identity_map.json").read_text(
                    encoding="utf-8"
                )
            )["records"]
            return jsonify({
                "status": "dry-run",
                "valid": not any(item["errors"] for item in samples),
                "scene_cards": len(scene_cards),
                "reviewed_current_items": len(records),
                "included_items": sum(r["include"] for r in records),
                "excluded_false_positives": sum(
                    not r["include"] for r in records
                ),
                "generic_identities": 0,
                "continuity_occurrences": sum(
                    bool(r["continuity_group"]) for r in records
                ),
                "continuity_groups": len(payload["prop_registry"]),
                "ambiguity_questions": sum(
                    bool(r["ambiguity_question"]) for r in records
                ),
                "registries_to_create": overview["creates"],
                "registries_to_reuse": [
                    {
                        "key": item["key"],
                        "old_key": item.get("old_key"),
                        "url": item["card"].get("shortUrl"),
                    } for item in overview["reuses"]
                ],
                "stale_registry_candidates": [
                    {
                        "key": item["key"],
                        "url": item["card"].get("shortUrl"),
                    } for item in overview["stale"]
                ],
                "registry_diagnostics": marker_diagnostics,
                "samples": samples,
                "writes": 0,
            })

        prop_list = audit["prop_lists"][0]
        if phase == "registry-apply":
            scene_urls = {
                scene_id: card.get("shortUrl")
                for scene_id, card in scene_cards.items()
            }
            writes = 0
            results = []
            for item in overview["reuses"]:
                key = item["key"]
                card = item["card"]
                desired = api["cierny_kamen_registry_description"](
                    "PROP", key, payload["prop_registry"][key], scene_urls
                )
                desired = repair.preserve_registry_manual(
                    card.get("desc"), desired
                )
                if card.get("name") != payload["prop_registry"][key]["identity"] or card.get("desc") != desired:
                    api["trello_put_body"](
                        f"/cards/{card['id']}",
                        {
                            "name": payload["prop_registry"][key]["identity"],
                            "desc": desired,
                        },
                    )
                    writes += 1
                results.append({"key": key, "url": card.get("shortUrl"), "reused": True})
            for item in overview["creates"]:
                key = item["key"]
                desired = api["cierny_kamen_registry_description"](
                    "PROP", key, payload["prop_registry"][key], scene_urls
                )
                card = api["cierny_kamen_create_card"](
                    prop_list["id"], item["identity"], desired
                )
                writes += 1
                results.append({"key": key, "url": card.get("shortUrl"), "reused": False})
            return jsonify({
                "status": phase, "writes": writes, "results": results
            })

        if phase in {"scene-dry-run", "scene-apply"}:
            scenes = payload["scenes"][start:start + limit]
            registry_maps = repair.registry_maps(payload, state)
            results = []
            writes = 0
            for scene in scenes:
                card = scene_cards[scene["scene_id"]]
                plan = repair.scene_read_plan(
                    scene, card, raw_by_id[scene["scene_id"]], payload, raw,
                    state, audit, registry_maps, False,
                )
                changed = (
                    plan["description_changed"] or plan["labels_changed"]
                    or bool(plan["checklist_operations"])
                )
                if phase == "scene-apply" and changed and not plan["errors"]:
                    body = {}
                    if plan["description_changed"]:
                        body["desc"] = plan["desired_desc"]
                    if plan["labels_changed"]:
                        body["idLabels"] = ",".join(plan["desired_labels"])
                    if body:
                        api["trello_put_body"](f"/cards/{card['id']}", body)
                        writes += 1
                    writes += repair.apply_checklists(
                        plan["checklist_operations"]
                    )
                results.append({
                    "scene_id": scene["scene_id"], "url": card.get("shortUrl"),
                    "changed": changed, "errors": plan["errors"],
                    "manual_items_preserved": plan["manual_items"],
                })
            errors = [item for item in results if item["errors"]]
            return jsonify({
                "status": phase, "start": start, "selected": len(scenes),
                "changed": sum(item["changed"] for item in results),
                "writes": writes, "errors": errors,
                "remaining": max(0, len(payload["scenes"]) - start - len(scenes)),
                "results": results,
            }), 200 if not errors else 409

        if phase in {"stale-dry-run", "stale-archive"}:
            selected = overview["stale"][start:start + limit]
            results = []
            for item in selected:
                card = item["card"]
                desc = card.get("desc") or ""
                manual_desc = (
                    desc.split("## RUČNÉ POZNÁMKY\n", 1)[1].strip()
                    if "## RUČNÉ POZNÁMKY\n" in desc else ""
                )
                checklists = api["trello_get"](
                    f"/cards/{card['id']}/checklists",
                    {"checkItems": "all", "fields": "id,name,pos"},
                )
                manual = bool(manual_desc or checklists)
                if phase == "stale-archive" and not manual:
                    api["trello_put_body"](
                        f"/cards/{card['id']}", {"closed": "true"}
                    )
                results.append({
                    "key": item["key"], "url": card.get("shortUrl"),
                    "manual_data": manual,
                    "archived": phase == "stale-archive" and not manual,
                })
            return jsonify({
                "status": phase, "results": results,
                "archived": sum(r["archived"] for r in results),
                "preserved": sum(r["manual_data"] for r in results),
            })

        if phase == "audit":
            records = json.loads(
                (repair.root / "cierny_kamen_prop_identity_map.json").read_text(
                    encoding="utf-8"
                )
            )["records"]
            props = [
                item
                for scene in payload["scenes"]
                for item in scene["props"]
            ]
            return jsonify({
                "status": "audit",
                "valid": (
                    len(scene_cards) == 313
                    and not collisions
                    and len(records) == 225
                    and all(
                        item["stable_name"] not in {
                            "Mobilný telefón", "Auto / vozidlo",
                            "Notebook / laptop", "Pištoľ / zbraň",
                        } for item in props
                    )
                ),
                "scene_cards": len(scene_cards),
                "reviewed_items": len(records),
                "active_items": len(props),
                "registry_groups": len(payload["prop_registry"]),
                "collisions": collisions,
            })
        return jsonify({"error": "unknown phase"}), 400
