from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pdfplumber

import build_cierny_kamen_pdf_payload as base


PDFS = {
    7: "SC_01_07_ČK_1.8_MK._KC_FINAL.pdf",
    8: "SC_01_08_ČK_2.2_NJ_SG_FINAL.pdf",
    9: "SC_01_09_ČK_1.4_MV_KC_FINALdocx .pdf",
    10: "SC_01_10_ČK_1.7_MV_KC_FINALdocx.pdf",
}
EXPECTED = {7: 51, 8: 47, 9: 51, 10: 51}
HEADING = re.compile(
    r"^(?P<episode>\d+)\s*/\s*(?P<number>\d+)\s*\.?\s*"
    r"(?P<suffix>FLASH|LP)?\.?\s*"
    r"(?P<heading>.+)$",
    re.I,
)


def parse_segment(segment, match, source_name, source_hash):
    scene_id = base.normalized_scene_id(
        match.group("episode"), match.group("number"), match.group("suffix") or ""
    )
    cursor = 1
    # In the four final PDFs the full scene heading is always on its numbered
    # source line.  Treating the next narrow, uppercase line as a continuation
    # incorrectly swallowed the cast of 07/04 into the location.
    heading = re.sub(r"\s+", " ", match.group("heading")).strip()
    character_parts = []
    while cursor < len(segment) and segment[cursor].x < 94 and base.is_upper_line(segment[cursor].text):
        character_parts.append(segment[cursor].text)
        cursor += 1
    characters_raw = re.sub(r"\s+", " ", " ".join(character_parts)).strip()
    if cursor >= len(segment):
        raise ValueError(f"{scene_id}: missing PREPIS/title")
    title_parts = [segment[cursor].text]
    title_page = segment[cursor].page
    title_top = segment[cursor].top
    cursor += 1
    # A wrapped title line is unusually indented and very close vertically;
    # ordinary action paragraphs start at the normal action x-position.
    while (
        cursor < len(segment)
        and segment[cursor].page == title_page
        and segment[cursor].top - title_top < 18
        and segment[cursor].x < 94
    ):
        title_parts.append(segment[cursor].text)
        title_top = segment[cursor].top
        cursor += 1
    prepis = re.sub(r"\s+", " ", " ".join(title_parts)).strip()
    action_raw, action_markdown = base.format_action(segment[cursor:])
    characters = [item.strip() for item in re.split(r",|\s{2,}", characters_raw) if item.strip()]
    return {
        "scene_id": scene_id, "episode": int(match.group("episode")),
        "name": f"{scene_id}. {heading}" + (f" — {characters_raw}" if characters_raw else ""),
        "heading": heading, "prepis": prepis,
        "location": normalized_location(heading),
        "characters": characters, "characters_raw": characters_raw,
        "action_raw": action_raw, "action_markdown": action_markdown,
        "action_sha256": hashlib.sha256(action_raw.encode("utf-8")).hexdigest(),
        "source_pdf": source_name, "source_sha256": source_hash,
    }


def normalized_location(heading):
    value = base.location_from_heading(heading)
    # DAY/NIGHT plus a schedule letter/number is production metadata, not part
    # of the story-space identity.  Parenthetical story qualifiers remain.
    return re.sub(
        r"\s*[-–—]\s*(?:DAY|NIGHT)\s+[A-Z0-9]+(?:\s*\([^)]*\))?\s*$",
        "", value, flags=re.I,
    ).strip()


def extract(pdf_path: Path, episode: int):
    source_hash = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    lines = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages):
            lines.extend(base.line_groups(page, page_index))
        pages = len(pdf.pages)
    lines = base.clean_lines(lines)
    occurrences = []
    for index, line in enumerate(lines):
        match = HEADING.match(line.text)
        if match and int(match.group("episode")) == episode:
            scene_id = base.normalized_scene_id(
                match.group("episode"), match.group("number"),
                match.group("suffix") or "",
            )
            occurrences.append((index, match, scene_id, line.page + 1, line.text))
    by_id = {}
    for item in occurrences:
        by_id.setdefault(item[2], []).append(item)
    if len(by_id) != EXPECTED[episode]:
        raise ValueError(
            f"episode {episode}: expected {EXPECTED[episode]}, got {len(by_id)}: "
            f"{sorted(by_id)}"
        )
    selected = []
    for scene_id, matches in by_id.items():
        if len(matches) < 2:
            raise ValueError(f"{scene_id}: missing full-script occurrence")
        selected.append(matches[-1])
    selected.sort(key=lambda item: item[0])
    scenes = []
    for position, (index, match, scene_id, page, raw_heading) in enumerate(selected):
        end = selected[position + 1][0] if position + 1 < len(selected) else len(lines)
        scene = parse_segment(
            lines[index:end], match, pdf_path.name, source_hash,
        )
        scene["order_in_episode"] = position
        scene["source_page"] = page
        scene["source_heading_line"] = raw_heading
        scene["props"] = []
        scene["set_items"] = [{
            "stable_name": scene["location"],
            "action": f"prostredie obrazu {scene_id}",
            "source_text": f"{scene['location']} — prostredie obrazu {scene_id}",
            "continuity": False,
        }]
        scene["labels"] = []
        scene["questions"] = []
        scenes.append(scene)
    return scenes, {
        "episode": episode, "filename": pdf_path.name,
        "sha256": source_hash, "pages": pages, "scenes": len(scenes),
        "all_ids": [scene["scene_id"] for scene in scenes],
        "occurrence_counts": {
            scene_id: len(matches) for scene_id, matches in sorted(by_id.items())
        },
    }


def main():
    root = Path(r"C:\Users\juraj\Downloads")
    scenes = []
    sources = []
    for episode, filename in PDFS.items():
        episode_scenes, source = extract(root / filename, episode)
        scenes.extend(episode_scenes)
        sources.append(source)
    ids = [scene["scene_id"] for scene in scenes]
    if len(ids) != 200 or len(set(ids)) != 200:
        raise ValueError(f"expected 200 unique IDs, got {len(ids)}/{len(set(ids))}")
    for order, scene in enumerate(scenes):
        scene["order"] = order
    payload = {
        "project": "Čierny Kameň", "board_ref": "CzuD55PR",
        "source_kind": "four_final_pdfs_ep07_10",
        "source_pdfs": sources,
        "episode_counts": {f"{ep:02d}": count for ep, count in EXPECTED.items()},
        "scenes": scenes,
        "stats": {
            "scenes": len(scenes), "unique_scene_ids": len(set(ids)),
            "missing_prepis": sum(not scene["prepis"] for scene in scenes),
            "missing_action": sum(not scene["action_raw"] for scene in scenes),
            "lp": sum(scene["scene_id"].endswith("LP") for scene in scenes),
            "flash": sum(scene["scene_id"].endswith("FLASH") for scene in scenes),
        },
    }
    Path("cierny_kamen_ep07_10_scenes.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"stats": payload["stats"], "sources": sources},
                     ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
