from __future__ import annotations

import hashlib
import re

from flask import jsonify, request

from meeting_notes_dryrun import classify_item, folded, list_kind


KEY = "ck-meeting-notes-ep01-03-16aug-4f8c2d91"
BOARD_REF = "CzuD55PR"
START = "<!-- CIERNY-KAMEN-MEETING-NOTES:START -->"
END = "<!-- CIERNY-KAMEN-MEETING-NOTES:END -->"
ITEM_MARKER = "CIERNY-KAMEN-MEETING-ITEM:"
SOURCE_CHECKLISTS = {"info z porady", "info z natacania"}


def scene_episode(scene_id):
    match = re.match(r"^0*(\d+)\s*/", str(scene_id or ""))
    return int(match.group(1)) if match else None


def protected_snapshot(card):
    rows = []
    for checklist in sorted(card.get("checklists", []), key=lambda row: row.get("pos", 0)):
        if folded(checklist.get("name")) not in SOURCE_CHECKLISTS:
            continue
        for item in sorted(checklist.get("checkItems", []), key=lambda row: row.get("pos", 0)):
            rows.append("\x1f".join((
                str(checklist.get("id") or ""), str(checklist.get("name") or ""),
                str(item.get("id") or ""), str(item.get("name") or ""),
                str(item.get("state") or ""), str(item.get("pos") or ""),
            )))
    value = (card.get("desc") or "") + "\x1e" + "\x1e".join(rows)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def source_notes(card):
    resolved = []
    ambiguous = []
    ignored = []
    for checklist in sorted(card.get("checklists", []), key=lambda row: row.get("pos", 0)):
        checklist_name = checklist.get("name") or ""
        if folded(checklist_name) not in SOURCE_CHECKLISTS:
            continue
        for item in sorted(checklist.get("checkItems", []), key=lambda row: row.get("pos", 0)):
            classification = classify_item(checklist_name, item.get("name"))
            row = {
                "checklist": checklist_name, "checklist_id": checklist.get("id"),
                "item_id": item.get("id"), "text": item.get("name") or "",
                "state": item.get("state"), "pos": item.get("pos"),
                **classification,
            }
            if classification["classification"] == "ambiguous":
                ambiguous.append(row)
            elif classification["classification"] == "ignored_placeholder":
                ignored.append(row)
            else:
                resolved.append(row)
    return resolved, ambiguous, ignored


def meeting_line(note):
    return (
        f"- <!-- {ITEM_MARKER}{note['item_id']} --> "
        f"**{note['checklist']}:** {note['text']}"
    )


def locate_manual_section(desc):
    lines = desc.splitlines(keepends=True)
    manual = None
    next_heading = None
    for index, line in enumerate(lines):
        heading = folded(line.strip().lstrip("#").strip())
        if heading == "rucne doplnenia":
            manual = index
            continue
        if manual is not None and line.lstrip().startswith("#"):
            next_heading = index
            break
    if manual is None or next_heading is None:
        return None
    return lines, manual, next_heading


def enrich_description(desc, notes):
    pending = [note for note in notes if f"{ITEM_MARKER}{note['item_id']}" not in desc]
    if not pending:
        return desc, [], None
    located = locate_manual_section(desc)
    if not located:
        return desc, [], "RUČNÉ DOPLNENIA section boundary is not unambiguous"
    lines, _manual, next_heading = located
    block_match = re.search(
        re.escape(START) + r".*?" + re.escape(END), desc, flags=re.S
    )
    new_lines = [meeting_line(note) for note in pending]
    if block_match:
        block = block_match.group(0)
        replacement = block[:-len(END)].rstrip() + "\n" + "\n".join(new_lines) + "\n" + END
        return desc[:block_match.start()] + replacement + desc[block_match.end():], pending, None

    insertion = "\n".join((START, *new_lines, END))
    prefix = "".join(lines[:next_heading]).rstrip()
    suffix = "".join(lines[next_heading:]).lstrip("\r\n")
    return prefix + "\n\n" + insertion + "\n\n" + suffix, pending, None


def load_cards(api):
    trello_get = api["trello_get"]
    board = trello_get(f"/boards/{BOARD_REF}", {"fields": "id,name,url,closed"})
    lists = trello_get(f"/boards/{board['id']}/lists", {
        "fields": "id,name,closed,pos", "filter": "all",
    })
    active_ids = {
        item["id"] for item in lists
        if not item.get("closed") and list_kind(item.get("name")) == "active"
    }
    cards = trello_get(f"/boards/{board['id']}/cards", {
        "fields": "id,name,desc,shortUrl,idList,closed,pos",
        "filter": "open", "limit": 1000,
        "checklists": "all", "checklist_fields": "name,pos",
    })
    parser = api["scene_id_from_card_name"]
    selected = []
    for card in cards:
        if card.get("idList") not in active_ids:
            continue
        scene_id = parser(card.get("name"))
        if scene_episode(scene_id) not in {1, 2, 3}:
            continue
        selected.append({**card, "scene_id": scene_id})
    selected.sort(key=lambda card: (
        scene_episode(card["scene_id"]),
        int(re.search(r"/(\d+)", card["scene_id"]).group(1)),
        card["scene_id"], card["id"],
    ))
    return board, selected


def build_plan(api, only_scene=None):
    board, cards = load_cards(api)
    plans = []
    ambiguous = []
    ignored = []
    for card in cards:
        if only_scene and folded(card["scene_id"]) != folded(only_scene):
            continue
        resolved, card_ambiguous, card_ignored = source_notes(card)
        ambiguous.extend({"scene_id": card["scene_id"], "card": card["name"],
                          "url": card.get("shortUrl"), **row} for row in card_ambiguous)
        ignored.extend({"scene_id": card["scene_id"], "card": card["name"],
                        "url": card.get("shortUrl"), **row} for row in card_ignored)
        desired, pending, conflict = enrich_description(card.get("desc") or "", resolved)
        if pending or conflict:
            plans.append({
                "card": card, "snapshot": protected_snapshot(card),
                "desired_desc": desired, "notes": pending, "conflict": conflict,
            })
    return board, cards, plans, ambiguous, ignored


def public_plan(plan, include_description=False):
    value = {
        "scene_id": plan["card"]["scene_id"], "card": plan["card"]["name"],
        "url": plan["card"].get("shortUrl"), "notes": plan["notes"],
        "note_count": len(plan["notes"]), "conflict": plan["conflict"],
        "description_sha256_before": hashlib.sha256(
            (plan["card"].get("desc") or "").encode("utf-8")
        ).hexdigest(),
        "description_sha256_after": hashlib.sha256(
            plan["desired_desc"].encode("utf-8")
        ).hexdigest(),
    }
    if include_description:
        value["description_before"] = plan["card"].get("desc") or ""
        value["description_after"] = plan["desired_desc"]
    return value


def register_routes(app, api):
    @app.route("/api/apply-ck-meeting-notes-ep01-03", methods=["POST"])
    def apply_ck_meeting_notes_ep01_03():
        if request.headers.get("X-Meeting-Notes-Apply-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "dry-run").strip().casefold()
        if mode not in {"dry-run", "apply"}:
            return jsonify({"error": "mode must be dry-run or apply"}), 400
        only_scene = request.args.get("scene", "").strip() or None
        limit = min(15, max(1, int(request.args.get("limit", "8"))))
        board, cards, plans, ambiguous, ignored = build_plan(api, only_scene=only_scene)
        actionable = [plan for plan in plans if not plan["conflict"] and plan["notes"]]
        conflicts = [plan for plan in plans if plan["conflict"]]
        result = {
            "status": "dry-run", "board": board, "episodes": [1, 2, 3],
            "scene_filter": only_scene, "scene_cards_scanned": len(cards),
            "source_notes": sum(len(source_notes(card)[0]) for card in cards),
            "pending_cards": len(actionable),
            "pending_notes": sum(len(plan["notes"]) for plan in actionable),
            "ambiguous_count": len(ambiguous), "ambiguous": ambiguous,
            "ignored_count": len(ignored), "conflict_count": len(conflicts),
            "conflicts": [public_plan(plan) for plan in conflicts],
            "writes": 0, "trello_todo_writes": 0, "microsoft_todo_accessed": False,
            "sample": [public_plan(plan, include_description=bool(only_scene))
                       for plan in actionable[:5]],
        }
        if mode == "dry-run":
            return jsonify(result), 200

        updated = []
        skipped_conflicts = []
        errors = []
        for plan in actionable[:limit]:
            card = plan["card"]
            try:
                current = api["trello_get"](f"/cards/{card['id']}", {
                    "fields": "id,name,desc,shortUrl,idList,closed,pos",
                    "checklists": "all", "checklist_fields": "name,pos",
                })
                current["scene_id"] = card["scene_id"]
                if protected_snapshot(current) != plan["snapshot"]:
                    skipped_conflicts.append({
                        "scene_id": card["scene_id"], "url": card.get("shortUrl"),
                        "reason": "card or source notes changed after dry-run",
                    })
                    continue
                written = api["trello_put_body"](
                    f"/cards/{card['id']}", {"desc": plan["desired_desc"]}
                )
                read_back = api["trello_get"](
                    f"/cards/{card['id']}", {"fields": "id,desc,shortUrl"}
                )
                if read_back.get("desc") != plan["desired_desc"]:
                    raise RuntimeError("description read-back mismatch")
                updated.append({
                    "scene_id": card["scene_id"], "url": written.get("shortUrl") or card.get("shortUrl"),
                    "notes_added": len(plan["notes"]),
                })
            except Exception as error:
                errors.append({"scene_id": card["scene_id"], "error": str(error)})
        result.update({
            "status": "applied", "writes": len(updated), "updated": updated,
            "skipped_concurrent_conflicts": skipped_conflicts, "errors": errors,
            "remaining_before_reaudit": max(0, len(actionable) - len(updated)),
        })
        return jsonify(result), (200 if not errors else 207)

