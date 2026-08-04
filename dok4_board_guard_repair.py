from __future__ import annotations

import re
from collections import defaultdict

from flask import jsonify, request


KEY = "dok4-board-guard-4aug-5d91c2e7"
BOARD_REFS = {
    "dunaj": "qCPeWA3e",
    "dok4": "lzNy4AtY",
    "riverdale": "CzuD55PR",
}
SYNC_START = "<!-- DUNAJ-PROP-SYNC:START -->"
SYNC_END = "<!-- DUNAJ-PROP-SYNC:END -->"


def automatic_marker(desc):
    if SYNC_START not in (desc or "") or SYNC_END not in desc:
        return None
    return desc[
        desc.index(SYNC_START):desc.index(SYNC_END) + len(SYNC_END)
    ]


def replace_marker_preserving_manual(desc, marker):
    old = automatic_marker(desc)
    if not old:
        return marker + ("\n\n" + desc if desc else "")
    return desc.replace(old, marker, 1)


def exact_auto_only(card):
    marker = automatic_marker(card.get("desc") or "")
    badges = card.get("badges") or {}
    return bool(
        marker
        and (card.get("desc") or "").strip() == marker.strip()
        and not badges.get("attachments")
        and not badges.get("checkItems")
        and not badges.get("comments")
    )


class Diagnostic:
    def __init__(self, api):
        self.api = api

    def boards(self):
        result = {}
        for project, ref in BOARD_REFS.items():
            board = self.api["trello_get"](
                f"/boards/{ref}", {"fields": "id,name,url,shortLink"}
            )
            lists = self.api["trello_get"](
                f"/boards/{board['id']}/lists",
                {"fields": "id,name,idBoard,closed", "filter": "open"},
            )
            todo = [
                item for item in lists
                if item.get("name", "").strip().casefold() == "todo"
            ]
            result[project] = {"board": board, "lists": lists, "todo": todo}
        return result

    def runtime_map(self, boards):
        known_lists = {
            item["id"]: {
                "id": item["id"], "name": item.get("name"),
                "idBoard": item.get("idBoard"),
                "board": project,
            }
            for project, data in boards.items() for item in data["lists"]
        }
        rows = []
        for source_id, config in self.api["BOARD_CONFIG"].items():
            target_id = config.get("target_list_id")
            source = known_lists.get(source_id)
            target = known_lists.get(target_id)
            if source is None:
                try:
                    item = self.api["trello_get"](
                        f"/lists/{source_id}",
                        {"fields": "id,name,idBoard,closed"},
                    )
                    source = {**item, "board": None}
                except Exception:
                    source = None
            if target is None:
                try:
                    item = self.api["trello_get"](
                        f"/lists/{target_id}",
                        {"fields": "id,name,idBoard,closed"},
                    )
                    target = {**item, "board": None}
                except Exception:
                    target = None
            rows.append({
                "source_list_id": source_id,
                "source_name": source.get("name") if source else None,
                "source_board_id": source.get("idBoard") if source else None,
                "target_list_id": target_id,
                "target_name": target.get("name") if target else None,
                "target_board_id": target.get("idBoard") if target else None,
                "same_board": bool(
                    source and target
                    and source.get("idBoard") == target.get("idBoard")
                ),
            })
        return rows

    def board_cards(self, board_id):
        return self.api["trello_get"](f"/boards/{board_id}/cards", {
            "fields": (
                "id,name,desc,idList,idBoard,shortUrl,due,closed,pos,"
                "dateLastActivity,badges"
            ),
            "filter": "open", "limit": 1000,
            "checklists": "all", "checklist_fields": "name",
        })

    def prop_key_from_todo(self, card):
        desc = card.get("desc") or ""
        match = re.search(r"\*\*REKVIZITA:\*\*\s*(.+)", desc, flags=re.I)
        source = match.group(1).strip() if match else re.split(
            r"\s+-\s+(?=\d{1,2}/)", card.get("name", ""), maxsplit=1
        )[0]
        return self.api["canonical_prop"](source)[0]

    def occurrences(self, cards):
        result = defaultdict(list)
        for card in cards:
            for checklist in card.get("checklists", []):
                for item in checklist.get("checkItems", []):
                    name = (item.get("name") or "").strip()
                    if self.api["CHECKLIST_TAG"].casefold() not in name.casefold():
                        continue
                    key, display = self.api["canonical_prop"](name)
                    if key:
                        result[key].append({
                            "display": display,
                            "item": name,
                            "card": card,
                            "checklist": checklist.get("name"),
                        })
        return result

    def microsoft_plan(self, wrong_card, primary_card, source_occurrences):
        if not self.api["microsoft_enabled"]():
            return {"matches": [], "blocker": "Microsoft To Do is not configured"}
        token = self.api["get_microsoft_access_token"]()
        tasks = self.api["graph_get_all"](
            f"/me/todo/lists/{self.api['TODO_LIST_ID']}/tasks", token
        )
        source_urls = {
            item["card"].get("shortUrl") for item in source_occurrences
        }
        matches = []
        for task in tasks:
            title = task.get("title", "").strip().casefold()
            body = (task.get("body") or {}).get("content", "")
            if (
                wrong_card.get("shortUrl") in body
                or primary_card.get("shortUrl") in body
                or title == wrong_card.get("name", "").strip().casefold()
                or title == primary_card.get("name", "").strip().casefold()
                or any(url and url in body for url in source_urls)
            ):
                matches.append({"task": task})
        blocker = None
        if len(matches) != 1:
            blocker = f"expected one Microsoft task match, found {len(matches)}"
        return {"matches": matches, "blocker": blocker, "token": token}

    def plan(self):
        boards = self.boards()
        runtime = self.runtime_map(boards)
        blockers = []
        for project, data in boards.items():
            if len(data["todo"]) != 1:
                blockers.append(f"{project}: expected exactly one open ToDo list")

        dok4_cards = self.board_cards(boards["dok4"]["board"]["id"])
        riverdale_cards = self.board_cards(
            boards["riverdale"]["board"]["id"]
        )
        occurrences = self.occurrences(dok4_cards)
        dok4_todo_id = boards["dok4"]["todo"][0]["id"] if len(
            boards["dok4"]["todo"]
        ) == 1 else None
        riverdale_todo_id = boards["riverdale"]["todo"][0]["id"] if len(
            boards["riverdale"]["todo"]
        ) == 1 else None
        dok4_todos = [card for card in dok4_cards if card.get("idList") == dok4_todo_id]
        riverdale_todos = [
            card for card in riverdale_cards
            if card.get("idList") == riverdale_todo_id
        ]
        dok4_urls = {
            item["card"].get("shortUrl")
            for values in occurrences.values() for item in values
        }
        candidates = []
        for wrong in riverdale_todos:
            marker = automatic_marker(wrong.get("desc") or "")
            if not marker or not any(url and url in marker for url in dok4_urls):
                continue
            key = self.prop_key_from_todo(wrong)
            source = [
                item for item in occurrences.get(key, [])
                if item["card"].get("shortUrl") in marker
            ]
            existing = [
                card for card in dok4_todos
                if self.prop_key_from_todo(card) == key
            ]
            candidates.append({
                "key": key, "wrong": wrong, "source": source,
                "existing": existing, "auto_only": exact_auto_only(wrong),
            })
        if len(candidates) != 1:
            blockers.append(
                f"expected one exact cross-board repair candidate, found {len(candidates)}"
            )
        elif not candidates[0]["source"]:
            blockers.append("candidate has no exact DOK4 [z] source occurrence")
        elif len(candidates[0]["existing"]) > 1:
            blockers.append("multiple existing DOK4 ToDo cards for candidate identity")
        elif candidates[0]["existing"] and not candidates[0]["auto_only"]:
            blockers.append("wrong Riverdale card contains manual data")

        microsoft = None
        if len(candidates) == 1 and candidates[0]["source"]:
            candidate = candidates[0]
            primary = (
                candidate["existing"][0]
                if candidate["existing"] else candidate["wrong"]
            )
            try:
                microsoft = self.microsoft_plan(
                    candidate["wrong"], primary, candidate["source"]
                )
                if microsoft.get("blocker"):
                    blockers.append(microsoft["blocker"])
            except Exception as exc:
                microsoft = {"matches": [], "blocker": str(exc)}
                blockers.append(f"Microsoft diagnostic failed: {exc}")

        return {
            "boards": boards, "runtime": runtime, "occurrences": occurrences,
            "dok4_todos": dok4_todos, "riverdale_todos": riverdale_todos,
            "candidates": candidates, "microsoft": microsoft,
            "blockers": blockers,
        }


def compact_card(card):
    return {
        "id": card.get("id"), "name": card.get("name"),
        "url": card.get("shortUrl"), "list_id": card.get("idList"),
        "due": card.get("due"), "last_activity": card.get("dateLastActivity"),
    }


def register_routes(flask_app, api):
    diagnostic = Diagnostic(api)

    @flask_app.route("/api/repair-dok4-board-routing", methods=["POST"])
    def repair_dok4_board_routing():
        if request.headers.get("X-Board-Guard-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "dry-run").strip().casefold()
        if mode not in {"dry-run", "apply", "audit"}:
            return jsonify({"error": "invalid mode"}), 400

        plan = diagnostic.plan()
        candidates = plan["candidates"]
        response = {
            "status": mode,
            "writes": 0,
            "runtime_source_target_lists": plan["runtime"],
            "cross_board_runtime_mappings": [
                item for item in plan["runtime"] if not item["same_board"]
            ],
            "boards": {
                project: {
                    "id": data["board"]["id"],
                    "name": data["board"].get("name"),
                    "ref": data["board"].get("shortLink"),
                    "todo": [
                        {"id": item["id"], "name": item.get("name")}
                        for item in data["todo"]
                    ],
                }
                for project, data in plan["boards"].items()
            },
            "dok4_tagged_identities": len(plan["occurrences"]),
            "dok4_tagged_occurrences": sum(
                len(items) for items in plan["occurrences"].values()
            ),
            "dok4_todo_cards": len(plan["dok4_todos"]),
            "riverdale_todo_cards": len(plan["riverdale_todos"]),
            "repair_candidates": [
                {
                    "key": item["key"],
                    "wrong_card": compact_card(item["wrong"]),
                    "source": [
                        {
                            "item": source["item"],
                            "checklist": source["checklist"],
                            "card": compact_card(source["card"]),
                        }
                        for source in item["source"]
                    ],
                    "existing_dok4": [compact_card(card) for card in item["existing"]],
                    "wrong_card_auto_only": item["auto_only"],
                    "action": "merge" if item["existing"] else "move",
                }
                for item in candidates
            ],
            "microsoft_task_matches": (
                len(plan["microsoft"]["matches"])
                if plan["microsoft"] else 0
            ),
            "blockers": plan["blockers"],
        }
        if mode in {"dry-run", "audit"}:
            response["safe_to_apply"] = not plan["blockers"]
            return jsonify(response), 200
        if plan["blockers"]:
            return jsonify(response), 409

        candidate = candidates[0]
        wrong = candidate["wrong"]
        source = candidate["source"]
        writes = []
        if candidate["existing"]:
            primary = candidate["existing"][0]
            marker = automatic_marker(primary.get("desc") or "") or ""
            for occurrence in source:
                marker = api["add_scene_to_prop_marker"](
                    marker,
                    occurrence["display"],
                    occurrence["card"],
                    occurrence["item"],
                    primary.get("due"),
                )
            desired = replace_marker_preserving_manual(
                primary.get("desc") or "", marker
            )
            payload = {"desc": desired}
            due_values = [
                value for value in [primary.get("due")] + [
                    item["card"].get("due") for item in source
                ] if value
            ]
            if due_values:
                payload["due"] = min(due_values)
            api["trello_put_body"](f"/cards/{primary['id']}", payload)
            writes.append("merged_dok4_card")
            api["trello_put_body"](
                f"/cards/{wrong['id']}", {"closed": "true"}
            )
            writes.append("archived_wrong_riverdale_card")
        else:
            primary = wrong
            dok4_todo_id = plan["boards"]["dok4"]["todo"][0]["id"]
            api["trello_put_body"](
                f"/cards/{wrong['id']}", {"idList": dok4_todo_id}
            )
            writes.append("moved_card_to_dok4")

        microsoft = plan["microsoft"]
        task = microsoft["matches"][0]["task"]
        desired_date = (primary.get("due") or "")[:10]
        desired_body = (
            "SYNC PROJECT: DOK4\n"
            f"SYNC DUE DATE: {desired_date or 'NONE'}\n\n"
            "Synchronizované automaticky z Trello karty rekvizity.\n\n"
            f"Trello: {primary['shortUrl']}\n\n{primary.get('desc', '')}"
        )[:24000]
        graph_payload = {
            "title": primary["name"],
            "body": {"content": desired_body, "contentType": "text"},
        }
        if primary.get("due"):
            graph_payload["dueDateTime"] = api["todo_due_payload"](
                primary["due"]
            )
        api["graph_patch"](
            f"/me/todo/lists/{api['TODO_LIST_ID']}/tasks/{task['id']}",
            microsoft["token"], graph_payload,
        )
        writes.append("updated_existing_microsoft_task")
        response["status"] = "applied"
        response["writes"] = len(writes)
        response["write_actions"] = writes
        response["primary_card"] = compact_card(primary)
        return jsonify(response), 200
