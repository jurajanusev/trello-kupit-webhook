from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE_MAP = ROOT / "cierny_kamen_prop_identity_map.json"
OUTPUT = ROOT / "cierny_kamen_all_props_registry_map.json"


def folded(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", value).strip().casefold()


def identity_core(value: str) -> str:
    value = re.sub(
        r"\s*\|\s*KARTA:\s*https://trello\.com/c/[A-Za-z0-9]+\s*$",
        "", value or "", flags=re.IGNORECASE,
    ).strip()
    value = re.sub(r"^(?:<[^>]+>\s*|↳\s*)", "", value).strip()
    return re.split(r"\s+—\s+", value, maxsplit=1)[0].strip()


# These mappings were reviewed item-by-item against the current board and the
# six authoritative PDFs.  They intentionally use Trello check-item IDs; a new
# or changed item cannot be classified by a broad keyword rule.
MANUAL_ITEMS = {
    "6a71945fbc40caec67ceb03a": ("Čln Jakuba a Sáry", (), None),
    "6a7194669299d97a3395d3f4": ("Veslá v člne Jakuba a Sáry", (), None),
    "6a719625fdc7c5f40f736f11": (
        "Výbava Matejovej skupiny na kurz prežitia", (), None,
    ),
    "6a71965dfaec94d790c9ceae": (
        "Policajný čln pátracieho tímu", ("Auto",), None,
    ),
    "6a719865853d630a4b816323": (
        "Policajné pásky na brehu rieky", (), None,
    ),
    "6a719875a0129510eedba095": (
        "Výbava Alice a Ivana ako miestnych novinárov", (), None,
    ),
    "6a7198bef4efd47a99107f28": (
        "Kelerov notes pri pátraní — 01/09", ("Dokument",),
        "01/09 — Upresniť konkrétny typ a vzhľad notesu pre Kelera; "
        "scenár ho explicitne neuvádza.",
    ),
    "6a719943ae45a59dca37e89d": (
        "Neidentifikovaný policajný maják — 01/09", (),
        "01/09 — Upresniť, či ide o maják policajného auta alebo člna.",
    ),
    "6a71998e8737ac1319f5f5d8": (
        "Dogyho spisovateľský notebook", ("Osobná rekvizita",), None,
    ),
    "6a719b1394c726c5945694fd": (
        "Sárina šatka — 01/11FLASH", ("Osobná rekvizita",),
        "01/11FLASH — Potvrdiť, v ktorých obrazoch 01/02LP–01/06LP je "
        "Sárina šatka fyzicky viditeľná ako rovnaký konkrétny kus.",
    ),
    "6a71b12dd19c73c066b975de": (
        "Neidentifikované kufre Laury a Veroniky — 01/13",
        ("Osobná rekvizita",),
        "01/13 — Potvrdiť počet a fyzickú prítomnosť kufrov a ich väzbu "
        "na obraz 01/14.",
    ),
    "6a71b14b3bb3ecb82450baa3": (
        "Neidentifikované kufre Laury a Veroniky — 01/14",
        ("Osobná rekvizita",),
        "01/14 — Potvrdiť počet a totožnosť kufrov voči obrazu 01/13.",
    ),
    "6a71b4e68238aa681a30a4f7": (
        "Magnetka „I love Barcelona“ pre Kika", ("Osobná rekvizita",), None,
    ),
    "6a71b6331158d41e172d4a08": (
        "Fefeho farebné limonády pre Bety a Alexa", (), None,
    ),
    "6a71b6b07593f469c6b731b4": (
        "Dva burgre v objednávke Veroniky", (), None,
    ),
    "6a71b6f7a303c93c2f504ce4": (
        "Taška na objednávku Veroniky", ("Osobná rekvizita",), None,
    ),
    "6a71b7642006c9e606a0ad71": (
        "Neidentifikované občerstvenie komparzu — 01/17", (),
        "01/17 — Upresniť konkrétne pitie, jedlo a počet kusov pre komparz.",
    ),
}


# Generated companion check-items are paired explicitly with the reviewed raw
# check-item above.  Both remain untouched and point to the same master card.
COMPANION_TO_RAW = {
    "6a724179c4d0c0e591337b35": "6a71945fbc40caec67ceb03a",
    "6a7241798298ee69cc46799b": "6a7194669299d97a3395d3f4",
    "6a72417a8c187648b5ad35b7": "6a719625fdc7c5f40f736f11",
    "6a72417a4a91652a6b79356b": "6a71965dfaec94d790c9ceae",
    "6a725c71459d8f609d3b5c06": None,
    "6a72417f88957031a3bd9281": "6a719865853d630a4b816323",
    "6a72417f04304547a5c92eb4": "6a719875a0129510eedba095",
    "6a725cb48dbbec5ad53dcd55": "6a719943ae45a59dca37e89d",
    "6a72418039448d6f98d44d87": "6a71998e8737ac1319f5f5d8",
    "6a7241812a7a007f2fcae71b": "6a719b1394c726c5945694fd",
    "6a71fd14acebab2328107900": "6a71b4e68238aa681a30a4f7",
    "6a72420844e9b860e8b100fe": "6a71b6331158d41e172d4a08",
    "6a7242096207dc6a9f0f2b23": "6a71b6b07593f469c6b731b4",
    "6a724209af99c3e54a433f8f": "6a71b6f7a303c93c2f504ce4",
}


COMPANION_OVERRIDES = {
    "6a725c71459d8f609d3b5c06": (
        "Potápačská výstroj policajného pátracieho tímu", (), None,
    ),
    "6a725cbff7564fde949d1330": (
        "Kikovo auto", ("Auto", "Osobná rekvizita"), None,
    ),
}


# Source taxonomy is explicit data from the reviewed identity map, not a text
# keyword classifier.  Per-identity overrides below handle Screen semantics.
SOURCE_CATEGORY_BY_TYPE = {
    "Auto / vozidlo": ("Auto",),
    "Sofiino auto": ("Auto", "Osobná rekvizita"),
    "Mobilný telefón": ("Osobná rekvizita",),
    "Notebook / laptop": ("Osobná rekvizita",),
    "Taška / batoh": ("Osobná rekvizita",),
    "Kľúče": ("Osobná rekvizita",),
    "Pištoľ / zbraň": ("Osobná rekvizita",),
    "Slúchadlá": ("Osobná rekvizita",),
    "Alexova gitara": ("Osobná rekvizita",),
    "Betin denník": ("Osobná rekvizita", "Dokument"),
    "Denník": ("Osobná rekvizita", "Dokument"),
    "Dokumenty / zmluva / spis": ("Dokument",),
    "Fotografie / fotoalbum": ("Dokument",),
}


SCREEN_IDENTITIES = {
    "Diktafón v Alicinom mobile",
    "Dogyho fotografie dôkazov zo Sofiinho auta",
    "Dogyho mobil s oznámením mesta",
    "Fotografia Jakubovej klubovej bundy s číslom 9",
    "Fotografia Olasovej na falošnom občianskom preukaze",
    "Fotografie z Alicinho internet bankingu",
    "Ivanov mobil s videom malej Sofie",
    "Rodinné fotografie Révayovcov na Sárinom tablete",
    "Slutshamingová fotografia Veroniky",
    "Slutshamingové fotografie obetí",
    "Sárina fotografia Laury a Andyho",
    "Tímová selfie tanečnej skupiny",
}


CONFLICT_ITEMS = {
    "6a6b93696e3a87e94cd1015a": (
        "Položka opisuje iba dialógovú zmienku o zbrani; autoritatívny "
        "identity audit nepotvrdil fyzickú prítomnosť rekvizity v 01/32FLASH."
    ),
}


def categories_for_source(record: dict) -> tuple[str, ...]:
    categories = set(SOURCE_CATEGORY_BY_TYPE.get(
        record["original_stable_name"], (),
    ))
    if record["stable_name"] in SCREEN_IDENTITIES:
        categories.add("Screen")
    if record.get("continuity_group"):
        categories.add("Nadväzná rekvizita")
    return tuple(sorted(categories))


def build(audit: dict, source: dict) -> dict:
    included_by_scene = defaultdict(list)
    for record in source["records"]:
        if record["include"]:
            included_by_scene[record["scene_id"]].append(record)

    rows = []
    unmatched = []
    for item in audit["prop_items"]:
        item_id = item["item_id"]
        original = item["name"]
        stable_name = None
        categories = ()
        question = None
        evidence = None

        if item_id in MANUAL_ITEMS:
            stable_name, categories, question = MANUAL_ITEMS[item_id]
            evidence = "explicit_manual_item_map"
        elif item_id in COMPANION_OVERRIDES:
            stable_name, categories, question = COMPANION_OVERRIDES[item_id]
            evidence = "explicit_companion_map"
        elif item_id in COMPANION_TO_RAW:
            raw_id = COMPANION_TO_RAW[item_id]
            stable_name, categories, question = MANUAL_ITEMS[raw_id]
            evidence = f"explicit_companion_of:{raw_id}"
        elif len(item["linked_cards"]) == 1:
            stable_name = item["linked_cards"][0]["name"]
            evidence = "existing_registry_url"
            candidates = [
                record for record in included_by_scene[item["scene_id"]]
                if folded(record["stable_name"]) == folded(stable_name)
            ]
            if candidates:
                categories = categories_for_source(candidates[0])
            if original.lstrip().startswith("<n>"):
                categories = tuple(sorted(set(categories) | {
                    "Nadväzná rekvizita",
                }))
        else:
            core = folded(identity_core(original))
            candidates = [
                record for record in included_by_scene[item["scene_id"]]
                if core == folded(record["stable_name"])
            ]
            if len(candidates) == 1:
                stable_name = candidates[0]["stable_name"]
                categories = categories_for_source(candidates[0])
                evidence = f"source_record:{candidates[0]['record_id']}"
                question = candidates[0].get("ambiguity_question")
            elif len(candidates) > 1 and len({
                candidate["stable_name"] for candidate in candidates
            }) == 1:
                stable_name = candidates[0]["stable_name"]
                categories = categories_for_source(candidates[0])
                evidence = "source_records:" + ",".join(
                    candidate["record_id"] for candidate in candidates
                )

        if stable_name is None:
            unmatched.append({
                "scene_id": item["scene_id"], "item_id": item_id,
                "name": original,
            })
            stable_name = f"Neidentifikovaná rekvizita — {item['scene_id']} — {item_id[-6:]}"
            question = (
                f"{item['scene_id']} — Určiť stabilnú identitu rekvizity „"
                f"{identity_core(original)}“; existujúce údaje ju nepotvrdzujú."
            )
            evidence = "safe_scene_specific_fallback"

        rows.append({
            "scene_id": item["scene_id"],
            "scene_url": item["scene_url"],
            "item_id": item_id,
            "checklist_id": item["checklist_id"],
            "original_name": original,
            "original_name_sha256": hashlib.sha256(
                original.encode("utf-8")
            ).hexdigest(),
            "stable_name": stable_name,
            "categories": list(categories),
            "evidence": evidence,
            "existing_registry_url": (
                item["linked_cards"][0]["url"]
                if len(item["linked_cards"]) == 1 else None
            ),
            "ambiguity_question": question,
            "conflict": CONFLICT_ITEMS.get(item_id),
        })

    identities = defaultdict(list)
    for row in rows:
        identities[row["stable_name"]].append(row)
    return {
        "project": "Čierny Kameň",
        "board_ref": "CzuD55PR",
        "source": "current Trello read-only audit plus six-PDF identity map",
        "records": rows,
        "stats": {
            "records": len(rows),
            "unique_identities": len(identities),
            "unmatched_safe_fallbacks": len(unmatched),
            "ambiguities": sum(bool(row["ambiguity_question"]) for row in rows),
            "conflicts": sum(bool(row["conflict"]) for row in rows),
        },
        "unmatched": unmatched,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audit", type=Path)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    audit = json.loads(args.audit.read_text(encoding="utf-8-sig"))
    source = json.loads(SOURCE_MAP.read_text(encoding="utf-8"))
    result = build(audit, source)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result["stats"], ensure_ascii=False))
    for row in result["unmatched"]:
        print(json.dumps(row, ensure_ascii=False))


if __name__ == "__main__":
    main()
