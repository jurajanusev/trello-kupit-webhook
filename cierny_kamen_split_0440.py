from __future__ import annotations

import copy
import hashlib

from flask import jsonify, request

from cierny_kamen_all_props_registry import ensure_attachment
from cierny_kamen_prop_markdown_format import exact_named, format_registry_item
from cierny_kamen_reference_all import board_support_data


KEY = "cierny-kamen-split-0440-12aug-5ac9e730"
CARD_0439 = "6a67b0fd060d03b43843c129"
ITEM_ALEX_0213 = "6a6bb5146d01c0ba1cf71309"
ITEM_ALEX_0214 = "6a7750dd2f9edfeba27bb231"
SPACE_URL = "https://trello.com/c/5MZNN6w7"
AUTO_START = "<!-- CIERNY-KAMEN-PROP-REGISTRY-AUTO:START -->"
AUTO_END = "<!-- CIERNY-KAMEN-PROP-REGISTRY-AUTO:END -->"

ACTION_0440_RAW = """Noel zatiahol Kika na nejaké miesto v amfiku, kde ich nikto nevidí. Najskôr to vyzerá tak, že ho chce zbiť, pritlačí ho o zábradlie (múr) a Kiko vyzerá vystrašene. Noel ho však vášnivo pobozká. Kiko je z toho vykoľajený, ale bozk mu opätuje, pretože Noel je hot. Kiko sa po chvíľke odtiahne.

KIKO
Počkaj, počkaj. Teraz už fakt musím. Čaká na mňa kamoška.

Noel ho znovu pobozká, Kiko bozky opätuje.

NOEL
Ja som Noel. Ty?

KIKO
Daj mi mobil.

Noel mu podá svoj mobil. Kiko doň rýchlo napíše svoje meno a číslo a prezvoní sa.

KIKO
Budem čakať.

Kiko mu vráti mobil. Noel sa pozrie na obrazovku a ostane zaskočený.

NOEL
Ty si Keler? Tvoj foter je ten fízel?

KIKO
Je to problém?

NOEL
Nie, ak tebe nevadí, že…

KIKO
…patríš k Vlkom? Bude to naše tajomstvo.

Noel sa usmeje. Ešte raz sa pobozkajú."""

ACTION_0440_MD = """*Noel zatiahol Kika na nejaké miesto v amfiku, kde ich nikto nevidí. Najskôr to vyzerá tak, že ho chce zbiť, pritlačí ho o zábradlie (múr) a Kiko vyzerá vystrašene. Noel ho však vášnivo pobozká. Kiko je z toho vykoľajený, ale bozk mu opätuje, pretože Noel je hot. Kiko sa po chvíľke odtiahne.*

> **KIKO:**
> Počkaj, počkaj. Teraz už fakt musím. Čaká na mňa kamoška.

*Noel ho znovu pobozká, Kiko bozky opätuje.*

> **NOEL:**
> Ja som Noel. Ty?

> **KIKO:**
> Daj mi mobil.

*Noel mu podá svoj mobil. Kiko doň rýchlo napíše svoje meno a číslo a prezvoní sa.*

> **KIKO:**
> Budem čakať.

*Kiko mu vráti mobil. Noel sa pozrie na obrazovku a ostane zaskočený.*

> **NOEL:**
> Ty si Keler? Tvoj foter je ten fízel?

> **KIKO:**
> Je to problém?

> **NOEL:**
> Nie, ak tebe nevadí, že…

> **KIKO:**
> …patríš k Vlkom? Bude to naše tajomstvo.

*Noel sa usmeje. Ešte raz sa pobozkajú.*"""


def split_action_0439(value):
    value = value.replace(
        "PARALELNÉ 4/40. ETX. AMFITEÁTER – ODĽAHLÉ MIESTO, NIGHT 15 "
        "KEVIN, NOEL Kiko sa bozkáva s Noelom ", "", 1,
    )
    start_marker = " (prestrih) Noel zatiahol Kika na nejaké miesto v amfiku"
    end_marker = "(prestrih) Rozhovor v hudobnej miestnosti pokračuje."
    start = value.index(start_marker)
    end = value.index(end_marker, start) + len(end_marker)
    return value[:start] + "*\n\n*Rozhovor v hudobnej miestnosti pokračuje." + value[end:]


def split_action_raw_0439(value):
    value = value.replace(
        "PARALELNÉ 4/40. ETX. AMFITEÁTER – ODĽAHLÉ MIESTO, NIGHT 15 "
        "KEVIN, NOEL Kiko sa bozkáva s Noelom ", "", 1,
    )
    start_marker = " (prestrih) Noel zatiahol Kika na nejaké miesto v amfiku"
    end_marker = "(prestrih) Rozhovor v hudobnej miestnosti pokračuje."
    start = value.index(start_marker)
    end = value.index(end_marker, start) + len(end_marker)
    return value[:start] + " Rozhovor v hudobnej miestnosti pokračuje." + value[end:]


def scene_0440():
    return {
        "scene_id": "04/40", "episode": 4,
        "name": "04/40. ETX. AMFITEÁTER – ODĽAHLÉ MIESTO, NIGHT 15 — KEVIN, NOEL",
        "heading": "ETX. AMFITEÁTER – ODĽAHLÉ MIESTO, NIGHT 15",
        "prepis": "Kiko sa bozkáva s Noelom",
        "location": "AMFITEÁTER – ODĽAHLÉ MIESTO",
        "characters": ["KEVIN", "NOEL"], "characters_raw": "KEVIN, NOEL",
        "action_raw": ACTION_0440_RAW, "action_markdown": ACTION_0440_MD,
        "action_sha256": hashlib.sha256(ACTION_0440_RAW.encode()).hexdigest(),
        "source_pdf": "SC_01_04_ČK_1.7_MK_FINAL.pdf",
        "source_sha256": "ae0cd7c66fd95c9674c6408b07ee6a9dc96c7de1b00ba8b044ab383fb578c94d",
        "order_in_episode": 39, "order": 206,
        "props": [{
            "stable_name": "Noelov osobný mobil",
            "action": "Noel ho podá Kikovi; Kiko doň napíše svoje meno a číslo a prezvoní sa.",
            "source_text": "Noelov osobný mobil — Noel ho podá Kikovi; Kiko doň napíše svoje meno a číslo a prezvoní sa.",
            "registry_key": "noelov osobny mobil", "continuity": False,
        }],
        "set_items": [{
            "stable_name": "AMFITEÁTER – ODĽAHLÉ MIESTO",
            "action": "prostredie obrazu 04/40",
            "source_text": "AMFITEÁTER – ODĽAHLÉ MIESTO — prostredie obrazu 04/40",
            "continuity": False,
        }],
        "labels": [], "questions": [],
    }


def augment_payload(payload):
    result = copy.deepcopy(payload)
    if any(scene["scene_id"] == "04/40" for scene in result["scenes"]):
        return result
    scene39 = next(scene for scene in result["scenes"] if scene["scene_id"] == "04/39")
    scene39["action_raw"] = split_action_raw_0439(scene39["action_raw"])
    scene39["action_markdown"] = split_action_0439(scene39["action_markdown"])
    scene39["action_sha256"] = hashlib.sha256(scene39["action_raw"].encode()).hexdigest()
    scene39["props"] = [
        item for item in scene39["props"]
        if item.get("stable_name") != "Mobil odovzdávaný Kikovi"
        and not (item.get("stable_name") == "Auto / vozidlo" and "vlámala" in item.get("action", ""))
    ]
    index = result["scenes"].index(scene39) + 1
    result["scenes"].insert(index, scene_0440())
    for scene in result["scenes"][index + 1:]:
        scene["order"] = int(scene.get("order", 0)) + 1
        if scene.get("episode") == 4:
            scene["order_in_episode"] = int(scene.get("order_in_episode", 0)) + 1
    return result


def description_0440(mobile_url, space_url, links):
    return f"""## Kiko sa bozkáva s Noelom

### REKVIZITY V KONTEXTE
- **Noelov osobný mobil** — Noel ho podá Kikovi; Kiko doň napíše svoje meno a číslo a prezvoní sa.

### NADVAZNOSŤ

- Bez potvrdenej nadväznosti.

### ODKAZY
- Noelov osobný mobil: {mobile_url}

### KONTINUITA PRIESTORU

- Predchádzajúci: [04/38 – Andy pracuje pre Lauru]({links['04/38']} "‌")
- Nasledujúci: —

### KONTINUITA POSTÁV

- KIKO: ← [04/37 – Noel balí Kika]({links['04/37']} "‌") | → [04/41 – Do domu Kelerovcov sa niekto vlámal]({links['04/41']} "‌")
- NOEL: ← [04/37 – Noel balí Kika]({links['04/37']} "‌") | → —

### RUČNÉ DOPLNENIA

### AKCIA A DIALÓGY
{ACTION_0440_MD}

<!-- CIERNY-KAMEN-SCHEDULE-METADATA:START -->
ČÍSLO OBRAZU: 04/40
ZDROJ: SC_01_04_ČK_1.7_MK_FINAL.pdf
NATÁČACÍ DEŇ: nenaplánované
DÁTUM: nenaplánované
PORADIE: nenaplánované
UNIT: nenaplánované
LOKÁCIA: [AMFITEÁTER – ODĽAHLÉ MIESTO]({space_url})
POSTAVY: KEVIN, NOEL<!-- CIERNY-KAMEN-SCHEDULE-METADATA:END -->"""


def split_desc_0439(value):
    value = value.replace(
        "- **Mobil odovzdávaný Kikovi** — KIKO Daj mi mobil.",
        "- **papiere s notami** — ktoré si na začiatku obrazu ukladá Olasová. - ide o indiferentné noty\n"
        "- **Darčeková škatuľa na sláčik na violončelo**\n"
        "- **nový sláčik na violončelo** — ktoré daruje Alex Olasovej na pamiatku",
        1,
    )
    return split_action_0439(value)


def register_routes(app, api):
    @app.route("/api/cierny-kamen-split-0440", methods=["POST"])
    def split_0440():
        if request.headers.get("X-Split-0440-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "audit").casefold().strip()
        if mode not in {"audit", "dry-run", "apply"}:
            return jsonify({"error": "invalid mode"}), 400
        payload = api["cierny_kamen_import_payload"]()
        state = api["cierny_kamen_import_state"](payload)
        groups = api["cierny_kamen_scene_cards_by_id"](state)
        support = board_support_data(api, state["board"]["id"])
        blockers = []
        if len(groups.get("04/39", [])) != 1 or groups.get("04/39", [None])[0]["id"] != CARD_0439:
            blockers.append("04/39 card mismatch")
        if len(groups.get("04/40", [])) > 1:
            blockers.append("duplicate 04/40 cards")
        if len(groups.get("02/13", [])) != 1 or len(groups.get("02/14", [])) != 1:
            blockers.append("02/13 or 02/14 card mismatch")
        scene_list = exact_named(state["lists"], "SCENÁRE")
        space_cards = [card for card in state["cards"] if card.get("shortUrl") == SPACE_URL and not card.get("closed")]
        mobile_cards = [card for card in state["cards"] if (card.get("name") or "").casefold() == "noelov osobný mobil".casefold()]
        personal_labels = exact_named(state["labels"], "Osobná rekvizita")
        if len(scene_list) != 1 or len(space_cards) != 1 or len(mobile_cards) > 1 or len(personal_labels) != 1:
            blockers.append("target list, space, mobile identity, or label mismatch")
        cards_by_id = {card["id"]: card for card in state["cards"]}
        card39 = cards_by_id.get(CARD_0439)
        prop39 = exact_named(support["checklists"].get(CARD_0439, []), "REKVIZITY")
        props13 = exact_named(support["checklists"].get(groups.get("02/13", [{}])[0].get("id"), []), "REKVIZITY") if groups.get("02/13") else []
        props14 = exact_named(support["checklists"].get(groups.get("02/14", [{}])[0].get("id"), []), "REKVIZITY") if groups.get("02/14") else []
        item13 = [item for cl in props13 for item in cl.get("checkItems", []) if item["id"] == ITEM_ALEX_0213]
        item14 = [item for cl in props14 for item in cl.get("checkItems", []) if item["id"] == ITEM_ALEX_0214]
        if len(prop39) != 1 or len(item13) != 1 or len(item14) != 1:
            blockers.append("required checklist items mismatch")
        links = {sid: groups[sid][0].get("shortUrl") for sid in ("04/37", "04/38", "04/41") if len(groups.get(sid, [])) == 1}
        if len(links) != 3:
            blockers.append("neighbor links missing")
        audit = {
            "status": mode, "writes": 0, "blockers": blockers,
            "counts": {"scene_cards_before": len([k for k,v in groups.items() if len(v)==1]),
                       "04_40_cards": len(groups.get("04/40", [])),
                       "mobile_master_matches": len(mobile_cards)},
            "card_0440": ({
                "card": groups["04/40"][0],
                "checklists": support["checklists"].get(groups["04/40"][0]["id"], []),
                "attachments": support["attachments"].get(groups["04/40"][0]["id"], []),
                "comments": support["comments"].get(groups["04/40"][0]["id"], []),
            } if len(groups.get("04/40", [])) == 1 else None),
            "source": {"pdf": "SC_01_04_ČK_1.7_MK_FINAL.pdf", "pages": [68,69,70],
                       "split_start": "Noel zatiahol Kika...",
                       "split_end": "Noel sa usmeje. Ešte raz sa pobozkajú."},
            "card_0439": {"url": card39.get("shortUrl") if card39 else None,
                          "desc_before": card39.get("desc") if card39 else None,
                          "desc_after": (
                              card39.get("desc") if groups.get("04/40")
                              else split_desc_0439(card39.get("desc"))
                          ) if card39 and not blockers else None},
            "alex_bag": {"02/13": item13, "02/14": item14},
            "planned": {"create_scene": not groups.get("04/40"), "create_mobile_master": not mobile_cards,
                        "create_personal_list": len(exact_named(state["lists"], "NOEL – OS. REKVIZITY")) == 0,
                        "update_0439_desc": True, "update_bag_items": 2},
        }
        if mode != "apply":
            return jsonify(audit), 200 if not blockers else 409
        if blockers:
            return jsonify(audit), 409
        if groups.get("04/40"):
            return jsonify({**audit, "status": "unchanged", "writes": 0}), 200

        writes = 0
        operations = []
        noel_lists = exact_named(state["lists"], "NOEL – OS. REKVIZITY")
        if len(noel_lists) > 1:
            return jsonify({**audit, "error": "duplicate NOEL lists"}), 409
        if noel_lists:
            noel_list = noel_lists[0]
        else:
            noel_list = api["trello_post_body"]("/lists", {"idBoard": state["board"]["id"], "name": "NOEL – OS. REKVIZITY", "pos": "bottom"})
            writes += 1; operations.append({"type": "create_list", "name": noel_list["name"]})
        if mobile_cards:
            mobile = mobile_cards[0]
        else:
            block = f"{AUTO_START}\nKANONICKÝ NÁZOV: Noelov osobný mobil\nALIASY: —\nKATEGÓRIE: Osobná rekvizita\n\n### VÝSKYTY V OBRAZOCH\n- [04/40]({card39['shortUrl']})\n{AUTO_END}"
            mobile = api["trello_post_body"]("/cards", {"idList": noel_list["id"], "name": "Noelov osobný mobil", "desc": block, "pos": "bottom", "idLabels": personal_labels[0]["id"]})
            writes += 1; operations.append({"type": "create_mobile_master", "url": mobile["shortUrl"]})
        desc40 = description_0440(mobile["shortUrl"], SPACE_URL, links)
        pos39 = float(card39.get("pos") or 0); pos41 = float(groups["04/41"][0].get("pos") or pos39 + 32768)
        new40 = api["trello_post_body"]("/cards", {"idList": scene_list[0]["id"], "name": scene_0440()["name"], "desc": desc40, "pos": (pos39 + pos41) / 2})
        writes += 1; operations.append({"type": "create_scene", "url": new40["shortUrl"]})
        checklist_names = ["REKVIZITY", "SET", "INFO Z PORADY", "INFO Z NATÁČANIA", "OTÁZKY NA PORADU"]
        created_cls = {}
        for index, name in enumerate(checklist_names):
            created_cls[name] = api["trello_post_body"](f"/cards/{new40['id']}/checklists", {"name": name, "pos": (index + 1) * 16384})
            writes += 1
        prop_name = format_registry_item("Noelov osobný mobil — Noel ho podá Kikovi; Kiko doň napíše svoje meno a číslo a prezvoní sa. | KARTA: " + mobile["shortUrl"], "Noelov osobný mobil", mobile["shortUrl"])
        api["trello_post_body"](f"/checklists/{created_cls['REKVIZITY']['id']}/checkItems", {"name": prop_name, "pos": "bottom"}); writes += 1
        api["trello_post_body"](f"/checklists/{created_cls['SET']['id']}/checkItems", {"name": "AMFITEÁTER – ODĽAHLÉ MIESTO — prostredie obrazu 04/40 | KARTA: " + SPACE_URL, "pos": "bottom"}); writes += 1
        if ensure_attachment(api, new40, mobile["shortUrl"], "Noelov osobný mobil"): writes += 1
        if ensure_attachment(api, mobile, new40["shortUrl"], "04/40"): writes += 1
        if ensure_attachment(api, new40, SPACE_URL, "AMFITEÁTER – ODĽAHLÉ MIESTO"): writes += 1
        if ensure_attachment(api, space_cards[0], new40["shortUrl"], "04/40"): writes += 1
        api["trello_put_body"](f"/cards/{CARD_0439}", {"desc": split_desc_0439(card39["desc"])}); writes += 1
        bag_url = "https://trello.com/c/QnuL7W0o"
        desired13 = format_registry_item(item13[0]["name"], "Alexova školská taška", bag_url)
        desired14_core = "Alexova školská taška nadv. 2/13 | KARTA: " + bag_url
        desired14 = format_registry_item(desired14_core, "Alexova školská taška", bag_url)
        api["trello_put_body"](f"/cards/{groups['02/13'][0]['id']}/checkItem/{ITEM_ALEX_0213}", {"name": desired13}); writes += 1
        api["trello_put_body"](f"/cards/{groups['02/14'][0]['id']}/checkItem/{ITEM_ALEX_0214}", {"name": desired14}); writes += 1
        operations.extend([{"type":"split_0439_desc"},{"type":"link_bag_0213_0214"}])
        after_state = api["cierny_kamen_import_state"](payload)
        after_groups = api["cierny_kamen_scene_cards_by_id"](after_state)
        return jsonify({"status":"applied","writes":writes,"operations":operations,
                        "audit":{"scene_cards_after":len([k for k,v in after_groups.items() if len(v)==1]),
                                 "04_40_cards":len(after_groups.get("04/40",[])),
                                 "duplicates":{k:len(v) for k,v in after_groups.items() if len(v)>1},
                                 "new_url":new40["shortUrl"]}}), 200
