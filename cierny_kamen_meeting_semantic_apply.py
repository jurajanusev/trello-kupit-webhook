from __future__ import annotations

import hashlib
import json
import re

from flask import jsonify, request

from cierny_kamen_meeting_semantic_dryrun import (
    BANNER_SCENES, BOARD_REF, PHOTO_CONFIRMED, SCENE_0153LP_SOURCE,
    build_audit, canonical_scene_id, folded, load_board, payload_scenes,
    scene_cards,
)


KEY = "ck-semantic-meeting-apply-19aug-c7e20f4b"
AUTO_START = "<!-- CIERNY-KAMEN-REGISTRY-AUTO:START -->"
AUTO_END = "<!-- CIERNY-KAMEN-REGISTRY-AUTO:END -->"
PHOTO_LABEL = "FOTKA"


SET_MASTER_ITEMS = {
    "FEFE BEEF – PARKOVISKO": [
        "Červené exteriérové sedenie", "Neónové logo FEFE BEEF",
    ],
    "ŠKOLA": ["Školský reproduktor"],
    "PITEVŇA": ["Podsvetľovací box na röntgen"],
}


SAFE_SET_NOTES = {
    "01/23": ["automat vybavi produkcia"],
    "01/40": ["VEĽA SVETIELOK", "PÓDIUM"],
    "02/12": ["VŠEOBECNÁ INFO - RAŇAJKOVÝ SETUP PEKNE A BOHATO NASETOVANÝ"],
    "02/41": ["AUTOMAT NEROZBÍJAME"],
    "02/43": ["SETUP PODĽA TECHNICKÝCH OBHLIADOK", "Logo tanečnej skupiny ECLIPSE"],
    "02/46": ["Logo tanečnej skupiny ECLIPSE – vystúpenie"],
    "02/47A": ["Logo tanečnej skupiny ECLIPSE – bezprostredné pokračovanie vystúpenia"],
    "02/49": ["VEĽKÝ BANNER S LOGOM ONYX - TRHÁME - TÍM CEZ NEHO PREBIEHA"],
    "03/11": ["ZARIADENÉ AKO SKLAD"],
    "03/19": ["OBR. BUDE V HUDOBNEJ MIESTNOSTI"],
    "03/28": ["BEZ NÁSTENKY"],
}


SAFE_PROP_NOTES = {
    "01/07": [
        "VÝBAVA PRE SKAUTOV - LANÁ, MAČETY, NOŽE, ĎALEKOHĽAD, ČUTORY",
        "ODZNAKY PRE SKAUTOV", "DREVENÁ PRAMICA PREVRÁTENÁ VO VODE",
    ],
    "01/09": ["DODÁVKA - REKVI", "VÝbava skupiny skautov – batohy", "Dogyho fotoaparát"],
    "01/12LP": [
        "Fotografia v rámiku – Jakub v drese a Sára v tanečnom",
        "Fotoalbum Jakuba z detstva",
    ],
    "01/13": ["SUV Laury a Veroniky – vybrať a dať schváliť", "Batožina Laury a Veroniky"],
    "01/15": ["Kikovo staršie ojazdené auto"],
    "01/18": ["Obálka s hotovosťou približne 1 200 eur"],
    "01/19": ["Betine lieky vo fľaštičke s vyrábanou etiketou"],
    "01/38": ["Pliešok s monogramom L. S."],
    "01/39": ["Pes – labrador alebo zlatý retriever"],
    "01/51": ["Kikovo auto"],
    "03/24FLASH": ["Expanzná zbraň – nie revolver"],
    "03/47LP": ["Parochňa v skrinke"],
}


SCENE_0153_PROPS = [
    "Policajné autá pri náleze Jakubovho tela (2×)",
    "Auto koronera pri náleze Jakubovho tela",
    "Pohrebné auto pri náleze Jakubovho tela",
    "Vrece na Jakubovo telo", "Nosidlá na Jakubovo telo",
    "Policajné pásky pri náleze Jakubovho tela",
    "Alicin mobil na zábery z miesta činu", "Doggyho slúchadlá",
]


def _exact(items, name):
    wanted = folded(name)
    return [item for item in items if folded(item.get("name")) == wanted]


def _card_hash(card):
    protected = {
        "desc": card.get("desc") or "", "labels": sorted(card.get("idLabels", [])),
        "checklists": [{
            "id": row.get("id"), "name": row.get("name"),
            "items": [(i.get("id"), i.get("name"), i.get("state"), i.get("pos"))
                      for i in row.get("checkItems", [])],
        } for row in card.get("checklists", [])],
    }
    return hashlib.sha256(json.dumps(protected, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _find_checklist(card, name):
    matches = _exact(card.get("checklists", []), name)
    return matches[0] if len(matches) == 1 else None


def _ensure_checklist(api, card, name):
    matches = _exact(card.get("checklists", []), name)
    if len(matches) > 1:
        raise RuntimeError(f"duplicate {name} checklists on {card['name']}")
    if matches:
        return matches[0], 0
    row = api["trello_post_body"]("/checklists", {"idCard": card["id"], "name": name, "pos": "bottom"})
    row = {**row, "checkItems": []}
    card.setdefault("checklists", []).append(row)
    return row, 1


def _ensure_item(api, card, checklist_name, text):
    checklist, writes = _ensure_checklist(api, card, checklist_name)
    core = folded(re.sub(r"\s*\|\s*KARTA:\s*https?://\S+\s*$", "", text))
    for item in checklist.get("checkItems", []):
        current = folded(re.sub(r"\s*\|\s*KARTA:\s*https?://\S+\s*$", "", item.get("name") or ""))
        if core == current:
            return writes, False
    created = api["trello_post_body"](f"/checklists/{checklist['id']}/checkItems", {"name": text, "pos": "bottom"})
    checklist.setdefault("checkItems", []).append(created)
    return writes + 1, True


def _registry_desc(name, category, appearances):
    links = "\n".join(f"- [{scene_id} – {title}]({url})" for scene_id, title, url in appearances)
    return (
        f"{AUTO_START}\nKANONICKÝ NÁZOV: {name}\nKATEGÓRIE: {category}\n\n"
        f"VÝSKYTY V OBRAZOCH:\n{links or '-'}\n{AUTO_END}"
    )


def _ensure_list(api, state, name):
    matches = _exact(state["open_lists"], name)
    if len(matches) > 1:
        raise RuntimeError(f"multiple open lists named {name}")
    if matches:
        return matches[0], 0
    row = api["trello_post_body"]("/lists", {"idBoard": state["board"]["id"], "name": name, "pos": "bottom"})
    state["open_lists"].append(row)
    state["lists"].append(row)
    return row, 1


def _ensure_label(api, state, name, color="yellow"):
    matches = _exact(state["labels"], name)
    if len(matches) > 1:
        raise RuntimeError(f"multiple labels named {name}")
    if matches:
        return matches[0], 0
    row = api["trello_post_body"]("/labels", {"idBoard": state["board"]["id"], "name": name, "color": color})
    state["labels"].append(row)
    return row, 1


def _ensure_label_on_card(api, card, label_id):
    if label_id in card.get("idLabels", []):
        return 0
    desired = list(card.get("idLabels", [])) + [label_id]
    api["trello_put_body"](f"/cards/{card['id']}", {"idLabels": ",".join(desired)})
    card["idLabels"] = desired
    return 1


def _ensure_master(api, state, name, target_list, category, appearances):
    matches = [card for card in state["cards"] if folded(card.get("name")) == folded(name)]
    if len(matches) > 1:
        raise RuntimeError(f"duplicate master identity: {name}")
    if matches:
        return matches[0], 0
    board_list, list_writes = _ensure_list(api, state, target_list)
    card = api["trello_post_body"]("/cards", {
        "idList": board_list["id"], "name": name,
        "desc": _registry_desc(name, category, appearances), "pos": "bottom",
    })
    card = {**card, "list_name": target_list, "idLabels": [], "checklists": []}
    state["cards"].append(card)
    return card, list_writes + 1


def _scene_item(name, master_url, context=None, previous=None, following=None, continuity=False):
    prefix = "<n> " if continuity else ""
    if not context:
        return f"{prefix}**{name}** | KARTA: {master_url}"
    flow = []
    if previous:
        flow.append(f"← {previous}")
    flow.append(context)
    if following:
        flow.append(f"→ {following}")
    return f"{prefix}**{name}** — *{' | '.join(flow)}* | KARTA: {master_url}"


def _existing_scene_list(state):
    matches = _exact(state["open_lists"], "SCENÁRE")
    if len(matches) != 1:
        raise RuntimeError("SCENÁRE list is missing or ambiguous")
    return matches[0]


def _create_0153lp(api, state, grouped):
    if grouped.get("01/53LP"):
        return grouped["01/53LP"][0], 0
    if grouped.get("01/53"):
        raise RuntimeError("01/53 collision blocks creation of 01/53LP")
    _payload, scenes = payload_scenes()
    scene52 = next(scene for scene in scenes if canonical_scene_id(scene["scene_id"]) == "01/52")
    raw = scene52["action_raw"]
    marker = "1/53LP "
    if marker not in raw:
        raise RuntimeError("01/53LP source boundary missing from payload")
    source = raw[raw.index(marker):]
    dialogue = re.split(r"\s+DOGY VO\s+", source, maxsplit=1)
    action = dialogue[0].split(SCENE_0153LP_SOURCE["prepis"], 1)[-1].strip()
    dogy = dialogue[1].strip() if len(dialogue) == 2 else ""
    desc = (
        f"## {SCENE_0153LP_SOURCE['prepis']}\n\n"
        "### REKVIZITY V KONTEXTE\n\n"
        "Policajné autá 2×, auto koronera, pohrebné auto, vrece na mŕtvolu, "
        "nosidlá, policajné pásky a Alicin mobil. Na mieste sú 4 policajti.\n\n"
        "### NADVÄZNOSŤ\n\n### ODKAZY\n\n### KONTINUITA PRIESTORU\n\n"
        "### KONTINUITA POSTÁV\n\n### RUČNÉ DOPLNENIA\n\n"
        "### AKCIA A DIALÓGY\n\n"
        f"*{action}*\n\n> **DOGY VO:**\n> {dogy}\n\n"
        "<!-- CIERNY-KAMEN-SCHEDULE-METADATA:START -->\n"
        "ČÍSLO OBRAZU: 01/53LP\n"
        "ZDROJ: SC_01_01_ČK_2.5_SG_KC_FINAL.pdf\n"
        "NATÁČACÍ DEŇ: nenaplánované\nDÁTUM: nenaplánované\n"
        "PORADIE: nenaplánované\nUNIT: nenaplánované\n"
        "LOKÁCIA: PRI RIEKE\nPOSTAVY: " + ", ".join(SCENE_0153LP_SOURCE["characters"]) + "\n"
        "<!-- CIERNY-KAMEN-SCHEDULE-METADATA:END -->"
    )
    card = api["trello_post_body"]("/cards", {
        "idList": _existing_scene_list(state)["id"],
        "name": "01/53LP. PRI RIEKE – STRIHÁK ZÁBEROV - DAY 4 – " + SCENE_0153LP_SOURCE["prepis"],
        "desc": desc, "pos": "bottom",
    })
    full = {**card, "checklists": [], "idLabels": [], "list_name": "SCENÁRE"}
    writes = 1
    for name in ("REKVIZITY", "SET", "INFO Z PORADY", "INFO Z NATÁČANIA", "OTÁZKY NA PORADU"):
        _checklist, count = _ensure_checklist(api, full, name)
        writes += count
    return full, writes


def _plan_summary(api):
    audit = build_audit(api)
    audit["eclipse_logo"]["decision"] = "ECLIPSE is the dance group"
    audit["eclipse_logo"]["apply_scene_ids"] = ["02/43", "02/46", "02/47A"]
    audit["write_plan"] = {
        "set_master_items": sum(len(v) for v in SET_MASTER_ITEMS.values()),
        "photo_labels": len(PHOTO_CONFIRMED), "dogy_scenes": audit["dogy_headphones"]["confirmed_physical_count"],
        "banner_scenes": len(BANNER_SCENES), "safe_set_notes": sum(map(len, SAFE_SET_NOTES.values())),
        "safe_prop_notes": sum(map(len, SAFE_PROP_NOTES.values())),
        "scene_01_53LP": audit["scene_01_53"]["proposed_action"],
        "vehicle_safe_moves": audit["vehicles_list"]["confirmed_master_count"],
        "blocked_vehicle_groups": len(audit["vehicles_list"]["blocked_semantic_conflict_groups"]),
    }
    return audit


def _apply_bootstrap(api):
    state = load_board(api)
    grouped = scene_cards(api, state)
    writes = 0; changed = []
    photo, count = _ensure_label(api, state, PHOTO_LABEL, "pink")
    writes += count; changed += (["created label FOTKA"] if count else [])
    # Create dependent master identities first. Their URLs are stable inputs for scene items.
    dogy_rows = []
    audit = build_audit(api)
    for row in audit["dogy_headphones"]["confirmed_physical"]:
        cards = row.get("cards") or []
        if len(cards) == 1:
            dogy_rows.append((row["scene_id"], row.get("title") or cards[0]["name"], cards[0]["url"]))
    dogy, count = _ensure_master(api, state, "Doggyho slúchadlá", "DOGY – OS. REKVIZITY", "Osobná rekvizita; Nadväzná rekvizita", dogy_rows)
    writes += count; changed += (["created Doggyho slúchadlá"] if count else [])
    banner_rows = []
    for scene_id in BANNER_SCENES:
        cards = grouped.get(scene_id, [])
        if len(cards) == 1:
            banner_rows.append((scene_id, cards[0]["name"], cards[0]["shortUrl"]))
    banner, count = _ensure_master(api, state, "BANNER NA OTVORENIE BASKETBALOVEJ SEZÓNY", "REGISTER REKVIZÍT", "Nadväzná rekvizita", banner_rows)
    writes += count; changed += (["created banner master"] if count else [])
    personal, count = _ensure_label(api, state, "Osobná rekvizita", "purple")
    writes += count
    continuity, count = _ensure_label(api, state, "Nadväzná rekvizita", "green")
    writes += count
    writes += _ensure_label_on_card(api, dogy, personal["id"])
    writes += _ensure_label_on_card(api, dogy, continuity["id"])
    writes += _ensure_label_on_card(api, banner, continuity["id"])
    _cars, count = _ensure_list(api, state, "AUTÁ")
    writes += count; changed += (["created AUTÁ list"] if count else [])
    scene, count = _create_0153lp(api, state, grouped)
    writes += count; changed += (["created 01/53LP"] if count else [])
    # One ToDo card for the requested school speaker, without duplicate creation.
    todo_lists = _exact(state["open_lists"], "ToDo")
    school = [card for card in state["cards"] if folded(card.get("name")) == folded("ŠKOLA")]
    todo_matches = [card for card in state["cards"] if folded("Školský reproduktor") in folded(card.get("name")) and folded(card.get("list_name")) == "todo"]
    if len(todo_lists) != 1 or len(school) != 1 or len(todo_matches) > 1:
        raise RuntimeError("Školský reproduktor ToDo target is missing or ambiguous")
    if not todo_matches:
        todo = api["trello_post_body"]("/cards", {
            "idList": todo_lists[0]["id"], "name": "Školský reproduktor - ŠKOLA",
            "desc": "Zabezpečiť školský reproduktor.\n\nSET master: " + school[0]["shortUrl"],
            "pos": "bottom",
        })
        state["cards"].append({**todo, "list_name": "ToDo", "idLabels": [], "checklists": []})
        writes += 1; changed.append("created school speaker Trello ToDo")
    return {"status": "bootstrap-applied", "writes": writes, "changed": changed, "scene_01_53LP": scene.get("shortUrl")}


def _apply_content(api, start, limit):
    state = load_board(api); grouped = scene_cards(api, state)
    operations = []
    # Fixed master SET additions.
    for master_name, items in SET_MASTER_ITEMS.items():
        matches = [card for card in state["cards"] if folded(card.get("name")) == folded(master_name)]
        if master_name in {"FEFE BEEF – PARKOVISKO", "PITEVŇA"}:
            matches = [card for card in matches if "nadvazne set" in folded(card.get("list_name"))]
        if len(matches) == 1:
            for text in items:
                if master_name == "ŠKOLA" and folded(text) == folded("Školský reproduktor"):
                    todo = [card for card in state["cards"] if folded("Školský reproduktor") in folded(card.get("name")) and folded(card.get("list_name")) == "todo"]
                    if len(todo) == 1:
                        text += " | KARTA: " + todo[0]["shortUrl"]
                operations.append(("item", matches[0], "SET", text))
    # Scene labels.
    photo = _exact(state["labels"], PHOTO_LABEL)
    if len(photo) == 1:
        for scene_id in sorted(PHOTO_CONFIRMED):
            if len(grouped.get(scene_id, [])) == 1:
                operations.append(("label", grouped[scene_id][0], photo[0]["id"], PHOTO_LABEL))
    # SET decisions and curated notes.
    for scene_id, texts in SAFE_SET_NOTES.items():
        if len(grouped.get(scene_id, [])) == 1:
            for text in texts:
                operations.append(("item", grouped[scene_id][0], "SET", text))
    # Registry masters for curated physical props.
    for scene_id, names in SAFE_PROP_NOTES.items():
        cards = grouped.get(scene_id, [])
        if len(cards) != 1:
            continue
        for name in names:
            operations.append(("linked_prop", cards[0], name, "REGISTER REKVIZÍT"))
    # Doggy and banner linked continuity.
    dogy = [card for card in state["cards"] if folded(card.get("name")) == folded("Doggyho slúchadlá")]
    continuity_labels = _exact(state["labels"], "Nadväzná rekvizita")
    if len(dogy) == 1:
        rows = build_audit(api)["dogy_headphones"]["confirmed_physical"]
        ids = [row["scene_id"] for row in rows if len(grouped.get(row["scene_id"], [])) == 1]
        for index, scene_id in enumerate(ids):
            text = _scene_item("Doggyho slúchadlá", dogy[0]["shortUrl"], "Doggy ich má pri fyzickej prítomnosti v obraze", ids[index-1] if index else "prvý výskyt", ids[index+1] if index+1 < len(ids) else "ďalší potvrdený obraz neurčený", True)
            operations.append(("item", grouped[scene_id][0], "REKVIZITY", text))
            if len(continuity_labels) == 1:
                operations.append(("label", grouped[scene_id][0], continuity_labels[0]["id"], "Nadväzná rekvizita"))
    banner = [card for card in state["cards"] if folded(card.get("name")) == folded("BANNER NA OTVORENIE BASKETBALOVEJ SEZÓNY")]
    if len(banner) == 1:
        ids = [scene_id for scene_id in BANNER_SCENES if len(grouped.get(scene_id, [])) == 1]
        for index, scene_id in enumerate(ids):
            text = _scene_item("BANNER NA OTVORENIE BASKETBALOVEJ SEZÓNY", banner[0]["shortUrl"], "banner je súčasťou otvorenia basketbalovej sezóny", ids[index-1] if index else "prvý výskyt", ids[index+1] if index+1 < len(ids) else "ďalší potvrdený obraz neurčený", True)
            operations.append(("item", grouped[scene_id][0], "REKVIZITY", text))
            if len(continuity_labels) == 1:
                operations.append(("label", grouped[scene_id][0], continuity_labels[0]["id"], "Nadväzná rekvizita"))
    # 01/53LP requested physical production props.
    if len(grouped.get("01/53LP", [])) == 1:
        for name in SCENE_0153_PROPS:
            operations.append(("linked_prop", grouped["01/53LP"][0], name, "REGISTER REKVIZÍT"))

    selected = operations[start:start + limit]
    writes = 0; changed = []; errors = []
    for op in selected:
        try:
            kind, card, arg1, arg2 = op
            if kind == "label":
                count = _ensure_label_on_card(api, card, arg1)
                writes += count
                if count: changed.append({"card": card["name"], "change": f"label {arg2}"})
            elif kind == "item":
                count, created = _ensure_item(api, card, arg1, arg2)
                writes += count
                if created: changed.append({"card": card["name"], "change": f"{arg1}: {arg2}"})
            else:
                master, count = _ensure_master(api, state, arg1, arg2, "Rekvizita", [(canonical_scene_id(card["name"].split('.')[0]), card["name"], card["shortUrl"])])
                writes += count
                text = _scene_item(arg1, master["shortUrl"], None)
                count, created = _ensure_item(api, card, "REKVIZITY", text)
                writes += count
                if created: changed.append({"card": card["name"], "change": f"REKVIZITY: {arg1}"})
        except Exception as exc:
            errors.append({"card": op[1].get("name"), "error": str(exc)})
    return {
        "status": "content-applied", "operations": len(operations), "start": start,
        "processed": len(selected), "writes": writes, "changed": changed,
        "errors": errors, "remaining": max(0, len(operations) - start - len(selected)),
    }


def _apply_vehicles(api):
    state = load_board(api); audit = build_audit(api)
    target, list_writes = _ensure_list(api, state, "AUTÁ")
    registry_matches = _exact(state["open_lists"], "REGISTER REKVIZÍT")
    if len(registry_matches) != 1:
        raise RuntimeError("REGISTER REKVIZÍT is missing or ambiguous")
    label, label_writes = _ensure_label(api, state, "Auto", "blue")
    writes = list_writes + label_writes; changed = []; errors = []
    # Narrow repair for the just-created generic candidate. It remains an Auto,
    # but without a proven owner/dej identity it belongs in the global register.
    generic_vans = [card for card in state["cards"] if folded(card.get("name")) == folded("DODÁVKA - REKVI")]
    if len(generic_vans) == 1 and folded(generic_vans[0].get("list_name")) == "auta":
        api["trello_put_body"](f"/cards/{generic_vans[0]['id']}", {"idList": registry_matches[0]["id"]})
        writes += 1
        changed.append({"name": generic_vans[0]["name"], "url": generic_vans[0]["shortUrl"],
                        "action": "returned to REGISTER REKVIZÍT; generic identity"})
    for row in audit["vehicles_list"]["confirmed_master_cards"]:
        try:
            cards = [card for card in state["cards"] if card["id"] == row["id"]]
            if len(cards) != 1:
                raise RuntimeError("master disappeared or duplicated")
            card = cards[0]
            if card["idList"] != target["id"]:
                api["trello_put_body"](f"/cards/{card['id']}", {"idList": target["id"]})
                writes += 1
            count = _ensure_label_on_card(api, card, label["id"])
            writes += count
            changed.append({"name": card["name"], "url": card["shortUrl"], "action": "kept/moved in AUTÁ"})
        except Exception as exc:
            errors.append({"name": row["name"], "error": str(exc)})
    return {"status": "vehicles-applied", "writes": writes, "changed": changed, "errors": errors,
            "blocked_groups_untouched": len(audit["vehicles_list"]["blocked_semantic_conflict_groups"])}


def register_routes(app, api):
    @app.route("/api/apply-ck-meeting-semantic-ep01-03", methods=["POST"])
    def apply_ck_meeting_semantic_ep01_03():
        if request.headers.get("X-CK-Semantic-Apply-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "dry-run").strip().casefold()
        try:
            if mode in {"dry-run", "audit"}:
                return jsonify(_plan_summary(api)), 200
            if mode == "bootstrap":
                return jsonify(_apply_bootstrap(api)), 200
            if mode == "content":
                start = max(0, int(request.args.get("start", "0")))
                limit = min(20, max(1, int(request.args.get("limit", "10"))))
                result = _apply_content(api, start, limit)
                return jsonify(result), (200 if not result["errors"] else 207)
            if mode == "vehicles":
                result = _apply_vehicles(api)
                return jsonify(result), (200 if not result["errors"] else 207)
            return jsonify({"error": "mode must be dry-run, audit, bootstrap, content, or vehicles"}), 400
        except Exception as exc:
            app.logger.exception("CK meeting semantic apply failed")
            return jsonify({"status": "failed", "error": f"{type(exc).__name__}: {exc}"}), 502
