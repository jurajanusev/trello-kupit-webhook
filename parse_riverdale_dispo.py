import json
import re
import sys
from datetime import datetime

import pdfplumber


DAY_RE = re.compile(r"^Day #(\d+):.*?(\d{2}/\d{2}/\d{4})")
SCENE_RE = re.compile(r"^\d+[A-Z]*$", re.I)


def clean(value):
    return re.sub(r"\s+", " ", value or "").strip()


def parse(pdf_path):
    rows = []
    current_day = None
    current_date = None
    current_unit = "1st unit"
    order = 0
    pending = None

    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for cells in table:
                    first = clean(cells[0] if cells else "")
                    day_match = DAY_RE.match(first)
                    if day_match:
                        current_day = int(day_match.group(1))
                        current_date = datetime.strptime(
                            day_match.group(2), "%m/%d/%Y"
                        ).date().isoformat()
                        order = 0
                        pending = None
                        continue
                    if first.startswith("Day Off:"):
                        current_day = None
                        current_date = None
                        pending = None
                        continue
                    if first.startswith("1st unit"):
                        current_unit = "1st unit"
                        continue
                    if first.startswith("2nd unit") and "Day Off" not in first:
                        current_unit = "2nd unit"
                        continue
                    if current_day is None or current_date is None:
                        continue

                    setting = clean(cells[1] if len(cells) > 1 else "")
                    episode_cell = clean(cells[4] if len(cells) > 4 else "")
                    episode_match = re.search(r"Episode:\s*(\d+)", episode_cell, re.I)

                    if SCENE_RE.fullmatch(first) and setting:
                        pending = {
                            "scene": first.upper(),
                            "setting": setting,
                            "location": clean(cells[3] if len(cells) > 3 else ""),
                            "characters": clean(cells[4] if len(cells) > 4 else ""),
                            "source_page": page_number,
                        }
                        continue

                    if pending and episode_match:
                        episode = int(episode_match.group(1))
                        order += 1
                        scene = pending["scene"]
                        rows.append({
                            "scene_id": f"{episode:02d}/{scene}",
                            "episode": episode,
                            "scene": scene,
                            "shooting_day": current_day,
                            "shooting_date": current_date,
                            "order": order,
                            "unit": current_unit,
                            "location": pending["location"],
                            "setting": pending["setting"],
                            "story": clean(cells[3] if len(cells) > 3 else ""),
                            "characters": pending["characters"],
                            "script_day": first,
                            "source_page": pending["source_page"],
                        })
                        pending = None

    return {
        "source": {
            "title": "Schedule Style A - Cierny kamen",
            "dated": "2026-10-11",
            "file": pdf_path,
            "date_derivation": "Explicit date from each numbered Day header.",
        },
        "rows": rows,
    }


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: parse_riverdale_dispo.py INPUT.pdf OUTPUT.json")
    result = parse(sys.argv[1])
    with open(sys.argv[2], "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({"output": sys.argv[2], "rows": len(result["rows"]),
                      "first": result["rows"][:1], "last": result["rows"][-1:]},
                     ensure_ascii=False, indent=2))
