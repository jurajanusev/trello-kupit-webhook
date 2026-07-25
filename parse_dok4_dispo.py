import json
import re
import sys
from datetime import datetime

import pdfplumber


SCENE_RE = re.compile(r"^\s*(\d{1,2})\s*/\s*(\d+[A-Z]*)\s*$", re.I)
DAY_RE = re.compile(r"^Day #(\d+):.*?(\d{2}/\d{2}/\d{4})(?:\s|$)")


def clean(value):
    return re.sub(r"\s+", " ", value or "").strip()


def parse(pdf_path):
    rows = []
    current_day = None
    current_date = None
    current_unit = "1st unit"
    order = 0
    stopped = False

    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for cells in table:
                    first = clean(cells[0])
                    if first == "SHOOT END":
                        stopped = True
                        break
                    day_match = DAY_RE.match(first)
                    if day_match:
                        current_day = int(day_match.group(1))
                        current_date = datetime.strptime(day_match.group(2), "%m/%d/%Y").date().isoformat()
                        order = 0
                        continue
                    if first.startswith("Day Off:"):
                        current_day = None
                        current_date = None
                        order = 0
                        continue
                    if first.startswith("1st unit"):
                        current_unit = "1st unit"
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
                        "location": clean(cells[1]),
                        "setting": clean(cells[2]),
                        "story": clean(cells[3]),
                        "characters": clean(cells[4]),
                        "source_page": page_number,
                    })
                if stopped:
                    break
            if stopped:
                break
    return {
        "source": {
            "title": "PREDBEZNE DISPO - DRUHA SANCA 4",
            "dated": datetime.fromtimestamp(
                __import__("os").path.getmtime(pdf_path)
            ).date().isoformat(),
            "file": pdf_path,
        },
        "rows": rows,
    }


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: parse_dok4_dispo.py INPUT.pdf OUTPUT.json")
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
