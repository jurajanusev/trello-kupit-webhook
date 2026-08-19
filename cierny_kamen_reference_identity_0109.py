from __future__ import annotations

from collections import Counter, defaultdict
import re

from flask import jsonify, request

from cierny_kamen_meeting_semantic_dryrun import (
    BOARD_REF, canonical_scene_id, card_text, folded, load_board, public_card,
    scene_cards,
)


KEY = "ck-reference-0109-identities-19aug-7c319e5a"
SCOUT_CANONICAL = "Výbava skautskej skupiny"
SCOUT_ALIASES = (
    "Výbava pre skautov", "Výbava skautov", "Skautská výbava",
    "Vybavenie skautskej skupiny",
)
BOAT_CANONICAL = "Drevená pramica Jakuba a Sáry"
BOAT_ALIASES = ("Čln Jakuba a Sáry", "Drevená pramica", "Jakubov a Sárin čln")
URL_RE = re.compile(r"https://trello\.com/c/[A-Za-z0-9]+", re.I)
HEADING_RE = re.compile(r"(?m)^(#{2,3})\s+(.+?)\s*$")
AUTO_BLOCK_RE = re.compile(r"<!--[^>]+:START\s*-->.*?<!--[^>]+:END\s*-->", re.S)


def identity_core(value):
    text = str(value or "").strip()
    text = re.sub(r"^\s*<n>\s*", "", text, flags=re.I)
    text = text.replace("**", "").replace("*", "")
    text = re.sub(r"\s*\|\s*KARTA:\s*https?://\S+.*$", "", text, flags=re.I)
    text = re.split(r"\s+[—–]\s+", text, maxsplit=1)[0]
    text = re.split(r"\s+\|\s+(?:TU:|←|→)", text, maxsplit=1, flags=re.I)[0]
    return text.strip()


def split_sections(desc):
    matches = list(HEADING_RE.finditer(desc or ""))
    rows = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(desc)
        rows.append({
            "level": len(match.group(1)), "title": match.group(2).strip(),
            "body": desc[match.end():end].strip(), "raw": desc[match.start():end].strip(),
        })
    return rows


def card_details(api, card):
    detail = api["trello_get"](f"/cards/{card['id']}", {
        "fields": "id,name,desc,shortUrl,idList,closed,pos,idLabels,dateLastActivity",
        "checklists": "all", "checklist_fields": "name,pos",
        "attachments": "true", "attachment_fields": "id,name,url,date",
    })
    actions = api["trello_get"](f"/cards/{card['id']}/actions", {
        "filter": "commentCard", "limit": 1000,
    })
    detail["comments"] = actions
    detail["list_name"] = card.get("list_name")
    return detail


def item_rows(card):
    result = []
    for checklist in card.get("checklists", []):
        if folded(checklist.get("name")) != "rekvizity":
            continue
        for item in sorted(checklist.get("checkItems", []), key=lambda row: row.get("pos", 0)):
            urls = URL_RE.findall(item.get("name") or "")
            result.append({
                "checklist_id": checklist.get("id"), "item_id": item.get("id"),
                "text": item.get("name") or "", "state": item.get("state"),
                "pos": item.get("pos"), "core": identity_core(item.get("name")),
                "urls": urls, "companion": (item.get("name") or "").lstrip().startswith(("→", "←", "↳")),
            })
    return result


def master_candidates(api, state, canonical, aliases):
    tokens = {folded(canonical), *(folded(alias) for alias in aliases)}
    matches = []
    for card in state["cards"]:
        name = folded(card.get("name"))
        text = folded(card_text(card))
        if name in tokens or any(token in name or token in text for token in tokens):
            if "rekviz" not in folded(card.get("list_name")) and not card.get("closed"):
                continue
            detail = card_details(api, card)
            manual_desc = AUTO_BLOCK_RE.sub("", detail.get("desc") or "").strip()
            matches.append({
                **public_card(detail, state), "date_last_activity": detail.get("dateLastActivity"),
                "attachment_count": len(detail.get("attachments", [])),
                "comment_count": len(detail.get("comments", [])),
                "manual_desc_chars": len(manual_desc),
                "manual_desc": manual_desc,
                "attachments": [{"id": row.get("id"), "name": row.get("name"), "url": row.get("url")}
                                for row in detail.get("attachments", [])],
                "comments": [{"id": row.get("id"), "text": (row.get("data") or {}).get("text")}
                             for row in detail.get("comments", [])],
            })
    matches.sort(key=lambda row: (
        -(row["manual_desc_chars"] + row["attachment_count"] * 1000 + row["comment_count"] * 1000),
        row.get("id") or "",
    ))
    return matches


def occurrence_rows(grouped, canonical, aliases):
    tokens = {folded(canonical), *(folded(alias) for alias in aliases)}
    rows = []
    for scene_id, cards in grouped.items():
        for card in cards:
            for item in item_rows(card):
                core = folded(item["core"])
                if core in tokens or any(token in core or core in token for token in tokens if core):
                    rows.append({"scene_id": scene_id, "card": card.get("name"),
                                 "url": card.get("shortUrl"), **item})
    return sorted(rows, key=lambda row: (row["scene_id"], row["pos"]))


def board_audit(grouped):
    duplicate_identity = []
    repeated_url = []
    missing_url = []
    companions = []
    for scene_id, cards in grouped.items():
        for card in cards:
            rows = item_rows(card)
            by_core = defaultdict(list); by_url = defaultdict(list)
            for row in rows:
                if row["core"]:
                    by_core[folded(row["core"])].append(row)
                for url in row["urls"]:
                    by_url[url.casefold()].append(row)
                if not row["urls"]:
                    missing_url.append({"scene_id": scene_id, "card": card["name"], "url": card["shortUrl"], **row})
                if row["companion"]:
                    companions.append({"scene_id": scene_id, "card": card["name"], "url": card["shortUrl"], **row})
            for core, matches in by_core.items():
                if len(matches) > 1:
                    duplicate_identity.append({"scene_id": scene_id, "card": card["name"], "url": card["shortUrl"], "identity": core, "items": matches})
            for url, matches in by_url.items():
                if len(matches) > 1:
                    repeated_url.append({"scene_id": scene_id, "card": card["name"], "url": card["shortUrl"], "registry_url": url, "items": matches})
    return {
        "duplicate_identity_count": len(duplicate_identity), "duplicate_identities": duplicate_identity,
        "repeated_url_count": len(repeated_url), "repeated_urls": repeated_url,
        "items_without_registry_url_count": len(missing_url), "items_without_registry_url": missing_url,
        "companion_item_count": len(companions), "companion_items": companions,
    }


def build_audit(api):
    state = load_board(api); grouped = scene_cards(api, state)
    # load_board intentionally optimizes for open production lists. Identity
    # resolution must also inspect archived cards before choosing a survivor.
    closed_cards = api["trello_get"](f"/boards/{state['board']['id']}/cards", {
        "fields": "id,name,desc,shortUrl,idList,closed,pos,idLabels,dateLastActivity",
        "filter": "closed", "limit": 1000,
        "checklists": "all", "checklist_fields": "name,pos",
    })
    known = {card["id"] for card in state["cards"]}
    for card in closed_cards:
        if card["id"] in known:
            continue
        board_list = state["list_by_id"].get(card.get("idList"), {})
        state["cards"].append({**card, "list_name": board_list.get("name", "ARCHIVED/UNKNOWN")})
        known.add(card["id"])
    card_matches = grouped.get("01/09", [])
    if len(card_matches) != 1:
        raise RuntimeError(f"01/09 must resolve to one production card, got {len(card_matches)}")
    scene = card_details(api, card_matches[0])
    sections = split_sections(scene.get("desc") or "")
    props = item_rows(scene)
    tape = [row for row in props if "pask" in folded(row["core"]) and "policajn" in folded(row["core"])]
    scout = master_candidates(api, state, SCOUT_CANONICAL, SCOUT_ALIASES)
    boat = master_candidates(api, state, BOAT_CANONICAL, BOAT_ALIASES)
    return {
        "status": "read-only-dry-run", "writes": 0,
        "board": state["board"], "scene_cards": sum(len(rows) for rows in grouped.values()),
        "scene_01_09": {
            "id": scene["id"], "name": scene["name"], "url": scene["shortUrl"],
            "description": scene.get("desc") or "", "sections": sections,
            "checklists": scene.get("checklists", []), "labels": scene.get("idLabels", []),
            "attachments": scene.get("attachments", []), "comments": scene.get("comments", []),
            "prop_items": props, "police_tape_items": tape,
        },
        "scout_gear": {"canonical": SCOUT_CANONICAL, "aliases": SCOUT_ALIASES,
                       "master_candidates": scout, "occurrences": occurrence_rows(grouped, SCOUT_CANONICAL, SCOUT_ALIASES)},
        "wooden_boat": {"canonical": BOAT_CANONICAL, "aliases": BOAT_ALIASES,
                        "master_candidates": boat, "occurrences": occurrence_rows(grouped, BOAT_CANONICAL, BOAT_ALIASES)},
        "whole_board_report_only": board_audit(grouped),
        "archived_cards_loaded": len(closed_cards),
    }


def register_routes(app, api):
    @app.route("/api/ck-reference-0109-identities", methods=["POST"])
    def ck_reference_0109_identities():
        if request.headers.get("X-CK-Reference-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "dry-run").casefold()
        if mode != "dry-run":
            return jsonify({"error": "read-only phase; apply is not enabled", "writes": 0}), 405
        try:
            return jsonify(build_audit(api)), 200
        except Exception as exc:
            app.logger.exception("CK 01/09 reference audit failed")
            return jsonify({"status": "failed", "writes": 0,
                            "error": f"{type(exc).__name__}: {exc}"}), 502
