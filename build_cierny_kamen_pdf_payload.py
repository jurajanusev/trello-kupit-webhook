from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pdfplumber


PDF_GLOBS = {
    1: "SC_01_01_*2.5_SG_KC_FINAL.pdf",
    2: "SC_01_02_*1.5_NJ_FINAL (1).pdf",
    3: "SC_01_03_*1.8_MV_FINAL.pdf",
    4: "SC_01_04_*1.7_MK_FINAL.pdf",
    5: "SC_01_05_*1.6_NJ_FINAL.pdf",
    6: "SC_01_06_*1.6_MV_KC_FINAL.pdf",
}
EXPECTED_EPISODE_COUNTS = {1: 52, 2: 60, 3: 55, 4: 49, 5: 45, 6: 52}

HEADING_RE = re.compile(
    r"^(?P<episode>\d+)\s*/\s*(?P<number>\d+)(?P<suffix>[A-Z]*)\.?\s*"
    r"(?P<heading>(?:INT|EXT)\..*)$",
    re.I,
)
UPPER_RE = re.compile(r"[A-ZÁÄČĎÉÍĹĽŇÓÔŔŠŤÚÝŽ]")


@dataclass
class PdfLine:
    page: int
    top: float
    x: float
    text: str


def folded(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    normalized = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    ).casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def is_upper_line(value: str) -> bool:
    letters = [character for character in value if character.isalpha()]
    return bool(letters) and all(
        not character.islower() for character in letters
    )


def normalized_scene_id(episode: str, number: str, suffix: str) -> str:
    return f"{int(episode):02d}/{int(number):02d}{suffix.upper()}"


def line_groups(page, page_index: int) -> list[PdfLine]:
    words = page.extract_words(use_text_flow=True, keep_blank_chars=False)
    groups: dict[float, list[dict]] = defaultdict(list)
    for word in words:
        groups[round(float(word["top"]), 1)].append(word)
    result = []
    for top, entries in sorted(groups.items()):
        ordered = sorted(entries, key=lambda entry: float(entry["x0"]))
        result.append(PdfLine(
            page=page_index,
            top=top,
            x=min(float(entry["x0"]) for entry in ordered),
            text=" ".join(entry["text"] for entry in ordered).strip(),
        ))
    return result


def clean_lines(lines: list[PdfLine]) -> list[PdfLine]:
    return [
        line
        for line in lines
        if line.text
        and not (line.top > 760 and re.fullmatch(r"\d+", line.text))
    ]


def locate_authoritative_pdf(root: Path, episode: int) -> Path:
    matches = sorted(root.glob(PDF_GLOBS[episode]))
    if len(matches) != 1:
        raise ValueError(
            f"episode {episode}: expected one PDF matching "
            f"{PDF_GLOBS[episode]!r}, found {[item.name for item in matches]}"
        )
    return matches[0]


def heading_indices(lines: list[PdfLine]) -> list[tuple[int, re.Match]]:
    return [
        (index, match)
        for index, line in enumerate(lines)
        if (match := HEADING_RE.match(line.text))
    ]


def parse_scene_segment(
    segment: list[PdfLine],
    heading_match: re.Match,
    source_name: str,
    source_sha256: str,
) -> dict:
    scene_id = normalized_scene_id(
        heading_match.group("episode"),
        heading_match.group("number"),
        heading_match.group("suffix"),
    )
    cursor = 1
    heading_parts = [heading_match.group("heading").strip()]
    while cursor < len(segment) and segment[cursor].x < 82:
        heading_parts.append(segment[cursor].text)
        cursor += 1
    heading = re.sub(r"\s+", " ", " ".join(heading_parts)).strip()

    character_parts = []
    while (
        cursor < len(segment)
        and segment[cursor].x < 94
        and is_upper_line(segment[cursor].text)
    ):
        character_parts.append(segment[cursor].text)
        cursor += 1
    characters_raw = re.sub(
        r"\s+", " ", " ".join(character_parts)
    ).strip()

    title_parts = []
    while (
        cursor < len(segment)
        and segment[cursor].x < 94
        and not re.match(
            r"^\(?PARA", segment[cursor].text, flags=re.I
        )
    ):
        title_parts.append(segment[cursor].text)
        cursor += 1
    prepis = re.sub(r"\s+", " ", " ".join(title_parts)).strip()
    if not prepis:
        raise ValueError(f"{scene_id}: missing PREPIS/title")

    action_lines = segment[cursor:]
    action_raw, action_markdown = format_action(action_lines)
    characters = [
        item.strip()
        for item in re.split(r",|\s{2,}", characters_raw)
        if item.strip()
    ]
    location = location_from_heading(heading)
    return {
        "scene_id": scene_id,
        "episode": int(heading_match.group("episode")),
        "name": (
            f"{scene_id}. {heading}"
            + (f" — {characters_raw}" if characters_raw else "")
        ),
        "heading": heading,
        "prepis": prepis,
        "location": location,
        "characters": characters,
        "characters_raw": characters_raw,
        "action_raw": action_raw,
        "action_markdown": action_markdown,
        "action_sha256": hashlib.sha256(
            action_raw.encode("utf-8")
        ).hexdigest(),
        "source_pdf": source_name,
        "source_sha256": source_sha256,
    }


def append_paragraph(blocks: list[dict], kind: str, text: str) -> None:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return
    if blocks and blocks[-1]["kind"] == kind:
        blocks[-1]["text"] = f"{blocks[-1]['text']} {text}"
    else:
        blocks.append({"kind": kind, "text": text})


def format_action(lines: list[PdfLine]) -> tuple[str, str]:
    blocks: list[dict] = []
    speaker = None
    last_page = None
    last_top = None
    for line in lines:
        text = line.text.strip()
        if not text:
            continue
        page_break = last_page is not None and line.page != last_page
        vertical_gap = (
            last_top is not None
            and not page_break
            and line.top - last_top > 20
        )
        if line.x >= 260 and is_upper_line(text):
            blocks.append({"kind": "speaker", "text": text})
            speaker = text
        elif line.x >= 165 and speaker:
            if (
                blocks
                and blocks[-1]["kind"] == "dialogue"
                and not vertical_gap
                and not page_break
            ):
                blocks[-1]["text"] += f" {text}"
            else:
                blocks.append({
                    "kind": "dialogue",
                    "speaker": speaker,
                    "text": text,
                })
        else:
            speaker = None
            if (
                blocks
                and blocks[-1]["kind"] == "action"
                and not vertical_gap
                and not page_break
                and line.x >= 94
            ):
                blocks[-1]["text"] += f" {text}"
            else:
                append_paragraph(blocks, "action", text)
        last_page = line.page
        last_top = line.top

    raw_parts = []
    markdown_parts = []
    for block in blocks:
        if block["kind"] == "speaker":
            continue
        if block["kind"] == "dialogue":
            raw_parts.append(
                f"{block['speaker']}\n{block['text']}"
            )
            quote = "\n".join(
                f"> {part}" if part else ">"
                for part in block["text"].splitlines()
            )
            markdown_parts.append(
                f"> **{block['speaker']}:**\n{quote}"
            )
        else:
            raw_parts.append(block["text"])
            markdown_parts.append(f"*{block['text']}*")
    return "\n\n".join(raw_parts).strip(), "\n\n".join(markdown_parts).strip()


def location_from_heading(heading: str) -> str:
    value = re.sub(
        r"^(?:INT\.?\s*/\s*EXT\.?|EXT\.?\s*/\s*INT\.?|INT\.|EXT\.)\s*",
        "",
        heading,
        flags=re.I,
    )
    value = re.sub(
        r"\s*[-–—]\s*(?:DAY|NIGHT|DEŇ|DEN|NOC|RÁNO|RANO|VEČER|VECER)"
        r"(?:\s+[0-9X]+)?(?:\s*\([^)]*\))?\s*$",
        "",
        value,
        flags=re.I,
    )
    return re.sub(r"\s+", " ", value).strip()


def extract_episode(pdf_path: Path, episode: int) -> list[dict]:
    source_bytes = pdf_path.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    lines = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages):
            lines.extend(line_groups(page, page_index))
    lines = clean_lines(lines)
    occurrences = heading_indices(lines)
    by_scene: dict[str, list[tuple[int, re.Match]]] = defaultdict(list)
    for index, match in occurrences:
        if int(match.group("episode")) != episode:
            continue
        scene_id = normalized_scene_id(
            match.group("episode"),
            match.group("number"),
            match.group("suffix"),
        )
        by_scene[scene_id].append((index, match))

    if len(by_scene) != EXPECTED_EPISODE_COUNTS[episode]:
        raise ValueError(
            f"episode {episode}: expected {EXPECTED_EPISODE_COUNTS[episode]} "
            f"unique headings, found {len(by_scene)}"
        )
    selected = []
    for scene_id, matches in by_scene.items():
        if len(matches) < 2:
            raise ValueError(f"{scene_id}: full-script heading not found")
        selected.append(matches[-1])
    selected.sort(key=lambda item: item[0])

    scenes = []
    for position, (index, match) in enumerate(selected):
        end = selected[position + 1][0] if position + 1 < len(selected) else len(lines)
        scene = parse_scene_segment(
            lines[index:end],
            match,
            pdf_path.name,
            source_sha256,
        )
        scene["order_in_episode"] = position
        scenes.append(scene)
    return scenes


PROP_PATTERNS = [
    ("Medvedia lampička", r"\bmedved(?:ia|ie|iu)\s+(?:lampičk\w*|svetielk\w*)"),
    ("Alexova gitara", r"\b(?:gitar\w*|gitare|gitaru)\b"),
    ("Basketbalová lopta", r"\bbasketbalov\w+\s+lopt\w*"),
    ("Blister s liekmi / Ritalin", r"\b(?:ritalin\w*|blister\w*\s+s\s+liek\w*)"),
    ("Pištoľ / zbraň", r"\b(?:pištoľ\w*|zbraň\w*)"),
    ("Betin denník", r"\bdenník\w*"),
    ("Notebook / laptop", r"\b(?:notebook\w*|laptop\w*|macbook\w*)"),
    ("Mobilný telefón", r"\b(?:mobil\w*|telefón\w*)"),
    ("Sofiino auto", r"\bsofi\w+\s+aut\w*"),
    (
        "Auto / vozidlo",
        r"\b(?:auto|auta|autu|autom|áut|automobil\w*|vozidl\w*|"
        r"limuzín\w*|taxík\w*|dodávk\w*)\b",
    ),
    ("Kľúče", r"\bkľúč\w*"),
    ("Kufor", r"\bkufor\w*"),
    ("Fotografie / fotoalbum", r"\b(?:fotk\w*|fotografi\w*|fotoalbum\w*)"),
    ("Obálka", r"\bobálk\w*"),
    ("Peniaze / bankovky", r"\b(?:peniaz\w*|bankovk\w*)"),
    ("Taška / batoh", r"\b(?:tašk\w*|batoh\w*)"),
    ("Bunda", r"\bbund\w*"),
    ("Dokumenty / zmluva / spis", r"\b(?:dokument\w*|zmluv\w*|spis\w*)"),
    ("Slúchadlá", r"\bslúchadl\w*"),
    ("USB kľúč", r"\bUSB\b"),
    ("Diktafón", r"\bdiktafón\w*"),
    ("Kamera", r"\bkamer\w*"),
    ("Kvety", r"\bkvet\w*"),
    ("Plyšová hračka", r"\bplyšov\w+\s+hračk\w*"),
    ("Jedlo / nápoj", r"\b(?:jedl\w*|lievanc\w*|drink\w*|pohár\w*|fľaš\w*)"),
]

CONTINUITY_PROP_IDENTITIES = {
    "Medvedia lampička",
    "Alexova gitara",
    "Basketbalová lopta",
    "Blister s liekmi / Ritalin",
    "Pištoľ / zbraň",
    "Betin denník",
    "Sofiino auto",
}

EXPLICIT_PROP_CHAINS = [
    {
        "key": "medvedia lampicka",
        "identity": "Medvedia lampička",
        "scenes": [
            (
                "06/01FLASH",
                "Sofia lampičku rozsvieti, aby chránila malú Bety pred tmou",
            ),
            (
                "06/03",
                "lampička zostáva v zásuvke aj v súčasnosti",
            ),
        ],
    },
    {
        "key": "sofiino auto",
        "identity": "Sofiino auto",
        "scenes": [
            (
                "06/41LP",
                "Bety a Dogy ho nájdu s bundou a kradnutým tovarom",
            ),
            (
                "06/42LP",
                "to isté nájdené auto sleduje neznámy pozorovateľ",
            ),
            (
                "06/50",
                "Keler nájde to isté auto horiace",
            ),
        ],
    },
]

SET_ELEMENT_PATTERNS = [
    ("Automat na jedlo", r"\bautomat\w*"),
    ("Gauč", r"\bgauč\w*"),
    ("Dvere", r"\bdver\w*"),
    ("Okno", r"\bokn\w*"),
    ("Pódium", r"\bpódi\w*"),
    ("Nástenka", r"\bnástenk\w*"),
    ("Stôl", r"\bstol\w*"),
    ("Posteľ", r"\bposteľ\w*"),
]


def context_sentence(text: str, pattern: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text))
    matcher = re.compile(pattern, re.I)
    for sentence in sentences:
        if matcher.search(sentence):
            return sentence.strip()
    return "predmet je priamo použitý alebo viditeľný v obraze"


def extract_materials(scene: dict) -> None:
    searchable = f"{scene['prepis']} {scene['action_raw']}"
    props = []
    seen = set()
    for identity, pattern in PROP_PATTERNS:
        if identity == "Auto / vozidlo" and any(
            item["stable_name"] == "Sofiino auto" for item in props
        ):
            continue
        if re.search(pattern, searchable, re.I):
            if identity == "Alexova gitara" and not re.search(
                r"\bALEX\b", scene["characters_raw"], re.I
            ):
                identity = "Gitara"
            if identity == "Betin denník" and not re.search(
                r"\bBETY\b", scene["characters_raw"], re.I
            ):
                identity = "Denník"
            key = folded(identity)
            if key in seen:
                continue
            seen.add(key)
            action_source = (
                scene["action_raw"]
                if re.search(pattern, scene["action_raw"], re.I)
                else scene["prepis"]
            )
            action = context_sentence(action_source, pattern)
            props.append({
                "stable_name": identity,
                "action": action,
                "source_text": f"{identity} — {action}",
                "continuity": False,
            })
    set_extras = []
    for identity, pattern in SET_ELEMENT_PATTERNS:
        if re.search(pattern, searchable, re.I):
            action_source = (
                scene["action_raw"]
                if re.search(pattern, scene["action_raw"], re.I)
                else scene["prepis"]
            )
            action = context_sentence(action_source, pattern)
            set_extras.append({
                "stable_name": identity,
                "action": action,
                "source_text": f"{identity} — {action}",
                "continuity": False,
            })
    if re.search(r"\bKOMPARZ\b", scene["characters_raw"], re.I):
        set_extras.append({
            "stable_name": "Komparzová akcia",
            "action": "komparz je prítomný podľa hlavičky a akcie obrazu",
            "source_text": (
                "Komparzová akcia — komparz je prítomný podľa hlavičky "
                "a akcie obrazu"
            ),
            "continuity": False,
        })
    scene["props"] = props
    scene["set_extras"] = set_extras


STRICT_SET_CHAINS = [
    {
        "key": "imatrikulacna-party-telocvicna",
        "identity": "Imatrikulačná párty – výzdoba a usporiadanie telocvične",
        "reason": "Eventový setup vzniká v 01/40 a pokračuje do 01/43.",
        "scenes": ["01/40", "01/41", "01/42", "01/43"],
    },
    {
        "key": "otvorenie-basketbalovej-sezony",
        "identity": "Otvorenie basketbalovej sezóny – pódium, hľadisko a občerstvenie",
        "reason": "Konkrétny eventový setup pokračuje od 02/43 po 02/53.",
        "scenes": [
            "02/43", "02/44", "02/45", "02/46", "02/47A", "02/48",
            "02/47B", "02/49", "02/50", "02/51", "02/47C", "02/53",
        ],
    },
    {
        "key": "aktivovana-skolska-redakcia",
        "identity": "Aktivovaná školská redakcia – uprataný a používaný priestor",
        "reason": "V 03/11 sa nepoužívaná miestnosť mení na aktívnu redakciu.",
        "scenes": [
            "03/11", "03/22", "03/27", "03/53", "05/05", "05/17",
            "05/46", "05/47LP", "06/02", "06/08",
        ],
    },
    {
        "key": "kelerova-vysetrovacia-nastenka",
        "identity": "Kelerova vyšetrovacia nástenka a pracovňa",
        "reason": "Nástenka a spisy z 04/28 prechádzajú do poškodeného stavu v 04/42.",
        "scenes": ["04/28", "04/42"],
    },
    {
        "key": "kar-revayovci-hala",
        "identity": "Kar u Révayovcov – výzdoba a eventové usporiadanie haly",
        "reason": "Výzdoba a setup karu pokračujú medzi 05/13, 05/36 a 05/37.",
        "scenes": ["05/13", "05/36", "05/37"],
    },
    {
        "key": "skolska-akademia-divadelna-sala",
        "identity": "Školská akadémia – pódium, hľadisko a backstage",
        "reason": "Konkrétny setup akadémie vzniká pri otvorení a pokračuje cez vystúpenia.",
        "scenes": [
            "06/37", "06/38", "06/39", "06/40", "06/43", "06/44", "06/45",
        ],
    },
]


def previous_and_next(
    occurrences: list[dict], current_scene_id: str
) -> tuple[dict | None, dict | None]:
    position = next(
        index
        for index, item in enumerate(occurrences)
        if item["scene_id"] == current_scene_id
    )
    previous = occurrences[position - 1] if position else None
    following = (
        occurrences[position + 1]
        if position + 1 < len(occurrences)
        else None
    )
    return previous, following


def continuity_item(
    stable_name: str,
    action: str,
    registry_key: str,
    previous: dict | None,
    following: dict | None,
) -> dict:
    return {
        "stable_name": stable_name,
        "action": action,
        "registry_key": registry_key,
        "continuity": True,
        "previous": (
            {
                "scene_id": previous["scene_id"],
                "state": previous["action"],
            }
            if previous else None
        ),
        "current_state": action,
        "next": (
            {
                "scene_id": following["scene_id"],
                "state": following["action"],
            }
            if following else None
        ),
    }


def add_continuity(scenes: list[dict]) -> tuple[dict, dict]:
    by_id = {scene["scene_id"]: scene for scene in scenes}
    prop_occurrences: dict[str, list[dict]] = defaultdict(list)
    for scene in scenes:
        for item in scene["props"]:
            if item["stable_name"] not in CONTINUITY_PROP_IDENTITIES:
                continue
            key = folded(item["stable_name"])
            prop_occurrences[key].append({
                "scene_id": scene["scene_id"],
                "action": item["action"],
            })
    prop_registry = {}
    for key, occurrences in prop_occurrences.items():
        if len(occurrences) < 2:
            continue
        identity = next(
            item["stable_name"]
            for scene in scenes
            for item in scene["props"]
            if folded(item["stable_name"]) == key
        )
        prop_registry[key] = {
            "identity": identity,
            "aliases": [identity],
            "occurrences": occurrences,
        }
        for occurrence in occurrences:
            scene = by_id[occurrence["scene_id"]]
            index = next(
                index for index, item in enumerate(scene["props"])
                if folded(item["stable_name"]) == key
            )
            previous, following = previous_and_next(
                occurrences, scene["scene_id"]
            )
            scene["props"][index] = continuity_item(
                identity,
                scene["props"][index]["action"],
                key,
                previous,
                following,
            )

    for chain in EXPLICIT_PROP_CHAINS:
        occurrences = [
            {"scene_id": scene_id, "action": action}
            for scene_id, action in chain["scenes"]
        ]
        missing = [
            item["scene_id"] for item in occurrences
            if item["scene_id"] not in by_id
        ]
        if missing:
            raise ValueError(
                f"prop chain {chain['key']} missing scenes {missing}"
            )
        prop_registry[chain["key"]] = {
            "identity": chain["identity"],
            "aliases": [chain["identity"]],
            "occurrences": occurrences,
        }
        for occurrence in occurrences:
            scene = by_id[occurrence["scene_id"]]
            scene["props"] = [
                item for item in scene["props"]
                if folded(item["stable_name"]) != chain["key"]
            ]
            previous, following = previous_and_next(
                occurrences, scene["scene_id"]
            )
            scene["props"].append(continuity_item(
                chain["identity"],
                occurrence["action"],
                chain["key"],
                previous,
                following,
            ))

    set_registry = {}
    strict_by_scene = {}
    for chain in STRICT_SET_CHAINS:
        missing = [item for item in chain["scenes"] if item not in by_id]
        if missing:
            raise ValueError(
                f"strict set chain {chain['key']} missing scenes {missing}"
            )
        occurrences = [
            {
                "scene_id": scene_id,
                "action": (
                    f"konkrétny zmenený stav setu pokračuje v {scene_id}"
                ),
            }
            for scene_id in chain["scenes"]
        ]
        set_registry[chain["key"]] = {
            "identity": chain["identity"],
            "aliases": [chain["identity"]],
            "reason": chain["reason"],
            "occurrences": occurrences,
        }
        for occurrence in occurrences:
            strict_by_scene[occurrence["scene_id"]] = chain["key"]

    for scene in scenes:
        set_key = strict_by_scene.get(scene["scene_id"])
        if set_key:
            entry = set_registry[set_key]
            previous, following = previous_and_next(
                entry["occurrences"], scene["scene_id"]
            )
            action = next(
                item["action"] for item in entry["occurrences"]
                if item["scene_id"] == scene["scene_id"]
            )
            primary = continuity_item(
                entry["identity"], action, set_key, previous, following
            )
        else:
            primary = {
                "stable_name": scene["location"],
                "action": f"prostredie obrazu {scene['scene_id']}",
                "source_text": (
                    f"{scene['location']} — prostredie obrazu "
                    f"{scene['scene_id']}"
                ),
                "continuity": False,
            }
        scene["set_items"] = [primary, *scene.pop("set_extras")]
        has_prop = any(item.get("continuity") for item in scene["props"])
        has_set = any(item.get("continuity") for item in scene["set_items"])
        auto = bool(re.search(
            r"\b(?:auto|auta|autu|autom|aut|automobil\w*|vozidl\w*|"
            r"limuzin\w*|taxik\w*|dodavk\w*)\b",
            folded(f"{scene['prepis']} {scene['action_raw']}"),
        ))
        scene["labels"] = [
            label
            for label, enabled in (
                ("Nadväzná rekvizita", has_prop),
                ("Nadväzný set", has_set),
                ("Auto", auto),
            )
            if enabled
        ]
        scene["questions"] = {
            "02/19LP": [
                "Má pietne miesto pri Jakubovej skrinke pokračovať v "
                "konkrétnom nasledujúcom obraze?"
            ],
            "02/41": [
                "Má rozbité sklo automatu zostať viditeľne rozbité v "
                "konkrétnom nasledujúcom obraze?"
            ],
        }.get(scene["scene_id"], [])
    return prop_registry, set_registry


def build_payload(pdf_root: Path) -> dict:
    scenes = []
    source_pdfs = []
    for episode in range(1, 7):
        path = locate_authoritative_pdf(pdf_root, episode)
        episode_scenes = extract_episode(path, episode)
        for scene in episode_scenes:
            extract_materials(scene)
        scenes.extend(episode_scenes)
        source_pdfs.append({
            "episode": episode,
            "filename": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "pages": len(pdfplumber.open(path).pages),
            "scenes": len(episode_scenes),
        })
    scene_ids = [scene["scene_id"] for scene in scenes]
    if len(scene_ids) != 313 or len(set(scene_ids)) != 313:
        raise ValueError(
            f"expected 313 unique scene IDs, got "
            f"{len(scene_ids)}/{len(set(scene_ids))}"
        )
    for order, scene in enumerate(scenes):
        scene["order"] = order
    prop_registry, set_registry = add_continuity(scenes)
    return {
        "project": "Čierny Kameň",
        "board_ref": "CzuD55PR",
        "scene_list_name": "SCENÁRE",
        "prop_registry_list_name": "REGISTER REKVIZÍT",
        "set_registry_list_name": "REGISTER SETOV",
        "source_kind": "six_final_pdfs",
        "source_pdfs": source_pdfs,
        "episode_counts": {
            f"{episode:02d}": EXPECTED_EPISODE_COUNTS[episode]
            for episode in range(1, 7)
        },
        "scenes": scenes,
        "prop_registry": prop_registry,
        "set_registry": set_registry,
        "stats": {
            "scenes": len(scenes),
            "unique_scene_ids": len(set(scene_ids)),
            "missing_prepis": sum(not scene["prepis"] for scene in scenes),
            "missing_action": sum(not scene["action_raw"] for scene in scenes),
            "prop_items_total": sum(len(scene["props"]) for scene in scenes),
            "set_items_total": sum(
                len(scene["set_items"]) for scene in scenes
            ),
            "prop_registry_cards": len(prop_registry),
            "set_registry_cards": len(set_registry),
            "continuity_prop_scenes": sum(
                "Nadväzná rekvizita" in scene["labels"] for scene in scenes
            ),
            "continuity_set_scenes": sum(
                "Nadväzný set" in scene["labels"] for scene in scenes
            ),
            "auto_scenes": sum(
                "Auto" in scene["labels"] for scene in scenes
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = build_payload(args.pdf_root.resolve())
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(payload["stats"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
