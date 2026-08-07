import json
import re
import sys
from datetime import datetime

import pdfplumber


SCENE_RE = re.compile(r"^\s*(\d{1,2})\s*/\s*(\d+[A-Z]*)\s*$", re.I)
DAY_RE = re.compile(r"^Day #(\d+):.*?(\d{2}/\d{2}/\d{4})")
SPLIT_SCENE_RE = re.compile(r"^\d+[A-Z]*$", re.I)


def clean(value):
    return re.sub(r"\s+", " ", value or "").strip()


def parse(pdf_path):
    rows = []
    current_day = None
    current_date = None
    current_unit = "1st unit"
    order = 0
    pending_scene = None
    source_label = None

    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            if source_label is None:
                header = page.extract_text() or ""
                source_match = re.search(
                    r"DUNAJ\s+16.*?\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b",
                    header, flags=re.I | re.S,
                )
                if source_match:
                    day, month, year = map(int, source_match.groups())
                    source_label = f"predbežná dispo DUNAJ 16 z {day}. {month}. {year}"
            for table in page.extract_tables():
                for cells in table:
                    first = clean(cells[0])
                    day_match = DAY_RE.match(first)
                    if day_match:
                        current_day = int(day_match.group(1))
                        current_date = datetime.strptime(
                            day_match.group(2), "%m/%d/%Y"
                        ).date().isoformat()
                        order = 0
                        pending_scene = None
                        continue
                    if first.startswith("Day Off:"):
                        current_day = None
                        current_date = None
                        order = 0
                        pending_scene = None
                        continue
                    if first.startswith("1st unit"):
                        current_unit = "1st unit"
                        continue
                    if first.startswith("2nd unit") and "Day Off" not in first:
                        current_unit = "2nd unit"
                        continue

                    # New Schedule Style B exports split every scene over two
                    # table rows. The first row contains scene/location/story;
                    # the following row contains script day, setting, cast and
                    # an ``Epizóda`` marker from which the episode is recovered.
                    second = clean(cells[1] if len(cells) > 1 else "")
                    if SPLIT_SCENE_RE.fullmatch(first) and not second:
                        pending_scene = {
                            "scene": first.upper(),
                            "location": clean(cells[2] if len(cells) > 2 else ""),
                            "story": clean(cells[3] if len(cells) > 3 else ""),
                            "source_page": page_number,
                        }
                        continue
                    if pending_scene and SPLIT_SCENE_RE.fullmatch(first) and second:
                        detail = clean(cells[3] if len(cells) > 3 else "")
                        episode_match = re.search(r"Epi.*?da:\s*(\d+)", detail, flags=re.I)
                        if not episode_match:
                            raise ValueError(
                                f"episode marker missing on page {page_number}: {detail}"
                            )
                        episode = int(episode_match.group(1))
                        before_episode = detail[:episode_match.start()].strip(" ,")
                        cast_parts = [part.strip() for part in before_episode.split(",") if part.strip()]
                        extras_parts = [part for part in cast_parts if "komparz" in part.casefold()]
                        character_parts = [part for part in cast_parts if "komparz" not in part.casefold()]
                        characters = ", ".join(
                            re.sub(r"^\d+\s*-\s*", "", part).strip()
                            for part in character_parts
                        )
                        notes_match = re.search(r"Pozn.*?mky:\s*(.*)$", detail, flags=re.I)
                        duration_match = re.search(
                            r"Shoot Dur\.:\s*([^;]+)",
                            clean(cells[2] if len(cells) > 2 else ""), flags=re.I,
                        )
                        notes = ", ".join(value for value in [
                            duration_match.group(1).strip() if duration_match else "",
                            notes_match.group(1).strip() if notes_match else "",
                        ] if value)
                        order += 1
                        scene = pending_scene["scene"]
                        rows.append({
                            "scene_id": f"{episode:02d}/{scene}",
                            "episode": episode,
                            "scene": scene,
                            "shooting_day": current_day,
                            "shooting_date": current_date,
                            "order": order,
                            "unit": current_unit,
                            "setting": second,
                            "script_day": first,
                            "location": pending_scene["location"],
                            "story": pending_scene["story"],
                            "characters": characters,
                            "extras": ", ".join(extras_parts),
                            "notes": notes,
                            "source_page": pending_scene["source_page"],
                        })
                        pending_scene = None
                        continue

                    scene_match = SCENE_RE.match(first)
                    if not scene_match or current_day is None or current_date is None:
                        continue
                    episode = int(scene_match.group(1))
                    scene = scene_match.group(2).upper()
                    order += 1
                    rows.append({
                        "scene_id": f"{episode:02d}/{scene}",
                        "episode": episode,
                        "scene": scene,
                        "shooting_day": current_day,
                        "shooting_date": current_date,
                        "order": order,
                        "unit": current_unit,
                        "setting": clean(cells[1] if len(cells) > 1 else ""),
                        "script_day": clean(cells[2] if len(cells) > 2 else ""),
                        "location": clean(cells[3] if len(cells) > 3 else ""),
                        "story": clean(cells[4] if len(cells) > 4 else ""),
                        "characters": clean(cells[5] if len(cells) > 5 else ""),
                        "extras": clean(cells[6] if len(cells) > 6 else ""),
                        "notes": clean(cells[8] if len(cells) > 8 else ""),
                        "source_page": page_number,
                    })

    return {
        "source": source_label or "predbežná dispo DUNAJ 16",
        "rows": rows,
    }


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: parse_dunaj_dispo.py INPUT.pdf OUTPUT.json")
    result = parse(sys.argv[1])
    with open(sys.argv[2], "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({
        "output": sys.argv[2],
        "rows": len(result["rows"]),
        "first": result["rows"][0] if result["rows"] else None,
        "last": result["rows"][-1] if result["rows"] else None,
    }, ensure_ascii=False, indent=2))
