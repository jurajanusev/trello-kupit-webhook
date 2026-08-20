from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import re

from flask import jsonify, request

from cierny_kamen_meeting_semantic_dryrun import (
    BOARD_REF, canonical_scene_id, card_text, folded, load_board, public_card,
    scene_cards,
)
from cierny_kamen_prop_identity_resolution import strip_technical_wrappers


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
IDENTITY_START = "<!-- CIERNY-KAMEN-PROP-IDENTITY:START -->"
IDENTITY_END = "<!-- CIERNY-KAMEN-PROP-IDENTITY:END -->"
CONFIRMED_DUPLICATE_URLS = {
    "https://trello.com/c/j848octw",
    "https://trello.com/c/zqlpmwnb",
}


def identity_core(value):
    return strip_technical_wrappers(value)


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


def _candidate_detail(api, card):
    try:
        return card_details(api, card), False
    except Exception:
        if (card.get("shortUrl") or "").casefold() not in CONFIRMED_DUPLICATE_URLS:
            raise
        return {
            **card, "attachments": [], "comments": [],
            "dateLastActivity": card.get("dateLastActivity"),
        }, True


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
            detail, detail_read_fallback = _candidate_detail(api, card)
            manual_desc = AUTO_BLOCK_RE.sub("", detail.get("desc") or "").strip()
            matches.append({
                **public_card(detail, state), "date_last_activity": detail.get("dateLastActivity"),
                "attachment_count": len(detail.get("attachments", [])),
                "comment_count": len(detail.get("comments", [])),
                "id_labels": list(detail.get("idLabels", [])),
                "manual_desc_chars": len(manual_desc),
                "manual_desc": manual_desc,
                "attachments": [{"id": row.get("id"), "name": row.get("name"), "url": row.get("url")}
                                for row in detail.get("attachments", [])],
                "comments": [{"id": row.get("id"), "text": (row.get("data") or {}).get("text")}
                             for row in detail.get("comments", [])],
                "detail_read_fallback": detail_read_fallback,
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
                    rows.append({"scene_id": scene_id, "card_id": card.get("id"), "card": card.get("name"),
                                 "url": card.get("shortUrl"), **item})
    return sorted(rows, key=lambda row: (row["scene_id"], row["pos"]))


def desired_0109_description(desc):
    sections = split_sections(desc)
    by_name = {folded(row["title"]): row for row in sections}
    common = {"rucne doplnenia", "akcia a dialogy"}
    legacy_navigation = {"kontinuita priestoru", "kontinuita postav"}.issubset(by_name)
    current_navigation = {"navigacia", "rovnaky priestor", "rovnake postavy"}.issubset(by_name)
    if not common.issubset(by_name) or not (legacy_navigation or current_navigation):
        return None, "required description sections are missing or ambiguous"
    metadata = re.search(
        r"<!--\s*CIERNY-KAMEN-SCHEDULE-METADATA:START\s*-->.*?"
        r"<!--\s*CIERNY-KAMEN-SCHEDULE-METADATA:END\s*-->", desc, flags=re.S,
    )
    if not metadata:
        return None, "metadata markers are missing"
    first = sections[0]
    if first["body"]:
        return None, "title section unexpectedly contains body text"
    space_key = "kontinuita priestoru" if legacy_navigation else "rovnaky priestor"
    characters_key = "kontinuita postav" if legacy_navigation else "rovnake postavy"
    space = by_name[space_key]["body"]
    character_lines = []
    seen = set()
    for line in by_name[characters_key]["body"].splitlines():
        match = re.match(r"\s*-\s*([^:]+):", line)
        key = folded(match.group(1)) if match else folded(line)
        if key in seen:
            continue
        seen.add(key); character_lines.append(line)
    action = by_name["akcia a dialogy"]["body"]
    action = action.replace(metadata.group(0), "").rstrip()
    manual = by_name["rucne doplnenia"]["body"]
    desired = (
        f"## {first['title']}\n\n"
        "## NAVIGÁCIA\n\n### Rovnaký priestor\n"
        f"{space}\n\n### Rovnaké postavy\n" + "\n".join(character_lines) + "\n\n"
        "## RUČNÉ DOPLNENIA\n" + (f"\n{manual}\n" if manual else "\n") + "\n"
        "## AKCIA A DIALÓGY\n\n" + action + "\n\n" + metadata.group(0)
    )
    return desired, None


def _pair_plan(rows, registry_url, desired_text):
    matches = [row for row in rows if registry_url.casefold() in {url.casefold() for url in row["urls"]}]
    original = [row for row in matches if not row["companion"]]
    companion = [row for row in matches if row["companion"]]
    conflict = None
    resolved = len(original) == 1 and not companion and original[0]["text"] == desired_text
    if not resolved and (len(original) != 1 or len(companion) != 1):
        conflict = "expected exactly one original plus one automatic companion"
    elif not resolved and original[0]["state"] != companion[0]["state"]:
        conflict = "original and companion have different check states"
    return {"registry_url": registry_url, "original": original, "companion": companion,
            "desired_text": desired_text, "resolved": resolved,
            "pending": not resolved and not conflict, "conflict": conflict}


def _identity_target_text(kind, scene_id, survivor_url, keep_z=False):
    if kind == "scout":
        body = (
            "<n> **Výbava skautskej skupiny** — *laná, mačety, nože, ďalekohľad a čutory | "
            "TU: používaná skautskou skupinou | ← prvý výskyt | "
            "→ ďalší potvrdený obraz neurčený*"
        )
    elif scene_id == "01/06LP":
        body = (
            "<n> **Drevená pramica Jakuba a Sáry** — *Jakub vesluje a Sára sedí v pramici | "
            "TU: pláva po rieke | ← prvý výskyt | → 01/07*"
        )
    else:
        body = (
            "<n> **Drevená pramica Jakuba a Sáry** — *prevrátená vo vode | "
            "TU: prevrátená vo vode | ← 01/06LP | → ďalší potvrdený obraz neurčený*"
        )
    if keep_z:
        body += " [z]"
    return f"{body} | KARTA: {survivor_url}"


def _identity_block(canonical, aliases, occurrences, source_urls):
    links = "\n".join(
        f"- [{row['scene_id']} – {row['card']}]({row['url']})"
        for row in sorted({row["scene_id"]: row for row in occurrences}.values(), key=lambda row: row["scene_id"])
    )
    sources = "\n".join(f"- {url}" for url in source_urls)
    timeline = "\n".join(
        f"- {row['scene_id']}: {identity_core(row['text'])}"
        for row in sorted(occurrences, key=lambda row: (row["scene_id"], row["pos"]))
    )
    return (
        f"{IDENTITY_START}\nKANONICKÝ NÁZOV: {canonical}\n"
        "ALIASY:\n" + "\n".join(f"- {alias}" for alias in aliases) + "\n\n"
        f"VÝSKYTY:\n{links}\n\nČASOVÁ OS:\n{timeline}\n\n"
        f"ZLÚČENÉ ZDROJOVÉ KARTY:\n{sources}\n{IDENTITY_END}"
    )


def build_reference_plan(audit):
    scene = audit["scene_01_09"]
    desired_desc, desc_conflict = desired_0109_description(scene["description"])
    rows = scene["prop_items"]
    pairs = [
        _pair_plan(rows, "https://trello.com/c/XnIkH9MX",
                   "**Policajné pásky** — *ohraničujú priestor pátrania* | KARTA: https://trello.com/c/XnIkH9MX"),
        _pair_plan(rows, "https://trello.com/c/O2GdZA1m",
                   "**Výbava Alice a Ivana ako miestnych novinárov** — *používajú ju pri sledovaní diania na brehu rieky* | KARTA: https://trello.com/c/O2GdZA1m"),
        _pair_plan(rows, "https://trello.com/c/hU7Ge64C",
                   "**Maják policajného auta pri rieke** — *bliká na policajnom aute v pozadí počas pátrania po Jakubovi* | KARTA: https://trello.com/c/hU7Ge64C"),
    ]
    identities = []
    for key, data in (("scout", audit["scout_gear"]), ("boat", audit["wooden_boat"])):
        candidates = data["master_candidates"]
        survivor = candidates[0] if candidates else None
        identities.append({
            "kind": key, "canonical": data["canonical"], "aliases": list(data["aliases"]),
            "survivor": survivor, "duplicates": candidates[1:] if survivor else candidates,
            "occurrences": data["occurrences"],
            "conflict": None if survivor and len(candidates) >= 2 else "expected at least two active master candidates",
        })
    blockers = ([desc_conflict] if desc_conflict else []) + [pair["conflict"] for pair in pairs if pair["conflict"]]
    blockers += [row["conflict"] for row in identities if row["conflict"]]
    return {
        "description": {
            "changed": desired_desc != scene["description"] if desired_desc else False,
            "before_sha256": hashlib.sha256(scene["description"].encode()).hexdigest(),
            "after_sha256": hashlib.sha256((desired_desc or scene["description"]).encode()).hexdigest(),
            "desired": desired_desc, "conflict": desc_conflict,
        },
        "scene_pairs": pairs, "identities": identities, "blockers": blockers,
        "safe_to_apply": not blockers,
    }


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
    archived_list_cards = 0
    for board_list in state["lists"]:
        if not board_list.get("closed"):
            continue
        rows = api["trello_get"](f"/lists/{board_list['id']}/cards", {
            "fields": "id,name,desc,shortUrl,idList,closed,pos,idLabels,dateLastActivity",
            "filter": "all", "limit": 1000,
            "checklists": "all", "checklist_fields": "name,pos",
        })
        archived_list_cards += len(rows)
        for card in rows:
            if card["id"] in known:
                continue
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
    scout_keyword_cards = [
        public_card(card, state) for card in state["cards"]
        if folded(card.get("list_name")) != "scenare"
        and any(token in folded(card_text(card)) for token in ("skaut", "matejovej skupiny", "kurz prezitia"))
    ]
    result = {
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
                       "master_candidates": scout, "keyword_cards": scout_keyword_cards,
                       "occurrences": occurrence_rows(grouped, SCOUT_CANONICAL, SCOUT_ALIASES)},
        "wooden_boat": {"canonical": BOAT_CANONICAL, "aliases": BOAT_ALIASES,
                        "master_candidates": boat, "occurrences": occurrence_rows(grouped, BOAT_CANONICAL, BOAT_ALIASES)},
        "whole_board_report_only": board_audit(grouped),
        "archived_cards_loaded": len(closed_cards),
        "cards_loaded_from_archived_lists": archived_list_cards,
    }
    result["reference_plan"] = build_reference_plan(result)
    return result


def _read_scene_card(api, card_id):
    return api["trello_get"](f"/cards/{card_id}", {
        "fields": "id,name,desc,shortUrl,idList,closed,pos,idLabels,dateLastActivity",
        "checklists": "all", "checklist_fields": "name,pos",
        "attachments": "true", "attachment_fields": "id,name,url,date",
    })


def apply_sample_0109(api):
    audit = build_audit(api); plan = audit["reference_plan"]
    if not plan["safe_to_apply"]:
        raise RuntimeError("sample blockers: " + json.dumps(plan["blockers"], ensure_ascii=False))
    scene = audit["scene_01_09"]
    live = _read_scene_card(api, scene["id"])
    if live.get("desc") != scene["description"]:
        raise RuntimeError("01/09 changed after dry-run")
    live_items = {row["item_id"]: row for row in item_rows(live)}
    for pair in plan["scene_pairs"]:
        if pair["resolved"]:
            continue
        for row in pair["original"] + pair["companion"]:
            current = live_items.get(row["item_id"])
            if not current or current["text"] != row["text"] or current["state"] != row["state"]:
                raise RuntimeError(f"01/09 item changed after dry-run: {row['item_id']}")
    writes = 0; changed = []
    if plan["description"]["changed"]:
        api["trello_put_body"](f"/cards/{scene['id']}", {"desc": plan["description"]["desired"]})
        writes += 1; changed.append("description_reordered")
    for pair in plan["scene_pairs"]:
        if pair["resolved"]:
            continue
        original = pair["original"][0]; companion = pair["companion"][0]
        if original["text"] != pair["desired_text"]:
            api["trello_put_body"](
                f"/cards/{scene['id']}/checkItem/{original['item_id']}",
                {"name": pair["desired_text"]},
            )
            writes += 1; changed.append(f"updated:{original['item_id']}")
        api["trello_delete"](
            f"/checklists/{companion['checklist_id']}/checkItems/{companion['item_id']}"
        )
        writes += 1; changed.append(f"archived_companion_item:{companion['item_id']}")
    after = _read_scene_card(api, scene["id"])
    after_rows = item_rows(after)
    return {
        "status": "sample-applied", "writes": writes, "changed": changed,
        "url": after.get("shortUrl"),
        "description_match": after.get("desc") == plan["description"]["desired"],
        "prop_item_count_before": len(scene["prop_items"]),
        "prop_item_count_after": len(after_rows),
        "target_pairs_after": [{"url": pair["registry_url"], "count": sum(
            pair["registry_url"].casefold() in {url.casefold() for url in row["urls"]}
            for row in after_rows
        )} for pair in plan["scene_pairs"]],
    }


def _ensure_attachment(api, card, url, name):
    existing = {row.get("url") for row in card.get("attachments", [])}
    if url in existing:
        return 0
    created = api["trello_post_body"](f"/cards/{card['id']}/attachments", {"url": url, "name": name})
    card.setdefault("attachments", []).append(created)
    return 1


def _duplicate_detail_for_apply(api, row):
    """Use the complete dry-run snapshot for duplicate masters.

    Trello can list a duplicate on the board while rejecting a second direct
    card-detail read (including during an interrupted archive). The dry-run
    already captured every field used by apply, so a second read is both
    redundant and less reliable.
    """
    return {
        "id": row["id"], "name": row["name"], "shortUrl": row["url"],
        "closed": bool(row.get("closed")), "idLabels": list(row.get("id_labels", [])),
        "attachments": row.get("attachments", []),
    }


def apply_confirmed_identities(api):
    audit = build_audit(api); plan = audit["reference_plan"]
    if not plan["safe_to_apply"]:
        raise RuntimeError("identity blockers: " + json.dumps(plan["blockers"], ensure_ascii=False))
    state = load_board(api); grouped = scene_cards(api, state)
    continuity_labels = [row for row in state["labels"] if folded(row.get("name")) == "nadvazna rekvizita"]
    if len(continuity_labels) != 1:
        raise RuntimeError("Nadväzná rekvizita label is missing or ambiguous")
    continuity_id = continuity_labels[0]["id"]
    writes = 0; results = []
    for identity in plan["identities"]:
        survivor_public = identity["survivor"]
        survivor = card_details(api, {"id": survivor_public["id"], "list_name": survivor_public["list"]})
        duplicates = [_duplicate_detail_for_apply(api, row) for row in identity["duplicates"]]
        source_urls = [row.get("shortUrl") for row in [survivor, *duplicates] if row.get("shortUrl")]
        occurrences = identity["occurrences"]
        grouped_occurrences = defaultdict(list)
        for row in occurrences:
            grouped_occurrences[row["scene_id"]].append(row)
        identity_changes = []
        for scene_id, rows in sorted(grouped_occurrences.items()):
            if len({row["state"] for row in rows}) != 1:
                raise RuntimeError(f"{identity['canonical']} has mixed check states in {scene_id}")
            card_matches = grouped.get(scene_id, [])
            if len(card_matches) != 1:
                raise RuntimeError(f"{scene_id} production card is missing or duplicated")
            live = _read_scene_card(api, card_matches[0]["id"])
            live_by_id = {row["item_id"]: row for row in item_rows(live)}
            for row in rows:
                if row["item_id"] not in live_by_id or live_by_id[row["item_id"]]["text"] != row["text"]:
                    raise RuntimeError(f"{scene_id} item changed after dry-run: {row['item_id']}")
            survivor_item = min(rows, key=lambda row: row["pos"])
            keep_z = any("[z]" in row["text"].casefold() for row in rows)
            desired = _identity_target_text(identity["kind"], scene_id, survivor.get("shortUrl"), keep_z)
            if survivor_item["text"] != desired:
                api["trello_put_body"](
                    f"/cards/{live['id']}/checkItem/{survivor_item['item_id']}", {"name": desired}
                )
                writes += 1; identity_changes.append(f"updated {scene_id}:{survivor_item['item_id']}")
            for row in rows:
                if row["item_id"] == survivor_item["item_id"]:
                    continue
                api["trello_delete"](f"/checklists/{row['checklist_id']}/checkItems/{row['item_id']}")
                writes += 1; identity_changes.append(f"archived duplicate {scene_id}:{row['item_id']}")
            if continuity_id not in live.get("idLabels", []):
                desired_labels = list(live.get("idLabels", [])) + [continuity_id]
                api["trello_put_body"](f"/cards/{live['id']}", {"idLabels": ",".join(desired_labels)})
                writes += 1; identity_changes.append(f"labelled {scene_id}")
        labels = set(survivor.get("idLabels", [])) | {continuity_id}
        for duplicate in duplicates:
            labels.update(duplicate.get("idLabels", []))
        manual = AUTO_BLOCK_RE.sub("", survivor.get("desc") or "").strip()
        block = _identity_block(identity["canonical"], identity["aliases"], occurrences, source_urls)
        desired_desc = block + (("\n\n" + manual) if manual else "")
        body = {}
        if survivor.get("name") != identity["canonical"]:
            body["name"] = identity["canonical"]
        if survivor.get("desc") != desired_desc:
            body["desc"] = desired_desc
        if sorted(survivor.get("idLabels", [])) != sorted(labels):
            body["idLabels"] = ",".join(sorted(labels))
        if body:
            api["trello_put_body"](f"/cards/{survivor['id']}", body)
            writes += 1; identity_changes.append("updated survivor")
        for row in occurrences:
            writes += _ensure_attachment(api, survivor, row["url"], f"{row['scene_id']} – {row['card']}")
        for duplicate in duplicates:
            writes += _ensure_attachment(api, survivor, duplicate["shortUrl"], f"Zlúčený zdroj: {duplicate['name']}")
            if not duplicate.get("closed"):
                api["trello_put_body"](f"/cards/{duplicate['id']}", {"closed": True})
                writes += 1; identity_changes.append(f"archived master {duplicate['shortUrl']}")
        results.append({"canonical": identity["canonical"], "survivor_url": survivor["shortUrl"],
                        "changes": identity_changes, "source_urls": source_urls})
    return {"status": "identities-applied", "writes": writes, "identities": results}


def register_routes(app, api):
    @app.route("/api/ck-reference-0109-identities", methods=["POST"])
    def ck_reference_0109_identities():
        if request.headers.get("X-CK-Reference-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "dry-run").casefold()
        try:
            if mode in {"dry-run", "audit"}:
                return jsonify(build_audit(api)), 200
            if mode == "sample-apply":
                return jsonify(apply_sample_0109(api)), 200
            if mode == "identities-apply":
                return jsonify(apply_confirmed_identities(api)), 200
            return jsonify({"error": "mode must be dry-run, audit, sample-apply, or identities-apply"}), 400
        except Exception as exc:
            app.logger.exception("CK 01/09 reference audit failed")
            return jsonify({"status": "failed", "writes": 0,
                            "error": f"{type(exc).__name__}: {exc}"}), 502
