from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).parent
PAYLOAD_PATH = ROOT / "cierny_kamen_pdf_payload.json"
OUTPUT_PATH = ROOT / "cierny_kamen_prop_identity_map.json"

# This is a reviewed scene/item map, not a classifier. Keys identify the exact
# occurrence in the immutable PDF payload: "<scene id>#<zero based prop index>".
MOBILES = {
    "01/16": "Betin osobný mobil", "01/23": "Alexov osobný mobil",
    "01/30": "Alexov osobný mobil", "01/32FLASH": "Alexov osobný mobil",
    "01/33": "Sárin mobil s hudbou na konkurz", "01/52": "Alicin reportérsky mobil",
    "02/08": "Alexov osobný mobil", "02/27": "Alicin mobil s diktafónom",
    "03/07": "Betin osobný mobil", "03/10": "Mobily Bety a Veroniky",
    "03/13": "Fifov osobný mobil", "03/15": "Mobily študentov so slutshamingovou fotkou",
    "03/16": "Veronikin osobný mobil", "03/20": "Veronikin osobný mobil",
    "03/22": "Betin osobný mobil", "03/27": "Kikov osobný mobil",
    "03/28": "Mobil použitý na otvorenie tajného kanála",
    "03/44": "Veronikin osobný mobil", "03/46": "Veronikin osobný mobil so Scrollom",
    "03/48LP": "Čmelského mobil s tajným kanálom", "03/50": "Sárin osobný mobil",
    "03/51": "Betin osobný mobil", "04/01LP": "Dogyho osobný mobil",
    "04/09": "Dogyho mobil s oznámením mesta", "04/15": "Sárin osobný mobil",
    "04/16": "Dogyho osobný mobil", "04/18": "Sárin mobil s fotografiou Laury a Andyho",
    "04/21": "Betin mobil so screenshotom parte", "04/24": "Betin mobil s fotografiou občianskeho preukazu",
    "04/35": "Laurin osobný mobil", "04/39": "Mobil odovzdávaný Kikovi",
    "04/47LP": "Betin osobný mobil", "05/09": "Lein osobný mobil",
    "05/11": "Alexov osobný mobil", "05/21": "Gonzov osobný mobil",
    "05/23": "Laurin osobný mobil", "05/26": "Ivanov mobil s videom malej Sofie",
    "06/03": "Betin osobný mobil", "06/04": "Dogyho mobil na fotografovanie Alicinho účtu",
    "06/08": "Betin mobil s fotografiami Alicinho účtu",
    "06/17": "Mobily Beky a Mery so sociálnymi sieťami",
    "06/26": "Veronikin osobný mobil", "06/28": "Betin osobný mobil",
    "06/42LP": "Dogyho mobil s fotografiami obsahu Sofiinho auta",
    "06/46": "Mobily basketbalistov v hľadisku",
}

CARS = {
    "01/02LP": "Auto Jakuba a Sáry", "01/03LP": "Auto Jakuba a Sáry",
    "01/04LP": "Auto Jakuba a Sáry", "01/09": "Policajné auto pri rieke",
    "01/13": "Čierna limuzína Laury a Veroniky", "01/15": "Auto, ktorým prišiel Alex",
    "01/27FLASH": "Olasovej auto", "01/32FLASH": "Olasovej auto",
    "01/38": "Taxík s Laurinou stratenou taškou", "01/52": "Policajné auto pri náleze Jakubovho tela",
    "02/12": "Ivanovo pripravené auto", "03/05FLASH": "Auto Jakuba a Sáry",
    "03/34": "Taxík ponúkaný Laure", "03/54FLASH": "Auto odstavené pri rieke",
    "03/55LP": "Olasovej auto", "04/23": "Olasovej auto",
    "04/39": "Olasovej auto", "04/41": "Kelerovo auto",
    "04/48": "Olasovej auto", "05/16": "Ivanovo auto",
    "06/25LP": "Auto pripravené na Sofiin odchod", "06/35": "Auto z Betinej spomienky",
    "06/36": "Auto spomenuté Bety", "06/42LP": "Sofiino auto",
    "06/46": "Sofiino auto", "06/50": "Kelerovo civilné auto",
}

NOTEBOOKS = {
    "01/12LP": "Dogyho spisovateľský notebook", "01/22": "Meryin DJ laptop",
    "01/27FLASH": "Dogyho spisovateľský notebook", "01/49": "Dogyho spisovateľský notebook",
    "01/52": "Dogyho spisovateľský notebook", "02/56": "Notebook Klaudie a Oskara na sledovanie podcastu",
    "03/01LP": "Dogyho spisovateľský notebook", "03/27": "Betin notebook na pátranie v DCčku",
    "04/14": "Betin notebook na pátranie po Olasovej", "05/14": "Tomiho výkonný laptop",
    "05/25": "Ivanov osobný laptop", "05/26": "Ivanov osobný laptop",
    "05/27": "Sárin laptop s Jakubovými fotografiami", "06/02": "Dogyho spisovateľský notebook",
    "06/04": "Alicin MacBook s internet bankingom",
}

PHOTOS = {
    "01/12LP": "Sárin fotoalbum s Jakubovými fotografiami",
    "02/19LP": "Spomienkové fotografie pri Jakubovej skrinke",
    "03/15": "Slutshamingová fotografia Veroniky", "03/16": "Slutshamingová fotografia Veroniky",
    "03/20": "Slutshamingová fotografia Veroniky", "03/22": "Slutshamingové fotografie obetí",
    "03/27": "Slutshamingová fotografia Veroniky", "03/28": "Tímová selfie tanečnej skupiny",
    "03/47LP": "Fotografia Bety a Alexa v Betinej skrinke",
    "04/06LP": "Zarámovaná fotografia Bety a Alexa z detstva",
    "04/18": "Sárina fotografia Laury a Andyho", "04/19": "Sárina fotografia Laury a Andyho",
    "04/20": "Zarámované fotografie primátorky Kamenickej",
    "04/23": "Fotografia Olasovej na falošnom občianskom preukaze",
    "04/24": "Fotografia Olasovej na falošnom občianskom preukaze",
    "04/28": "Fotografie osôb na Kelerovej vyšetrovacej nástenke",
    "04/42": "Odstránené fotografie z Kelerovej vyšetrovacej nástenky",
    "05/05": "Fotografie podozrivých na Kelerovej vyšetrovacej nástenke",
    "05/13": "Smútočný portrét Jakuba vo vile Révayovcov",
    "05/14": "Fotografia Jakuba a Sofie", "05/17": "Slutshamingová fotografia Sofie",
    "05/27": "Rodinné fotografie Révayovcov na Sárinom tablete",
    "05/45LP": "Smútočný portrét Jakuba pri urne",
    "05/47LP": "Ukradnuté fotografie z Jakubovej pitvy",
    "06/08": "Fotografie z Alicinho internet bankingu",
    "06/46": "Dogyho fotografie dôkazov zo Sofiinho auta",
}

FOOD = {
    "01/17": "Zabalené jedlo pre Veroniku", "01/34": "Alexova fľaša s vodou",
    "01/40": "Nealkoholické občerstvenie na školskej párty",
    "01/44": "Drinkové poháre na párty u Sáry", "02/11": "Lukášove rýchle raňajky",
    "02/34": "Betina fľaša s vodou", "02/35": "Jedlo od Fefeho pre Alexa",
    "02/38": "Jedlo od Fefeho pre Lukáša a Alexa", "02/54": "Poháre Bety a Veroniky na prípitok",
    "03/34": "Laurin pohár na víno", "03/39": "Olasovej drink z amfiteátra",
    "03/42": "Fifov drink s uvoľňovačom", "04/10": "Drinkové poháre hostí u Fefeho",
    "04/19": "Laurin pohár vína", "05/08": "Lukášova objednávka jedla od Fefeho",
    "05/37": "Ivanov pohár tvrdého alkoholu", "06/04": "Raňajkový čaj a lievance u Bety",
}

BAGS = {
    "01/17": "Taška s jedlom pre Veroniku", "01/18": "Alexov školský batoh",
    "01/19": "Betina školská taška", "01/30": "Alexova školská taška",
    "01/38": "Laurine nákupné tašky", "02/13": "Alexova školská taška",
    "02/34": "Betin tanečný batoh", "02/35": "Taška s jedlom pre Alexa",
    "02/53": "Tanečné tašky skupiny Eclipse", "03/11": "Dogyho školský batoh",
    "03/15": "Veronikin školský batoh", "04/23": "Betin batoh s planžetou",
    "04/26": "Laurina kožená taška s iniciálami L.S.", "06/12": "Veronikina papierová taška s jedlom",
    "06/15": "Laurina osobná taška",
}

MONEY = {
    "01/18": "Alexova výplata zo stavby", "02/27": "Bankovky v Alicinej obálke pre patológa",
    "04/10": "Tržba za drinky u Fefeho", "04/20": "Financie na záchranu amfiteátra",
    "04/22": "Pouličné zárobky Olasovej z hrania", "04/26": "Laurin úplatok pre primátorku",
    "04/37": "Kikove vysypané mince", "04/38": "Andyho hotovostná odmena od Laury",
    "05/08": "Laurina platba za objednávku", "05/28": "Fefeho dlh Laure",
}

DOCUMENTS = {
    "01/49": "Dogyho rozpísaný román", "04/28": "Kelerove vyšetrovacie spisy a papiere",
    "04/42": "Prázdny spis k vražde Jakuba", "05/05": "Jakubov vyšetrovací spis",
    "06/33": "Projektové dokumenty s Veronikiným sfalšovaným podpisom",
}

OTHER_NAMES = {
    ("Bunda", "02/02FLASH"): "Jakubova klubová bunda s číslom 9",
    ("Bunda", "02/15"): "Alexova odložená bunda",
    ("Bunda", "04/50"): "Andyho kožená bunda",
    ("Bunda", "05/36"): "Bundy a kabáty hostí na kare",
    ("Bunda", "06/41LP"): "Jakubova klubová bunda s číslom 9",
    ("Bunda", "06/42LP"): "Jakubova klubová bunda s číslom 9",
    ("Bunda", "06/46"): "Fotografia Jakubovej klubovej bundy s číslom 9",
    ("Dokumenty / zmluva / spis", "01/49"): "Dogyho rozpísaný román",
    ("Kamera", "02/55"): "Alicina streamovacia kamera",
    ("Kvety", "02/19LP"): "Spomienkové kvety pri Jakubovej skrinke",
    ("Kvety", "04/08"): "Alexova kytica pre Olasovú",
    ("Kvety", "05/13"): "Smútočná kvetinová výzdoba okolo Jakubovej fotografie",
    ("Kufor", "06/24LP"): "Sofiin cestovný kufor",
    ("Kufor", "06/25LP"): "Sofiin cestovný kufor",
    ("Kufor", "06/42LP"): "Batožinový priestor Sofiinho auta",
    ("Obálka", "01/18"): "Obálka s Alexovou výplatou zo stavby",
    ("Obálka", "02/27"): "Alicina obálka s úplatkom pre patológa",
    ("Obálka", "04/38"): "Obálka s Andyho odmenou od Laury",
    ("Plyšová hračka", "02/19LP"): "Spomienkové plyšové hračky pri Jakubovej skrinke",
    ("Slúchadlá", "01/22"): "Meryine DJ slúchadlá",
    ("Diktafón", "02/27"): "Diktafón v Alicinom mobile",
    ("Kľúče", "03/44"): "Kľúče od pút použitých na Fifa",
}

FALSE_POSITIVES = {
    ("Kamera", "02/03FLASH"), ("Kamera", "03/47LP"), ("Kamera", "06/03"),
    ("Kľúče", "06/46"), ("Dokumenty / zmluva / spis", "01/49"),
    ("Kvety", "06/25LP"), ("Alexova gitara", "01/17"),
    ("Alexova gitara", "05/20"), ("Alexova gitara", "06/43"),
    ("Medvedia lampička", "06/02"), ("Pištoľ / zbraň", "01/32FLASH"),
    ("Pištoľ / zbraň", "04/24"), ("Pištoľ / zbraň", "04/27"),
    ("Pištoľ / zbraň", "04/29"), ("Peniaze / bankovky", "04/20"),
    ("Peniaze / bankovky", "04/22"), ("Peniaze / bankovky", "05/28"),
    ("Fotografie / fotoalbum", "04/19"), ("Fotografie / fotoalbum", "05/17"),
    ("Auto / vozidlo", "02/12"), ("Auto / vozidlo", "03/34"),
    ("Auto / vozidlo", "04/39"), ("Auto / vozidlo", "06/25LP"),
    ("Auto / vozidlo", "06/35"), ("Auto / vozidlo", "06/36"),
    ("Auto / vozidlo", "06/46"),
    ("Betin denník", "04/31"), ("Betin denník", "04/39"),
    ("Betin denník", "04/45"), ("Fotografie / fotoalbum", "04/42"),
}

CONTINUITY = {
    ("Auto / vozidlo", "01/02LP"): "auto-jakuba-a-sary",
    ("Auto / vozidlo", "01/03LP"): "auto-jakuba-a-sary",
    ("Auto / vozidlo", "01/04LP"): "auto-jakuba-a-sary",
    ("Auto / vozidlo", "01/27FLASH"): "olasovej-auto",
    ("Auto / vozidlo", "01/32FLASH"): "olasovej-auto",
    ("Auto / vozidlo", "03/55LP"): "olasovej-auto",
    ("Auto / vozidlo", "04/23"): "olasovej-auto",
    ("Auto / vozidlo", "04/48"): "olasovej-auto",
    ("Sofiino auto", "06/41LP"): "sofiino-auto",
    ("Sofiino auto", "06/42LP"): "sofiino-auto",
    ("Sofiino auto", "06/50"): "sofiino-auto",
    ("Bunda", "02/02FLASH"): "jakubova-bunda-9",
    ("Bunda", "06/41LP"): "jakubova-bunda-9",
    ("Bunda", "06/42LP"): "jakubova-bunda-9",
    ("Alexova gitara", "01/39"): "alexova-stara-gitara",
    ("Alexova gitara", "02/28"): "alexova-stara-gitara",
    ("Alexova gitara", "03/19"): "alexova-stara-gitara",
    ("Alexova gitara", "03/25"): "alexova-stara-gitara",
    ("Alexova gitara", "03/32"): "alexova-stara-gitara",
    ("Alexova gitara", "03/45"): "alexova-gitara-od-lukasa",
    ("Alexova gitara", "04/44"): "alexova-gitara-od-lukasa",
    ("Alexova gitara", "05/15"): "alexova-gitara-od-lukasa",
    ("Alexova gitara", "05/44LP"): "alexova-gitara-od-lukasa",
    ("Alexova gitara", "06/13"): "alexova-gitara-od-lukasa",
    ("Alexova gitara", "06/16"): "alexova-gitara-od-lukasa",
    ("Alexova gitara", "06/27"): "alexova-gitara-od-lukasa",
    ("Alexova gitara", "06/47"): "alexova-gitara-od-lukasa",
    ("Betin denník", "04/06LP"): "betin-povodny-dennik",
    ("Betin denník", "04/14"): "betin-povodny-dennik",
    ("Denník", "04/47LP"): "betin-novy-dennik",
    ("Betin denník", "06/03"): "betin-novy-dennik",
    ("Denník", "06/36"): "betin-novy-dennik",
    ("Medvedia lampička", "06/01FLASH"): "betina-medvedia-lampicka",
    ("Medvedia lampička", "06/03"): "betina-medvedia-lampicka",
    ("Pištoľ / zbraň", "04/23"): "olasovej-pistol",
    ("Pištoľ / zbraň", "04/30"): "olasovej-pistol",
    ("Pištoľ / zbraň", "04/31"): "olasovej-pistol",
}


def contextual_name(old: str, scene: dict, action: str) -> str:
    sid = scene["scene_id"]
    if old == "Mobilný telefón": return MOBILES[sid]
    if old == "Auto / vozidlo": return CARS[sid]
    if old == "Notebook / laptop": return NOTEBOOKS[sid]
    if old == "Fotografie / fotoalbum": return PHOTOS[sid]
    if old == "Jedlo / nápoj": return FOOD[sid]
    if old == "Taška / batoh": return BAGS[sid]
    if old == "Peniaze / bankovky": return MONEY[sid]
    if old == "Dokumenty / zmluva / spis": return DOCUMENTS[sid]
    if (old, sid) in OTHER_NAMES: return OTHER_NAMES[(old, sid)]
    if old == "Pištoľ / zbraň": return "Olasovej pištoľ"
    if old == "Blister s liekmi / Ritalin":
        return "Betin blister s Ritalinom od Alice" if sid == "01/19" else "Poloprázdny blister s Ritalinom v Betinej skrinke"
    if old in {"Betin denník", "Denník"}:
        return "Betin nový denník" if sid in {"04/47LP", "06/03", "06/36"} else "Betin pôvodný denník"
    if old == "Alexova gitara":
        return "Alexova stará gitara" if sid in {"01/39", "02/28", "03/19", "03/25", "03/32"} else "Alexova gitara od Lukáša"
    if old == "Medvedia lampička": return "Betina medvedia lampička od Sofie"
    if old == "Sofiino auto": return "Sofiino auto"
    raise KeyError(f"Uncurated identity {sid}: {old}: {action}")


def main() -> None:
    payload = json.loads(PAYLOAD_PATH.read_text(encoding="utf-8"))
    records = []
    for scene in payload["scenes"]:
        for index, item in enumerate(scene["props"]):
            old = item["stable_name"]
            sid = scene["scene_id"]
            included = (old, sid) not in FALSE_POSITIVES
            stable = (
                f"Vyradený false-positive: {old}"
                if not included
                else contextual_name(old, scene, item["action"])
            )
            group = CONTINUITY.get((old, sid)) if included else None
            question = None
            if (old, sid) in {
                ("Mobilný telefón", "03/28"), ("Mobilný telefón", "04/39"),
                ("Blister s liekmi / Ritalin", "01/19"),
                ("Blister s liekmi / Ritalin", "03/47LP"),
            }:
                question = (
                    (
                        f"{sid}: potvrdiť, či ide o ten istý fyzický blister "
                        "Ritalinu ako v druhom výskyte 01/19 / 03/47LP; "
                        "dovtedy sú vedené oddelene bez nadväznosti."
                    )
                    if old == "Blister s liekmi / Ritalin"
                    else (
                        f"{sid}: potvrdiť vlastníka alebo fyzickú totožnosť "
                        f"rekvizity „{stable}“; dovtedy je bez nadväznosti."
                    )
                )
                group = None
            evidence_kind = "physical" if included else (
                "camera_direction" if old == "Kamera" else "dialogue_or_reference"
            )
            records.append({
                "record_id": f"{sid}#{index}",
                "scene_id": sid,
                "source_pdf": scene["source_pdf"],
                "source_evidence": item["action"],
                "original_stable_name": old,
                "include": included,
                "stable_name": stable,
                "physical_presence": included,
                "evidence_kind": evidence_kind,
                "continuity_group": group,
                "action": item["action"],
                "current_state": item["action"],
                "previous": None,
                "next": None,
                "ambiguity_question": question,
            })

    by_group = {}
    for record in records:
        if record["continuity_group"]:
            by_group.setdefault(record["continuity_group"], []).append(record)
    order = {s["scene_id"]: (s["episode"], s["order_in_episode"]) for s in payload["scenes"]}
    for group_records in by_group.values():
        group_records.sort(key=lambda r: order[r["scene_id"]])
        for index, record in enumerate(group_records):
            record["previous"] = (
                "prvý výskyt" if index == 0
                else f"{group_records[index - 1]['scene_id']}: {group_records[index - 1]['current_state']}"
            )
            record["next"] = (
                "ďalší potvrdený obraz neurčený" if index == len(group_records) - 1
                else f"{group_records[index + 1]['scene_id']}: {group_records[index + 1]['current_state']}"
            )
    output = {
        "project": "Čierny Kameň",
        "source": "explicit human-reviewed identity map for six final PDFs",
        "reviewed_current_items": len(records),
        "records": records,
    }
    OUTPUT_PATH.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "reviewed": len(records),
        "included": sum(r["include"] for r in records),
        "excluded_false_positive": sum(not r["include"] for r in records),
        "continuity_occurrences": sum(bool(r["continuity_group"]) for r in records),
        "continuity_groups": len(by_group),
        "questions": sum(bool(r["ambiguity_question"]) for r in records),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
