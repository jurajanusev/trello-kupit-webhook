from __future__ import annotations

import copy
import hashlib
import re
import unicodedata
from collections import defaultdict

from flask import jsonify, request

from cierny_kamen_reference_all import board_support_data, protected_card_value


KEY = "ck-global-reference-20aug-8e57c104"
META_START = "<!-- CIERNY-KAMEN-SCHEDULE-METADATA:START -->"
META_END = "<!-- CIERNY-KAMEN-SCHEDULE-METADATA:END -->"
HEADING = re.compile(r"(?m)^(#{2,3})\s+(.+?)\s*$")
URL = re.compile(r"https://trello\.com/c/[A-Za-z0-9]+", re.I)
PRESERVED_START = "<!-- CIERNY-KAMEN-PRESERVED-LEGACY:START -->"
PRESERVED_END = "<!-- CIERNY-KAMEN-PRESERVED-LEGACY:END -->"


def folded(value):
    return " ".join("".join(ch for ch in unicodedata.normalize("NFKD", value or "")
                            if not unicodedata.combining(ch)).casefold().split())


def sections(desc):
    rows, matches = [], list(HEADING.finditer(desc or ""))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(desc)
        rows.append({"title": match.group(2).strip(), "body": desc[match.end():end].strip(),
                     "start": match.start(), "end": end})
    return rows


def _manual_with_preserved(manual_body, preserved):
    manual_body = re.sub(rf"\n*{re.escape(PRESERVED_START)}.*?{re.escape(PRESERVED_END)}", "", manual_body, flags=re.S).strip()
    if not preserved:
        return manual_body
    block = [PRESERVED_START, "### Zachované údaje z odstránených automatických sekcií"]
    for origin, lines in preserved:
        block.extend([f"- Pôvod: {origin}", *[f"  - {line}" for line in lines]])
    block.append(PRESERVED_END)
    return "\n\n".join(filter(None, [manual_body, "\n".join(block)]))


def desired_description(desc, prop_items):
    if (desc or "").count(META_START) != 1 or (desc or "").count(META_END) != 1:
        return None, "metadata markers are not unique", []
    meta_start = desc.index(META_START)
    meta_end = desc.index(META_END) + len(META_END)
    metadata = desc[meta_start:meta_end]
    body = (desc[:meta_start] + desc[meta_end:]).strip()
    rows = sections(body)
    by = defaultdict(list)
    for row in rows:
        by[folded(row["title"])].append(row)
    required = ("rucne doplnenia", "akcia a dialogy")
    if any(len(by[key]) != 1 for key in required) or not rows:
        return None, "manual/action sections are missing or ambiguous", []
    title = rows[0]["title"]
    if rows[0]["body"]:
        return None, "title heading contains body", []
    if len(by["navigacia"]) == 1 and len(by["rovnaky priestor"]) == 1 and len(by["rovnake postavy"]) == 1:
        desired = desc.strip()
        return desired, None, []
    if len(by["kontinuita priestoru"]) != 1 or len(by["kontinuita postav"]) != 1:
        return None, "legacy navigation sections are missing or ambiguous", []
    prop_text = "\n".join(item.get("name") or "" for item in prop_items)
    prop_fold = folded(prop_text)
    prop_urls = {url.casefold() for url in URL.findall(prop_text)}
    preserved = []
    props = by.get("rekvizity v kontexte", [])
    if len(props) == 1:
        unmatched = []
        for raw in props[0]["body"].splitlines():
            line = raw.strip().lstrip("-").strip()
            if not line or "bez samostatnej rekvizity" in folded(line):
                continue
            name = re.sub(r"[*_]", "", line).split(" — ", 1)[0].strip()
            urls = {url.casefold() for url in URL.findall(line)}
            if not (folded(name) and folded(name) in prop_fold) and not (urls and urls <= prop_urls):
                unmatched.append(line)
        if unmatched:
            preserved.append(("REKVIZITY V KONTEXTE", unmatched))
    for key, label in (("nadvaznost", "NADVAZNOSŤ"), ("kontinuita", "KONTINUITA")):
        for row in by.get(key, []):
            lines = [line.strip().lstrip("-").strip() for line in row["body"].splitlines()]
            lines = [line for line in lines if line and "bez potvrdenej nadvaznosti" not in folded(line)]
            if lines:
                preserved.append((label, lines))
    links = by.get("odkazy", [])
    if len(links) == 1:
        unmatched = []
        for raw in links[0]["body"].splitlines():
            line = raw.strip().lstrip("-").strip()
            if not line or line.startswith("Bez "):
                continue
            urls = {url.casefold() for url in URL.findall(line)}
            if not urls or not urls <= prop_urls:
                unmatched.append(line)
        if unmatched:
            preserved.append(("ODKAZY", unmatched))
    manual_body = _manual_with_preserved(by["rucne doplnenia"][0]["body"], preserved)
    parts = [
        f"## {title}",
        "## NAVIGÁCIA\n\n### Rovnaký priestor\n" + by["kontinuita priestoru"][0]["body"],
        "### Rovnaké postavy\n" + by["kontinuita postav"][0]["body"],
        "## RUČNÉ DOPLNENIA" + (("\n\n" + manual_body) if manual_body else ""),
        "## AKCIA A DIALÓGY\n\n" + by["akcia a dialogy"][0]["body"],
        metadata,
    ]
    return "\n\n".join(parts), None, preserved


def _scene_groups(api, state):
    groups = defaultdict(list)
    for card in state["cards"]:
        list_name = state["lists_by_id"].get(card.get("idList"), {}).get("name", "")
        if "original screener" in folded(list_name):
            continue
        info = api["cierny_kamen_scene_name_info"](card.get("name", ""))
        if not info or info.get("test"):
            continue
        groups[info["scene_id"]].append(card)
    return dict(groups)


def _prop_rows(card, support):
    rows = []
    for checklist in support["checklists"].get(card["id"], []):
        if folded(checklist.get("name")) != "rekvizity":
            continue
        for item in sorted(checklist.get("checkItems", []), key=lambda row: row.get("pos", 0)):
            text = item.get("name") or ""
            rows.append({"card_id": card["id"], "checklist_id": checklist["id"], "item_id": item["id"],
                         "name": text, "state": item.get("state"), "pos": item.get("pos"),
                         "urls": URL.findall(text), "companion": text.lstrip().startswith(("↳", "→", "←"))})
    return rows


def _companion_target(original, companion, master_name, url):
    text = companion["name"].lstrip("↳→← ")
    text = re.sub(r"\s*\|\s*KARTA:\s*https://trello\.com/c/[A-Za-z0-9]+\s*$", "", text, flags=re.I)
    context = text.split(" — ", 1)[1].strip() if " — " in text else ""
    prefix = "<n> " if any(row["name"].lstrip().startswith("<n>") for row in (original, companion)) else ""
    suffix = " [z]" if any("[z]" in row["name"].casefold() for row in (original, companion)) else ""
    return f"{prefix}**{master_name}**" + (f" — *{context}*" if context else "") + f" | KARTA: {url}{suffix}"


def build_audit(api):
    payload = api["cierny_kamen_import_payload"]()
    state = api["cierny_kamen_import_state"](payload)
    groups = _scene_groups(api, state)
    collisions = {key: len(value) for key, value in groups.items() if len(value) != 1 and key in {s['scene_id'] for s in payload['scenes']}}
    cards = {key: value[0] for key, value in groups.items() if len(value) == 1}
    missing = [scene["scene_id"] for scene in payload["scenes"] if scene["scene_id"] not in cards]
    support = board_support_data(api, state["board"]["id"])
    description_ops, description_conflicts = [], []
    all_rows = []
    for scene in payload["scenes"]:
        card = cards.get(scene["scene_id"])
        if not card:
            continue
        props = _prop_rows(card, support)
        all_rows.extend({"scene_id": scene["scene_id"], "card_url": card.get("shortUrl"), **row} for row in props)
        desired, conflict, preserved = desired_description(card.get("desc") or "", props)
        if conflict:
            description_conflicts.append({"scene_id": scene["scene_id"], "url": card.get("shortUrl"), "reason": conflict})
        elif desired != (card.get("desc") or "").strip():
            description_ops.append({"scene_id": scene["scene_id"], "card_id": card["id"], "url": card.get("shortUrl"),
                                    "before": card.get("desc") or "", "after": desired,
                                    "preserved_origins": [origin for origin, _ in preserved]})
    cards_by_url = {(card.get("shortUrl") or "").casefold(): card for card in state["cards"] if card.get("shortUrl")}
    by_scene_url = defaultdict(list)
    missing_url = []
    for row in all_rows:
        if not row["urls"]:
            missing_url.append(row)
        for url in {url.casefold() for url in row["urls"]}:
            by_scene_url[(row["scene_id"], url)].append(row)
    prop_ops, prop_conflicts = [], []
    for (scene_id, url), rows in by_scene_url.items():
        if len(rows) < 2:
            continue
        companions = [row for row in rows if row["companion"]]
        originals = [row for row in rows if not row["companion"]]
        master = cards_by_url.get(url)
        if len(rows) == 2 and len(companions) == 1 and len(originals) == 1 and len({row['state'] for row in rows}) == 1 and master:
            prop_ops.append({"scene_id": scene_id, "url": url, "original": originals[0], "companion": companions[0],
                             "master_name": master.get("name"),
                             "after": _companion_target(originals[0], companions[0], master.get("name"), originals[0]["urls"][0])})
        else:
            prop_conflicts.append({"scene_id": scene_id, "url": url, "items": len(rows), "states": sorted({str(row['state']) for row in rows}),
                                   "reason": "not one compatible original plus automatic companion"})
    return {"status": "read-only-dry-run", "writes": 0, "board": state["board"], "source_scenes": len(payload["scenes"]),
            "unique_scene_cards": len(cards), "missing_scene_ids": missing, "collisions": collisions,
            "description_pending": len(description_ops), "description_conflicts": description_conflicts,
            "prop_items": len(all_rows), "prop_companion_merges": len(prop_ops), "prop_conflicts": prop_conflicts,
            "prop_items_without_url": len(missing_url), "description_ops": description_ops, "prop_ops": prop_ops,
            "_payload": payload, "_state": state, "_support": support, "_cards": cards}


def public(audit, include_ops=False):
    hidden = {"_payload", "_state", "_support", "_cards"}
    if not include_ops:
        hidden |= {"description_ops", "prop_ops"}
    return {key: value for key, value in audit.items() if key not in hidden}


def apply_descriptions(api, start, limit):
    audit = build_audit(api)
    selected = audit["description_ops"][start:start + limit]
    writes, errors = 0, []
    for op in selected:
        live = api["trello_get"](f"/cards/{op['card_id']}", {"fields": "id,desc"})
        if live.get("desc") != op["before"]:
            errors.append({"scene_id": op["scene_id"], "error": "description changed after dry-run"}); continue
        api["trello_put_body"](f"/cards/{op['card_id']}", {"desc": op["after"]}); writes += 1
        after = api["trello_get"](f"/cards/{op['card_id']}", {"fields": "id,desc"})
        if after.get("desc") != op["after"]:
            errors.append({"scene_id": op["scene_id"], "error": "description read-back mismatch"}); break
    return {"status": "descriptions-applied", "writes": writes, "selected": len(selected), "errors": errors,
            "scene_ids": [op["scene_id"] for op in selected], "pending_before": audit["description_pending"]}


def apply_props(api, start, limit):
    audit = build_audit(api)
    selected = audit["prop_ops"][start:start + limit]
    writes, errors = 0, []
    for op in selected:
        card = audit["_cards"][op["scene_id"]]
        live_support = board_support_data(api, audit["_state"]["board"]["id"])
        live_rows = {row["item_id"]: row for row in _prop_rows(card, live_support)}
        if any(row["item_id"] not in live_rows or live_rows[row["item_id"]]["name"] != row["name"] for row in (op["original"], op["companion"])):
            errors.append({"scene_id": op["scene_id"], "error": "prop items changed after dry-run"}); continue
        api["trello_put_body"](f"/cards/{card['id']}/checkItem/{op['original']['item_id']}", {"name": op["after"]}); writes += 1
        api["trello_delete"](f"/checklists/{op['companion']['checklist_id']}/checkItems/{op['companion']['item_id']}"); writes += 1
    return {"status": "props-applied", "writes": writes, "selected": len(selected), "errors": errors,
            "scene_ids": [op["scene_id"] for op in selected], "pending_before": audit["prop_companion_merges"]}


def register_routes(app, api):
    @app.route("/api/ck-global-reference", methods=["POST"])
    def ck_global_reference():
        if request.headers.get("X-CK-Global-Reference-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "dry-run").casefold()
        try:
            start, limit = int(request.args.get("start", "0")), int(request.args.get("limit", "5"))
            if start < 0 or limit < 1 or limit > 10:
                return jsonify({"error": "invalid batch"}), 400
            if mode in {"dry-run", "audit", "final-audit"}:
                audit = build_audit(api)
                return jsonify(public(audit, request.args.get("details") == "1")), 200
            if mode == "descriptions-apply":
                return jsonify(apply_descriptions(api, start, limit)), 200
            if mode == "props-apply":
                return jsonify(apply_props(api, start, limit)), 200
            return jsonify({"error": "invalid mode"}), 400
        except Exception as exc:
            app.logger.exception("global reference migration failed")
            return jsonify({"status": "failed", "writes": 0, "error": f"{type(exc).__name__}: {exc}"}), 502
