from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
from urllib.parse import urlencode

from flask import jsonify, request

from meeting_notes_dryrun import folded, list_kind


KEY = "ck-semantic-meeting-dryrun-19aug-83d41c7e"
BOARD_REF = "CzuD55PR"
EPISODES = {1, 2, 3}
PHOTO_LABEL = "FOTKA"
PHOTO_CONFIRMED = {
    "01/09", "01/12LP", "02/19LP", "03/13", "03/15", "03/20", "03/22",
    "03/27", "03/28", "03/47LP",
}
PHOTO_AMBIGUOUS = {"03/16", "01/53LP"}
BANNER_SCENES = (
    "02/43", "02/44", "02/45", "02/46", "02/47A", "02/47B",
    "02/47C", "02/48",
)
MEETING_START = "<!-- CIERNY-KAMEN-MEETING-NOTES:START -->"
MEETING_END = "<!-- CIERNY-KAMEN-MEETING-NOTES:END -->"
MEETING_ITEM_RE = re.compile(
    r"<!--\s*CIERNY-KAMEN-MEETING-ITEM:([^>]+?)\s*-->\s*"
    r"\*\*([^*]+):\*\*\s*(.*)", re.I,
)
PHOTO_RE = re.compile(
    r"\b(?:fotk\w*|fotograf\w*|fotoapar\w*|selfie|odfot\w*|vyfot\w*|"
    r"screenshot\w*|skrin\s*shot\w*|fotoalbum\w*)\b", re.I,
)
VEHICLE_RE = re.compile(
    r"\b(?:auto|auta|automobil\w*|vozidl\w*|suv|limuz[ií]n\w*|kabriolet\w*|"
    r"dod[aá]vk\w*|sanitk\w*|pohrebn[eé]\s+auto|volkswagen\w*|toyota\w*|"
    r"policajn[eé]\s+auto|[čc]ln\w*|pramic\w*|motork\w*|bicykl\w*)\b", re.I,
)
DOGY_RE = re.compile(r"\bdog(?:y|gy)(?:ho|mu|m)?\b", re.I)
DOGY_PHYSICAL_RE = re.compile(
    r"\bdog(?:y|gy)(?:ho|mu|m)?\s+(?:sed[ií]|stoj[ií]|ide|vojde|pr[ií]de|"
    r"prech[aá]dza|pozoruje|p[ií][šs]e|sle(?:duje|doval)|[čc]ak[aá]|"
    r"zostane|od[ií]de|kr[aá][čc]a|prik[ýy]vne|usmeje|pohne|zjav[ií])\b",
    re.I,
)
DOGY_PHYSICAL_OVERRIDES = {"01/12LP", "01/27FLASH", "03/24FLASH", "03/55LP"}
SCENE_REF_RE = re.compile(r"\b0*([1-9]\d*)\s*/\s*0*(\d+)([A-Za-z]*)\b")


SCENE_0153LP_SOURCE = {
    "scene_id": "01/53LP",
    "source_pdf": "SC_01_01_ČK_2.5_SG_KC_FINAL.pdf",
    "printed_page": 84,
    "pdf_page_index": 91,
    "heading": "PRI RIEKE – STRIHÁK ZÁBEROV - DAY 4",
    "characters": [
        "SÁRA", "BETY", "ALICA", "IVAN", "ALEX", "LUKÁŠ", "VERONIKA",
        "LAURA", "KIKO", "PATRIK", "SEBO", "DOGY", "KELER", "POLICAJTI",
    ],
    "prepis": "Policajti vynášajú Jakubove telo",
    "source_fact": (
        "Policajti opáskovali miesto; v origináli je jedno policajné auto, "
        "Keler, policajti, zazipsované telo na nosidlách a Alica si robí "
        "mobilom zábery."
    ),
    "user_overrides": [
        "POLICAJNÉ AUTO 2×", "AUTO KORONER", "POHREBNÉ AUTO",
        "VRECE NA MŔTVOLU", "NOSIDLÁ", "4× POLICAJTI", "POLICAJNÉ PÁSKY",
    ],
}


def episode_of(scene_id):
    match = re.match(r"^0*(\d+)\s*/", str(scene_id or ""))
    return int(match.group(1)) if match else None


def canonical_scene_id(scene_id):
    match = re.match(r"^0*(\d+)\s*/\s*0*(\d+)([A-Za-z]*)$", str(scene_id or "").strip())
    if not match:
        return str(scene_id or "").strip().upper()
    return f"{int(match.group(1)):02d}/{int(match.group(2)):02d}{match.group(3).upper()}"


def evidence_snippets(text, pattern, limit=4):
    snippets = []
    for part in re.split(r"(?<=[.!?])\s+|\n+", str(text or "")):
        part = part.strip()
        if part and pattern.search(part):
            snippets.append(part[:700])
            if len(snippets) >= limit:
                break
    return snippets


def payload_scenes():
    path = Path(__file__).with_name("cierny_kamen_pdf_payload.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload, [scene for scene in payload["scenes"] if scene.get("episode") in EPISODES]


def load_board(api):
    get = api["trello_get"]
    board = get(f"/boards/{BOARD_REF}", {"fields": "id,name,url,shortLink,closed"})
    lists = get(f"/boards/{board['id']}/lists", {
        "fields": "id,name,pos,closed", "filter": "all",
    })
    labels = get(f"/boards/{board['id']}/labels", {
        "fields": "id,name,color", "limit": 1000,
    })
    open_lists = [row for row in lists if not row.get("closed")]

    def load_chunk(chunk):
        urls = []
        for board_list in chunk:
            params = {
                "fields": "id,name,desc,shortUrl,idList,closed,pos,idLabels",
                "filter": "all", "limit": 1000,
                "checklists": "all", "checklist_fields": "name,pos",
            }
            urls.append(f"/lists/{board_list['id']}/cards?{urlencode(params)}")
        responses = get("/batch", {"urls": ",".join(urls)})
        if len(responses) != len(chunk):
            raise RuntimeError("Trello batch response length mismatch")
        loaded = {}
        for board_list, response in zip(chunk, responses):
            body = response.get("200")
            if body is None:
                raise RuntimeError(
                    f"Trello list read failed: {board_list['name']} ({next(iter(response), 'unknown')})"
                )
            loaded[board_list["id"]] = body
        return loaded

    chunks = [open_lists[index:index + 10] for index in range(0, len(open_lists), 10)]
    cards_by_list = {}
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(chunks)))) as executor:
        for loaded in executor.map(load_chunk, chunks):
            cards_by_list.update(loaded)

    list_by_id = {row["id"]: row for row in lists}
    all_cards = []
    for board_list in open_lists:
        for card in cards_by_list.get(board_list["id"], []):
            all_cards.append({**card, "list_name": board_list["name"]})
    return {
        "board": board, "lists": lists, "open_lists": open_lists,
        "list_by_id": list_by_id, "labels": labels, "cards": all_cards,
    }


def scene_cards(api, state):
    parser = api["scene_id_from_card_name"]
    grouped = defaultdict(list)
    for card in state["cards"]:
        if folded(card.get("list_name")) != "scenare":
            continue
        scene_id = parser(card.get("name"))
        if episode_of(scene_id) in EPISODES:
            grouped[canonical_scene_id(scene_id)].append(card)
    return grouped


def card_text(card):
    rows = [card.get("name") or "", card.get("desc") or ""]
    for checklist in card.get("checklists", []):
        rows.append(checklist.get("name") or "")
        rows.extend(item.get("name") or "" for item in checklist.get("checkItems", []))
    return "\n".join(rows)


def find_cards(state, phrase):
    wanted = folded(phrase)
    return [card for card in state["cards"] if wanted in folded(card.get("name"))]


def public_card(card, state):
    labels = {row["id"]: row.get("name") for row in state["labels"]}
    return {
        "id": card.get("id"), "name": card.get("name"),
        "url": card.get("shortUrl"), "list": card.get("list_name"),
        "closed": bool(card.get("closed")),
        "labels": [labels.get(label_id, label_id) for label_id in card.get("idLabels", [])],
        "checklists": [{
            "id": checklist.get("id"), "name": checklist.get("name"),
            "items": [{"id": item.get("id"), "text": item.get("name"),
                       "state": item.get("state"), "pos": item.get("pos")}
                      for item in checklist.get("checkItems", [])],
        } for checklist in card.get("checklists", [])],
    }


def set_master_plan(state, master_name, additions):
    matches = find_cards(state, master_name)
    exact = [card for card in matches if folded(card.get("name")) == folded(master_name)]
    selected = exact if exact else matches
    continuity_set = [
        card for card in selected
        if "nadvazne set" in folded(card.get("list_name"))
    ]
    # A set master is distinct from the ordinary story-space card. Prefer the
    # continuity register when it exists; ŠKOLA currently only has a space master.
    if continuity_set:
        selected = continuity_set
    result = {
        "requested_master": master_name,
        "matches": [public_card(card, state) for card in selected],
        "match_count": len(selected), "conflict": None,
        "requested_set_items": additions, "missing_set_items": [],
        "checklist_missing": False,
    }
    if len(selected) != 1:
        result["conflict"] = "master card missing" if not selected else "multiple possible master cards"
        return result
    checklist = next((row for row in selected[0].get("checklists", [])
                      if folded(row.get("name")) == "set"), None)
    result["checklist_missing"] = checklist is None
    existing = [item.get("name") or "" for item in (checklist or {}).get("checkItems", [])]
    result["missing_set_items"] = [
        item for item in additions
        if not any(folded(item) in folded(current) or folded(current) in folded(item)
                   for current in existing if current.strip())
    ]
    return result


def photo_plan(scenes, grouped, state):
    source = {canonical_scene_id(scene["scene_id"]): scene for scene in scenes}
    labels = [row for row in state["labels"] if folded(row.get("name")) == folded(PHOTO_LABEL)]
    confirmed = []
    ambiguous = []
    for scene_id in sorted(PHOTO_CONFIRMED):
        scene = source.get(scene_id)
        cards = grouped.get(scene_id, [])
        text = "\n".join((scene or {}).get(key, "") for key in ("prepis", "action_raw"))
        if scene_id == "01/09":
            manual = "\n".join(
                item.get("name") or ""
                for card in cards for checklist in card.get("checklists", [])
                for item in checklist.get("checkItems", [])
                if "fotoapar" in folded(item.get("name"))
            )
            text += "\n" + manual
        confirmed.append({
            "scene_id": scene_id, "title": (scene or {}).get("prepis"),
            "evidence": evidence_snippets(text, PHOTO_RE),
            "cards": [public_card(card, state) for card in cards],
            "card_collision": len(cards) != 1,
            "already_labeled": bool(labels and any(labels[0]["id"] in card.get("idLabels", []) for card in cards)),
        })
    for scene_id in sorted(PHOTO_AMBIGUOUS):
        if scene_id == "01/53LP":
            ambiguous.append({
                "scene_id": scene_id,
                "reason": "originál hovorí, že Alica robí mobilom zábery; nie je určené, či ide o foto alebo video",
                "evidence": [SCENE_0153LP_SOURCE["source_fact"]],
            })
            continue
        scene = source.get(scene_id)
        ambiguous.append({
            "scene_id": scene_id,
            "reason": "fotografia je iba uvedená ako motivácia/backstory, nie je jasné, či fyzicky hrá v obraze",
            "evidence": evidence_snippets((scene or {}).get("action_raw", ""), PHOTO_RE),
        })

    board_only = []
    reviewed = PHOTO_CONFIRMED | PHOTO_AMBIGUOUS
    for scene_id, cards in grouped.items():
        if scene_id in reviewed:
            continue
        hits = []
        for card in cards:
            checklist_text = "\n".join(
                item.get("name") or ""
                for checklist in card.get("checklists", [])
                for item in checklist.get("checkItems", [])
            )
            hits.extend(evidence_snippets(checklist_text, PHOTO_RE, limit=3))
        if hits:
            board_only.append({
                "scene_id": scene_id, "reason": "Trello-only/manual evidence; requires semantic confirmation",
                "evidence": list(dict.fromkeys(hits))[:5],
                "cards": [public_card(card, state) for card in cards],
            })
    return {
        "existing_label_matches": labels,
        "label_action": "reuse" if len(labels) == 1 else ("create" if not labels else "conflict"),
        "confirmed_scene_count": len(confirmed), "confirmed": confirmed,
        "ambiguous": ambiguous, "board_only_candidates": board_only,
        "selection_rule": "physical/displayed photograph or photographing action, not a dialogue-only mention",
    }


def scene_0153_plan(grouped, state, payload):
    exact_53 = grouped.get("01/53", [])
    exact_53lp = grouped.get("01/53LP", [])
    payload_ids = {canonical_scene_id(scene["scene_id"]) for scene in payload["scenes"]}
    action = "reuse_01_53LP" if len(exact_53lp) == 1 else (
        "create_01_53LP" if not exact_53lp and not exact_53 else "blocked_collision"
    )
    return {
        "authoritative_source": SCENE_0153LP_SOURCE,
        "payload_contains_01_53": "01/53" in payload_ids,
        "payload_contains_01_53LP": "01/53LP" in payload_ids,
        "payload_defect": "01/53LP is appended to 01/52 action_raw and absent as a standalone payload scene",
        "board_01_53": [public_card(card, state) for card in exact_53],
        "board_01_53LP": [public_card(card, state) for card in exact_53lp],
        "proposed_action": action,
        "important": "Do not create 01/53; the source ID is 01/53LP.",
        "source_vs_user": {
            "source_has": ["1× policajné auto", "policajti", "policajné pásky", "zazipsované telo", "nosidlá"],
            "user_adds_or_specifies": SCENE_0153LP_SOURCE["user_overrides"],
        },
    }


def banner_plan(grouped, state):
    master_matches = find_cards(state, "BANNER NA OTVORENIE BASKETBALOVEJ SEZÓNY")
    rows = []
    for scene_id in BANNER_SCENES:
        cards = grouped.get(scene_id, [])
        fallback = None
        if not cards:
            base = re.sub(r"[A-Z]+$", "", scene_id)
            base_cards = grouped.get(base, [])
            if len(base_cards) == 1:
                fallback = {"scene_id": base, "card": public_card(base_cards[0], state)}
        rows.append({
            "scene_id": scene_id, "cards": [public_card(card, state) for card in cards],
            "exact_count": len(cards), "fallback": fallback,
            "status": "exact" if len(cards) == 1 else (
                "missing_with_fallback" if fallback else ("missing" if not cards else "duplicate")
            ),
        })
    return {
        "identity": "BANNER NA OTVORENIE BASKETBALOVEJ SEZÓNY",
        "master_matches": [public_card(card, state) for card in master_matches],
        "master_action": "reuse" if len(master_matches) == 1 else (
            "create" if not master_matches else "conflict"
        ),
        "scenes": rows,
        "input_interpretation": "2/47C2/48 is treated only as two requested IDs: 02/47C and 02/48",
    }


def dogy_plan(scenes, grouped, state):
    confirmed = []
    ambiguous = []
    for scene in scenes:
        scene_id = canonical_scene_id(scene["scene_id"])
        text = "\n".join((scene.get("characters_raw", ""), scene.get("action_raw", "")))
        if not DOGY_RE.search(text):
            continue
        characters = [folded(value) for value in scene.get("characters", [])]
        exact_character = "dogy" in characters
        physical_evidence = evidence_snippets(scene.get("action_raw", ""), DOGY_PHYSICAL_RE)
        if scene_id in DOGY_PHYSICAL_OVERRIDES and not physical_evidence:
            physical_evidence = evidence_snippets(scene.get("action_raw", ""), DOGY_RE)
        only_vo_mo = not exact_character and not physical_evidence
        row = {
            "scene_id": scene_id, "title": scene.get("prepis"),
            "characters_raw": scene.get("characters_raw"),
            "evidence": physical_evidence or evidence_snippets(text, DOGY_RE),
            "cards": [public_card(card, state) for card in grouped.get(scene_id, [])],
        }
        if only_vo_mo:
            row["reason"] = "only VO/MO/dialogue/mention evidence; physical presence not proven"
            ambiguous.append(row)
        else:
            row["reason"] = "exact DOGY character or explicit physical action"
            confirmed.append(row)

    # 01/53LP is missing from the payload but visually verified in the PDF.
    if not any(row["scene_id"] == "01/53LP" for row in confirmed):
        confirmed.append({
            "scene_id": "01/53LP", "title": SCENE_0153LP_SOURCE["prepis"],
            "characters_raw": ", ".join(SCENE_0153LP_SOURCE["characters"]),
            "evidence": ["Dogy prechádza v pozadí a tvári sa ako novinár na mieste činu."],
            "cards": [public_card(card, state) for card in grouped.get("01/53LP", [])],
            "reason": "physical presence verified on PDF page 84",
        })

    master_matches = [card for card in state["cards"] if any(
        token in folded(card.get("name")) for token in ("doggyho sluchadla", "dogyho sluchadla")
    )]
    linked_scene_ids = []
    for scene_id, cards in grouped.items():
        if any("sluchadl" in folded(card_text(card)) and "dog" in folded(card_text(card))
               for card in cards):
            linked_scene_ids.append(scene_id)
    return {
        "identity": "Doggyho slúchadlá",
        "master_matches": [public_card(card, state) for card in master_matches],
        "master_action": "reuse" if len(master_matches) == 1 else (
            "create_in_DOGY_OS_REKVIZITY" if not master_matches else "conflict"
        ),
        "confirmed_physical_count": len(confirmed),
        "confirmed_physical": sorted(confirmed, key=lambda row: row["scene_id"]),
        "ambiguous_vo_mo_or_mention_count": len(ambiguous),
        "ambiguous_vo_mo_or_mention": sorted(ambiguous, key=lambda row: row["scene_id"]),
        "existing_linked_scene_ids": sorted(linked_scene_ids),
        "planned_item_rule": "add one linked personal-prop item only to confirmed physical scenes; never to VO/MO-only candidates",
    }


def eclipse_plan(scenes, grouped, state):
    source = {canonical_scene_id(scene["scene_id"]): scene for scene in scenes}

    def row(scene_id, reason):
        scene = source.get(scene_id, {})
        pattern = re.compile(r"eclipse|tane[čc]n|vyst[uú]p|kapel|koncert", re.I)
        return {
            "scene_id": scene_id, "title": scene.get("prepis"), "reason": reason,
            "evidence": evidence_snippets(scene.get("action_raw", ""), pattern),
            "cards": [public_card(card, state) for card in grouped.get(scene_id, [])],
        }

    return {
        "source_conflict": (
            "The scripts define ECLIPSE as Sára's dance group. Beka's performing band is not named ECLIPSE. "
            "Therefore no card is proposed as an unambiguous 'band ECLIPSE' performance."
        ),
        "confirmed_dance_group_performance": [
            row("02/46", "Eclipse dancers perform while Beka's separately identified band plays")
        ],
        "continuation_candidate": [
            row("02/47A", "audience reaction continues immediately after the student performance")
        ],
        "rehearsal_or_audition_not_performance": [
            row("01/33", "Eclipse audition"),
            row("02/33", "dance-group choreography/rehearsal"),
            row("02/43", "last rehearsal before performance"),
        ],
        "decision_needed": "Confirm whether 'logo ECLIPSE' belongs to the dance group scenes or to Beka's unnamed band setup.",
    }


def meeting_notes_plan(grouped, state):
    rows = []
    seen = set()
    for scene_id, cards in grouped.items():
        for card in cards:
            desc = card.get("desc") or ""
            block_match = re.search(
                re.escape(MEETING_START) + r"(.*?)" + re.escape(MEETING_END),
                desc, flags=re.S,
            )
            sources = []
            if block_match:
                for line in block_match.group(1).splitlines():
                    match = MEETING_ITEM_RE.search(line)
                    if match:
                        sources.append((match.group(1).strip(), match.group(2).strip(), match.group(3).strip(), "auto_block"))
            for checklist in card.get("checklists", []):
                if folded(checklist.get("name")) not in {"info z porady", "info z natacania"}:
                    continue
                for item in checklist.get("checkItems", []):
                    sources.append((item.get("id"), checklist.get("name"), item.get("name") or "", "live_checklist"))
            other_items = []
            for checklist in card.get("checklists", []):
                if folded(checklist.get("name")) in {"rekvizity", "set"}:
                    other_items.extend((checklist.get("name"), item.get("name") or "")
                                       for item in checklist.get("checkItems", []))
            for item_id, checklist_name, text, source in sources:
                key = (scene_id, item_id)
                if key in seen:
                    continue
                seen.add(key)
                normalized = folded(text)
                if "?" in text or any(token in normalized for token in (
                    "pride prepis", "setup sa doriesi", "dohodnut na technickych",
                    "podla planu a lokacie", "podla lokacie",
                )):
                    target = "AMBIGUOUS_OR_PENDING_DECISION"
                elif any(token in normalized for token in (
                    "obraz zruseny", "zlucenie obrazov", "oprava textu", "prepis",
                )):
                    target = "SCENE_EDITORIAL_DECISION"
                elif any(token in normalized for token in (
                    "setup", "set ", "podium", "sedenie", "logo", "automat",
                    "sklad", "hudobnej miestnosti", "nastenk", "svetiel",
                )):
                    target = "SET"
                elif any(token in normalized for token in (
                    "auto", "pramica", "fotograf", "fotoaparat", "banner", "vrece",
                    "nosidl", "pask", "monogram", "pes ", "paroch", "blister",
                    "penazi", "batoh", "batozin", "zbran", "rekvi",
                )):
                    target = "REKVIZITY"
                else:
                    target = "PRODUCTION_OR_DESCRIPTION"
                matches = [{"checklist": checklist, "text": current}
                           for checklist, current in other_items
                           if normalized and (normalized in folded(current) or folded(current) in normalized)]
                rows.append({
                    "scene_id": scene_id, "card": card.get("name"), "url": card.get("shortUrl"),
                    "item_id": item_id, "source_checklist": checklist_name,
                    "source": source, "text": text, "proposed_target": target,
                    "already_present_in_target": matches[:5],
                    "action": "unchanged" if matches else (
                        "manual_decision" if target == "AMBIGUOUS_OR_PENDING_DECISION" else "propose_semantic_apply"
                    ),
                })
    counts = Counter(row["proposed_target"] for row in rows)
    return {
        "source_items": len(rows), "target_counts": dict(sorted(counts.items())),
        "already_semantically_present": sum(bool(row["already_present_in_target"]) for row in rows),
        "proposed_changes": sum(row["action"] == "propose_semantic_apply" for row in rows),
        "manual_decisions": sum(row["action"] == "manual_decision" for row in rows),
        "items": sorted(rows, key=lambda row: (row["scene_id"], row["item_id"] or "")),
        "protection": "source checklist items, states, manual text and the evidence auto-block remain unchanged",
    }


def vehicles_plan(state):
    label_by_id = {row["id"]: row.get("name") for row in state["labels"]}
    auto_labels = [row for row in state["labels"] if folded(row.get("name")) == "auto"]
    target_lists = [row for row in state["open_lists"] if folded(row.get("name")) == "auta"]
    candidates = []
    ambiguous = []
    excluded_non_vehicle = []
    for card in state["cards"]:
        list_name = folded(card.get("list_name"))
        master_list = (
            "register rekviz" in list_name or "os. rekviz" in list_name
            or "osobne rekviz" in list_name
        )
        if not master_list:
            continue
        names = [label_by_id.get(label_id, "") for label_id in card.get("idLabels", [])]
        has_auto_label = any(folded(name) == "auto" for name in names)
        vehicle_hit = bool(VEHICLE_RE.search(card.get("name") or ""))
        if not has_auto_label and not vehicle_hit:
            continue
        references = {
            canonical_scene_id(f"{match.group(1)}/{match.group(2)}{match.group(3)}")
            for match in SCENE_REF_RE.finditer(card_text(card))
        }
        in_scope_references = sorted(
            scene_id for scene_id in references if episode_of(scene_id) in EPISODES
        )
        if not in_scope_references:
            continue
        component_or_content = any(token in folded(card.get("name")) for token in (
            "batozinovy priestor", "fotografi", "vesla", "mobil s fotograf",
        ))
        if component_or_content:
            excluded_non_vehicle.append({
                **public_card(card, state),
                "reason": "name describes vehicle content/component, not the physical vehicle",
                "scene_references": in_scope_references,
            })
            continue
        public = public_card(card, state)
        generic = folded(card.get("name")) in {
            "auto", "vozidlo", "auto vozidlo", "dodavka", "cln", "pramica",
        }
        row = {
            **public, "reason": (
                "existing Auto label" if has_auto_label else "specific physical-vehicle name"
            ),
            "needs_auto_label": not has_auto_label,
            "move_needed": folded(card.get("list_name")) != "auta",
            "scene_references": in_scope_references,
        }
        if generic or (not has_auto_label and len(folded(card.get("name")).split()) < 2):
            row["ambiguity"] = "generic identity; do not move until the physical vehicle is resolved"
            ambiguous.append(row)
        else:
            candidates.append(row)
    def conflict_family(row):
        name = folded(row["name"])
        if name.startswith("dodavka") and not any(
            owner in name for owner in ("alic", "bet", "dogy", "jakub", "kiko", "laur", "olas", "sar", "veronik")
        ):
            return "Neidentifikovaná dodávka – vlastníctvo/dejová identita neurčená"
        if "auto" in name and "jakub" in name and "sar" in name:
            return "Auto Jakuba a Sáry"
        if "auto" in name and "olasov" in name:
            return "Olasovej auto"
        if "policajn" in name and "auto" in name:
            return "Policajné auto – identity/kusy neurčené"
        if ("cln" in name or "pramica" in name) and "policajn" not in name:
            return "Čln/pramica pri rieke – totožnosť neurčená"
        if name.startswith("auto ") and not any(
            owner in name for owner in ("kiko", "jakub", "sar", "olasov")
        ):
            return "Neidentifikované auto podľa lokálneho kontextu"
        return None

    groups = defaultdict(list)
    for row in candidates:
        groups[folded(row["name"])].append(row)
    duplicate_groups = [rows for rows in groups.values() if len(rows) > 1]
    conflict_groups = defaultdict(list)
    safe_candidates = []
    for row in candidates:
        family = conflict_family(row)
        if family:
            conflict_groups[family].append(row)
        else:
            safe_candidates.append(row)
    return {
        "existing_AUTA_lists": target_lists,
        "list_action": "reuse" if len(target_lists) == 1 else (
            "create" if not target_lists else "conflict"
        ),
        "existing_Auto_labels": auto_labels,
        "reviewed_physical_vehicle_cards": len(candidates),
        "confirmed_master_count": len(safe_candidates),
        "confirmed_master_cards": safe_candidates,
        "blocked_semantic_conflict_groups": [
            {"identity_family": family, "cards": rows}
            for family, rows in sorted(conflict_groups.items())
        ],
        "ambiguous_count": len(ambiguous), "ambiguous_or_excluded": ambiguous,
        "duplicate_identity_groups": duplicate_groups,
        "excluded_non_vehicle": excluded_non_vehicle,
        "exclusion_rule": "scene cards and ToDo cards are never candidates; generic identities are not moved",
    }


def todo_impact(state, identity):
    todo_lists = [row for row in state["open_lists"] if folded(row.get("name")) == "todo"]
    matches = [card for card in state["cards"]
               if folded(card.get("list_name")) == "todo" and folded(identity) in folded(card.get("name"))]
    return {
        "todo_lists": todo_lists,
        "existing_matches": [public_card(card, state) for card in matches],
        "trello_todo_action": "reuse_update" if len(matches) == 1 else (
            "create" if not matches else "merge_conflict"
        ),
        "microsoft_todo_predicted_action": "update" if len(matches) == 1 else (
            "create_after_trello" if not matches else "blocked_until_merge"
        ),
    }


def build_audit(api):
    payload, scenes = payload_scenes()
    state = load_board(api)
    grouped = scene_cards(api, state)
    parser = api["scene_id_from_card_name"]
    parallel_scene_cards = [
        public_card(card, state) for card in state["cards"]
        if folded(card.get("list_name")) == "original screener"
        and episode_of(parser(card.get("name"))) in EPISODES
    ]
    duplicate_scenes = {
        scene_id: [public_card(card, state) for card in cards]
        for scene_id, cards in grouped.items() if len(cards) > 1
    }
    fefe = set_master_plan(
        state, "FEFE BEEF – PARKOVISKO",
        ["Červené exteriérové sedenie", "Neónové logo FEFE BEEF"],
    )
    school = set_master_plan(state, "ŠKOLA", ["Školský reproduktor"])
    school["todo_impact"] = todo_impact(state, "školský reproduktor")
    pitva = set_master_plan(state, "PITEVŇA", ["Podsvetľovací box na röntgen"])
    return {
        "status": "read-only-dry-run", "mode": "dry-run", "writes": 0,
        "scope": {"board_ref": BOARD_REF, "project": "Čierny Kameň / Riverdale", "episodes": [1, 2, 3]},
        "board": state["board"],
        "counts": {
            "authoritative_payload_scenes_ep01_03": len(scenes),
            "board_scene_ids_ep01_03": len(grouped),
            "board_scene_cards_ep01_03": sum(len(cards) for cards in grouped.values()),
            "duplicate_scene_ids": len(duplicate_scenes),
            "parallel_original_screener_cards_excluded": len(parallel_scene_cards),
            "open_lists": len(state["open_lists"]), "board_labels": len(state["labels"]),
        },
        "duplicate_scenes": duplicate_scenes,
        "parallel_original_screener": {
            "excluded_from_every_proposed_change": True,
            "count": len(parallel_scene_cards), "cards": parallel_scene_cards,
        },
        "set_masters": {"fefe_beef_parkovisko": fefe, "skola": school, "pitevna": pitva},
        "photo_label": photo_plan(scenes, grouped, state),
        "scene_01_53": scene_0153_plan(grouped, state, payload),
        "eclipse_logo": eclipse_plan(scenes, grouped, state),
        "dogy_headphones": dogy_plan(scenes, grouped, state),
        "season_opening_banner": banner_plan(grouped, state),
        "meeting_notes": meeting_notes_plan(grouped, state),
        "vehicles_list": vehicles_plan(state),
        "microsoft_todo_accessed": False,
        "write_guards": {
            "trello_post_put_delete_calls": 0, "graph_calls": 0,
            "apply_mode": "HTTP 405; not implemented",
        },
    }


def register_routes(app, api):
    @app.route("/api/audit-ck-meeting-semantic-ep01-03", methods=["POST"])
    def audit_ck_meeting_semantic_ep01_03():
        if request.headers.get("X-CK-Semantic-Audit-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "dry-run").strip().casefold()
        if mode != "dry-run":
            return jsonify({
                "error": "read-only endpoint; apply mode is not implemented", "writes": 0,
            }), 405
        try:
            return jsonify(build_audit(api)), 200
        except Exception as error:
            app.logger.exception("Čierny Kameň meeting semantic dry-run failed")
            return jsonify({
                "status": "read-only-audit-failed", "writes": 0,
                "error": f"{type(error).__name__}: {error}",
            }), 502
