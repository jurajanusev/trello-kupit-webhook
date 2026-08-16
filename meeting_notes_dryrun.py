from __future__ import annotations

from collections import Counter, defaultdict
import re
import unicodedata
from urllib.parse import urlencode

from flask import jsonify, request


KEY = "meeting-notes-audit-16aug-7c4e91b2"
PROJECTS = {
    "dunaj": {"board_ref": "qCPeWA3e", "name": "Dunaj"},
    "dok4": {"board_ref": "lzNy4AtY", "name": "DOK 4"},
    "riverdale": {
        "board_ref": "CzuD55PR", "name": "Riverdale / Čierny Kameň",
    },
}

URL_RE = re.compile(r"https://trello\.com/c/[A-Za-z0-9]+", re.I)
MARKDOWN_RE = re.compile(r"[*_`]+")
TECH_TAG_RE = re.compile(r"(?:<n>|\[(?:z|h|s)\])", re.I)


def folded(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", value).strip().casefold()


def normalized_text(value):
    value = URL_RE.sub(" ", str(value or ""))
    value = TECH_TAG_RE.sub(" ", value)
    value = MARKDOWN_RE.sub("", value)
    value = re.sub(r"\|\s*KARTA\s*:\s*$", "", value, flags=re.I)
    value = re.sub(r"[^0-9A-Za-zÀ-ž/<>?]+", " ", value)
    return folded(value)


def semantic_core(value):
    value = re.split(r"\|\s*KARTA\s*:", str(value or ""), maxsplit=1, flags=re.I)[0]
    return normalized_text(value)


def normalized_lines(value):
    return {
        normalized_text(line) for line in str(value or "").splitlines()
        if normalized_text(line)
    }


def list_kind(name):
    name_folded = folded(name)
    if any(token in name_folded for token in (
        "natocene", "archiv", "completed", "done", "hotovo",
    )):
        return "shot"
    if name_folded == "todo":
        return "todo"
    support_tokens = (
        "register", "rekviz", "nadvazne set", "nadvazny set",
        "priestor", "mobily", "auta", "dokument", "screens",
    )
    if any(token in name_folded for token in support_tokens):
        return "registry"
    if "test" in name_folded or "sablon" in name_folded or "template" in name_folded:
        return "other"
    return "active"


def placeholder_reason(checklist_name, text):
    value = folded(text)
    exact = {
        "doplnit sem zmeny schvalene na porade",
        "doplni sa na porade",
        "bez poloziek",
        "placeholder",
        "x", "xx", "test", "-", ".", "...",
    }
    if value in exact or value.startswith("doplnit sem zmeny schvalene na porade"):
        return "template/placeholder item"
    if not value:
        return "empty item"
    return None


def cue_matches(value, patterns):
    return [label for label, pattern in patterns if re.search(pattern, value)]


CANCEL_CUES = (
    ("zrušiť/zrušené", r"\bzrus(?:it|ene|eny|ena)\b"),
    ("netreba", r"\bnetreba\b"),
    ("nepoužiť", r"\bnepouzit\b"),
    ("odstrániť/vyradiť", r"\b(?:odstranit|vyradit)\b"),
    ("bez predmetu", r"\bbez\s+(?:rekvizity|predmetu|setu)\b"),
)
CHANGE_CUES = (
    ("zmeniť/zmena", r"\bzmen(?:it|a|ene|eny|ena)\b"),
    ("vymeniť/nahradiť", r"\b(?:vymenit|nahradit)\b"),
    ("namiesto", r"\bnamiesto\b"),
    ("upraviť/presunúť", r"\b(?:upravit|presunut)\b"),
    ("po novom", r"\bpo\s+novom\b"),
)
ADD_CUES = (
    ("doplniť/pridať", r"\b(?:doplnit|pridat)\b"),
    ("zabezpečiť/pripraviť", r"\b(?:zabezpecit|pripravit)\b"),
    ("zohnať/kúpiť/objednať", r"\b(?:zohnat|kupit|objednat)\b"),
    ("vyrobiť/požičať", r"\b(?:vyrobit|pozicat)\b"),
    ("tag [z]", r"\[z\]"),
)
QUESTION_CUES = (
    ("question mark", r"\?"),
    ("overiť/potvrdiť", r"\b(?:overit|potvrdit)\b"),
    ("zistiť/rozhodnúť", r"\b(?:zistit|rozhodnut)\b"),
    ("otázka/nejasné", r"\b(?:otazka|nejasne|neurcene)\b"),
)
CLARIFY_CUES = (
    ("potvrdené/schválené", r"\b(?:potvrdene|schvalene)\b"),
    ("ostáva/bude", r"\b(?:ostava|zostava|bude)\b"),
    ("farba/rozmer/počet/stav", r"\b(?:farba|rozmer|pocet|stav)\b"),
    ("explicit visual state", r"\b(?:prazdn[ay]|rozbit[ay]|poskoden[ay]|otvoren[ay]|zatvoren[ay]|cist[ay]|spinav[ay])\b"),
)


def classify_item(checklist_name, text):
    placeholder = placeholder_reason(checklist_name, text)
    if placeholder:
        return {
            "classification": "ignored_placeholder", "confidence": "high",
            "reason": placeholder, "cues": [],
        }
    raw_folded = folded(text)
    checklist_folded = folded(checklist_name)
    if (
        raw_folded.startswith("bez ")
        and not re.match(r"^bez\s+(?:zmeny|zmien|problemu|otazok)\b", raw_folded)
        and (
            checklist_folded in {"rekvizity", "set"}
            or "porad" in checklist_folded
        )
    ):
        return {
            "classification": "cancelled", "confidence": "contextual",
            "reason": f"'Bez …' in {checklist_name} removes an expected element",
            "cues": ["contextual bez …"],
        }
    groups = {
        "cancelled": cue_matches(raw_folded, CANCEL_CUES),
        "changed": cue_matches(raw_folded, CHANGE_CUES),
        "added": cue_matches(raw_folded, ADD_CUES),
        "ambiguous": cue_matches(raw_folded, QUESTION_CUES),
        "clarified": cue_matches(raw_folded, CLARIFY_CUES),
    }
    matched = [name for name, cues in groups.items() if cues]
    if "ambiguous" in matched:
        return {
            "classification": "ambiguous", "confidence": "high",
            "reason": "requires a decision or missing confirmation",
            "cues": groups["ambiguous"],
        }
    decisive = [name for name in ("cancelled", "changed", "added") if groups[name]]
    if len(decisive) > 1:
        return {
            "classification": "ambiguous", "confidence": "medium",
            "reason": "contains cues for multiple operations",
            "cues": [cue for name in decisive for cue in groups[name]],
        }
    if decisive:
        name = decisive[0]
        return {
            "classification": name, "confidence": "high",
            "reason": f"explicit {name} wording",
            "cues": groups[name],
        }
    if groups["clarified"]:
        return {
            "classification": "clarified", "confidence": "medium",
            "reason": "declarative clarification wording",
            "cues": groups["clarified"],
        }
    if checklist_folded in {"rekvizity", "set"}:
        return {
            "classification": "added", "confidence": "contextual",
            "reason": f"natural item in {checklist_name}; identity/action still needs review",
            "cues": ["checklist context"],
        }
    if "info z porady" in checklist_folded or "info z natacania" in checklist_folded:
        return {
            "classification": "clarified", "confidence": "contextual",
            "reason": f"declarative item in {checklist_name}",
            "cues": ["checklist context"],
        }
    return {
        "classification": "ambiguous", "confidence": "low",
        "reason": "no unambiguous operation cue and no durable prior-sync marker",
        "cues": [],
    }


def support_projection(card, list_name, kind):
    text = "\n".join((card.get("name") or "", card.get("desc") or ""))
    return {
        "id": card["id"], "name": card.get("name"),
        "url": card.get("shortUrl"), "list": list_name, "kind": kind,
        "folded_text": normalized_text(text), "lines": normalized_lines(text),
    }


def text_matches(core, full, projection):
    if not core:
        return False
    if core in projection["lines"] or full in projection["lines"]:
        return True
    return len(core) >= 18 and core in projection["folded_text"]


def processed_evidence(item, card, support_cards_by_kind, support_by_url):
    text = item.get("name") or ""
    full = normalized_text(text)
    core = semantic_core(text)
    evidence = []
    desc_projection = {
        "folded_text": normalized_text(card.get("desc") or ""),
        "lines": normalized_lines(card.get("desc") or ""),
    }
    if text_matches(core, full, desc_projection):
        evidence.append({"kind": "scene_description", "card": card.get("shortUrl")})
    if item.get("id") and item["id"] in (card.get("desc") or ""):
        evidence.append({"kind": "scene_item_id_marker", "item_id": item["id"]})

    urls = URL_RE.findall(text)
    for url in urls:
        target = support_by_url.get(url.rstrip("/"))
        if target and (
            text_matches(core, full, target)
            or re.search(r"\|\s*KARTA\s*:", text, flags=re.I)
        ):
            evidence.append({
                "kind": "linked_master", "url": target["url"],
                "name": target["name"], "list": target["list"],
            })

    for kind in ("todo", "registry"):
        for target in support_cards_by_kind.get(kind, []):
            if item.get("id") and item["id"] in target["folded_text"]:
                evidence.append({
                    "kind": f"{kind}_item_id_marker", "url": target["url"],
                    "name": target["name"], "list": target["list"],
                })
                break
            if text_matches(core, full, target):
                evidence.append({
                    "kind": f"{kind}_text_match", "url": target["url"],
                    "name": target["name"], "list": target["list"],
                })
                break
    unique = []
    seen = set()
    for row in evidence:
        key = (row.get("kind"), row.get("url"), row.get("item_id"))
        if key not in seen:
            seen.add(key)
            unique.append(row)
    return unique


def load_list_cards(trello_get, list_id, include_checklists):
    params = {
        "fields": "id,name,desc,due,dueComplete,shortUrl,closed,idList,pos",
        "filter": "open", "limit": 1000,
    }
    if include_checklists:
        params.update({"checklists": "all", "checklist_fields": "all"})
    return trello_get(f"/lists/{list_id}/cards", params)


def load_list_cards_batched(trello_get, list_specs):
    """Load up to ten Trello lists per read-only batch request."""
    result = {}
    for offset in range(0, len(list_specs), 10):
        chunk = list_specs[offset:offset + 10]
        urls = []
        for spec in chunk:
            params = {
                "fields": "id,name,desc,due,dueComplete,shortUrl,closed,idList,pos",
                "filter": "open", "limit": 1000,
            }
            if spec["include_checklists"]:
                params.update({"checklists": "all", "checklist_fields": "all"})
            urls.append(f"/lists/{spec['id']}/cards?{urlencode(params)}")
        responses = trello_get("/batch", {"urls": ",".join(urls)})
        if len(responses) != len(chunk):
            raise RuntimeError("Trello batch response length mismatch")
        for spec, response in zip(chunk, responses):
            body = response.get("200")
            if body is None:
                status = next(iter(response), "unknown")
                raise RuntimeError(
                    f"Trello batch list read failed for {spec['name']}: {status}"
                )
            result[spec["id"]] = body
    return result


def scene_id_for(api, name):
    parser = api.get("scene_id_from_card_name")
    return parser(name) if parser else None


def audit_project(api, config, include_processed=False):
    trello_get = api["trello_get"]
    board = trello_get(f"/boards/{config['board_ref']}", {
        "fields": "id,name,url,shortLink,closed",
    })
    lists = trello_get(f"/boards/{board['id']}/lists", {
        "fields": "id,name,pos,closed", "filter": "all",
    })
    open_lists = [item for item in lists if not item.get("closed")]
    kinds = {item["id"]: list_kind(item.get("name")) for item in open_lists}
    list_specs = [{
        "id": item["id"], "name": item["name"],
        "include_checklists": kinds[item["id"]] == "active",
    } for item in open_lists if kinds[item["id"]] in {"active", "todo", "registry"}]
    cards_by_list = load_list_cards_batched(trello_get, list_specs)

    support_cards_by_kind = defaultdict(list)
    support_by_url = {}
    support_list_names = defaultdict(list)
    for board_list in open_lists:
        kind = kinds[board_list["id"]]
        if kind not in {"todo", "registry"}:
            continue
        support_list_names[kind].append(board_list["name"])
        for card in cards_by_list.get(board_list["id"], []):
            projection = support_projection(card, board_list["name"], kind)
            support_cards_by_kind[kind].append(projection)
            if projection.get("url"):
                support_by_url[projection["url"].rstrip("/")] = projection

    scene_cards = []
    skipped_non_scene_cards = 0
    active_list_names = []
    for board_list in open_lists:
        if kinds[board_list["id"]] != "active":
            continue
        active_list_names.append(board_list["name"])
        for card in cards_by_list.get(board_list["id"], []):
            scene_id = scene_id_for(api, card.get("name"))
            if not scene_id:
                skipped_non_scene_cards += 1
                continue
            scene_cards.append({
                **card, "scene_id": scene_id, "list_name": board_list["name"],
            })

    findings_by_card = []
    processed_sample = []
    totals = Counter()
    classifications = Counter()
    checklist_names = Counter()
    for card in scene_cards:
        checklist_results = []
        for checklist in sorted(card.get("checklists", []), key=lambda row: row.get("pos", 0)):
            checklist_names[checklist.get("name") or ""] += 1
            item_results = []
            for item in sorted(checklist.get("checkItems", []), key=lambda row: row.get("pos", 0)):
                totals["items"] += 1
                evidence = processed_evidence(
                    item, card, support_cards_by_kind, support_by_url
                )
                classification = classify_item(checklist.get("name"), item.get("name"))
                if evidence:
                    totals["processed"] += 1
                    if len(processed_sample) < 25:
                        processed_sample.append({
                            "project": config["name"], "scene_id": card["scene_id"],
                            "card": card["name"], "url": card.get("shortUrl"),
                            "checklist": checklist.get("name"), "item_id": item.get("id"),
                            "text": item.get("name"), "state": item.get("state"),
                            "evidence": evidence[:3],
                        })
                    if not include_processed:
                        continue
                    classification = {
                        "classification": "processed", "confidence": "high",
                        "reason": "matching content already exists", "cues": [],
                    }
                elif classification["classification"] == "ignored_placeholder":
                    totals["ignored_placeholders"] += 1
                    if not include_processed:
                        continue
                else:
                    totals["review_items"] += 1
                    classifications[classification["classification"]] += 1
                    if classification["classification"] == "ambiguous":
                        totals["ambiguous"] += 1
                item_results.append({
                    "id": item.get("id"), "text": item.get("name"),
                    "state": item.get("state"), "pos": item.get("pos"),
                    **classification, "processed_evidence": evidence[:3],
                })
            if item_results:
                checklist_results.append({
                    "id": checklist.get("id"), "name": checklist.get("name"),
                    "pos": checklist.get("pos"), "items": item_results,
                })
        if checklist_results:
            findings_by_card.append({
                "id": card["id"], "scene_id": card["scene_id"],
                "name": card["name"], "url": card.get("shortUrl"),
                "list": card["list_name"], "due": card.get("due"),
                "checklists": checklist_results,
            })

    return {
        "project": config["name"],
        "board": {"id": board["id"], "name": board.get("name"), "url": board.get("url")},
        "lists": {
            "active_scanned": active_list_names,
            "shot_skipped": [item["name"] for item in open_lists if kinds[item["id"]] == "shot"],
            "todo": support_list_names["todo"],
            "registry": support_list_names["registry"],
        },
        "counts": {
            "open_lists": len(open_lists), "active_lists_scanned": len(active_list_names),
            "scene_cards_scanned": len(scene_cards),
            "non_scene_cards_skipped": skipped_non_scene_cards,
            "checklists": sum(checklist_names.values()),
            "checklist_items": totals["items"],
            "already_processed": totals["processed"],
            "ignored_placeholders": totals["ignored_placeholders"],
            "review_items": totals["review_items"],
            "ambiguous": totals["ambiguous"],
            "cards_with_findings": len(findings_by_card),
            "todo_cards_compared": len(support_cards_by_kind["todo"]),
            "registry_cards_compared": len(support_cards_by_kind["registry"]),
        },
        "classification_counts": dict(sorted(classifications.items())),
        "checklist_counts": dict(sorted(checklist_names.items(), key=lambda row: folded(row[0]))),
        "processed_sample": processed_sample,
        "finding_cards": findings_by_card,
        "warnings": (["Trello ToDo list was not found; ToDo comparison is incomplete"]
                     if not support_list_names["todo"] else []),
    }


def paginated_project(result, start, limit):
    cards = result.pop("finding_cards")
    selected = cards[start:start + limit]
    result["findings"] = {
        "start": start, "limit": limit, "total_cards": len(cards),
        "returned_cards": len(selected),
        "remaining_cards": max(0, len(cards) - start - len(selected)),
        "cards": selected,
    }
    return result


def register_routes(app, api):
    @app.route("/api/meeting-notes-audit", methods=["POST"])
    def meeting_notes_audit():
        if request.headers.get("X-Meeting-Notes-Audit-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "dry-run").strip().casefold()
        if mode != "dry-run":
            return jsonify({
                "error": "read-only endpoint; apply mode is not implemented"
            }), 405
        project = request.args.get("project", "all").strip().casefold()
        if project != "all" and project not in PROJECTS:
            return jsonify({"error": "unknown project"}), 404
        try:
            start = max(0, int(request.args.get("start", "0")))
            limit = min(100, max(1, int(request.args.get("limit", "20"))))
        except ValueError:
            return jsonify({"error": "invalid start/limit"}), 400
        include_processed = request.args.get("include_processed", "0") == "1"
        selected_projects = PROJECTS if project == "all" else {project: PROJECTS[project]}
        results = []
        for config in selected_projects.values():
            results.append(paginated_project(
                audit_project(api, config, include_processed=include_processed),
                start, limit,
            ))
        totals = Counter()
        classifications = Counter()
        for result in results:
            totals.update({
                key: value for key, value in result["counts"].items()
                if isinstance(value, int)
            })
            classifications.update(result["classification_counts"])
        return jsonify({
            "status": "read-only-dry-run", "mode": "dry-run", "writes": 0,
            "microsoft_todo_accessed": False,
            "classification_policy": {
                "version": "meeting-notes-v1",
                "rule": "explicit wording plus checklist/card context; uncertainty is never guessed",
                "processed_rule": "exact text/item marker or verified linked master/ToDo/registry evidence",
            },
            "projects": results,
            "totals": dict(totals),
            "classification_counts": dict(sorted(classifications.items())),
        }), 200
