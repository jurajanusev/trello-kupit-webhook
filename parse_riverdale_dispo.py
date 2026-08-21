import json
import re
import sys
from datetime import datetime, timedelta

import pdfplumber


DAY_RE = re.compile(r"Day\s*#(\d+)", re.I)
SOURCE_DATE_RE = re.compile(r"dated:\s*(\d{1,2}\.\d{1,2}\.\d{4})", re.I)
EPISODE_RE = re.compile(r"Episode:\s*(\d+)", re.I)
SCENE_RE = re.compile(r"^\d+[A-Z]*$", re.I)


def clean(value):
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_scene(episode, scene):
    match = re.fullmatch(r"0*(\d+)([A-Z]*)", scene, flags=re.I)
    if not match:
        raise ValueError(f"unsupported scene number: {scene!r}")
    return f"{int(episode):02d}/{int(match.group(1))}{match.group(2).upper()}"


def parse(pdf_path):
    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        first_text = pdf.pages[0].extract_text() or ""
        source_match = SOURCE_DATE_RE.search(first_text)
        if not source_match:
            raise ValueError("source date not found")
        source_date = datetime.strptime(source_match.group(1), "%d.%m.%Y").date()
        event_date = source_date - timedelta(days=1)
        current_day = None
        current_date = None
        order = 0
        pending = None
        stopped = False

        for page_number, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for cells in table:
                    values = [clean(value) for value in (cells + [None] * 4)[:4]]
                    first, setting, text, detail = values
                    if "SHOOT END" in first.upper():
                        stopped = True
                        break
                    if "DAY OFF" in first.upper():
                        event_date += timedelta(days=1)
                        current_day = None
                        current_date = None
                        order = 0
                        pending = None
                        continue
                    day_match = DAY_RE.search(first)
                    if day_match:
                        event_date += timedelta(days=1)
                        current_day = int(day_match.group(1))
                        current_date = event_date.isoformat()
                        order = 0
                        pending = None
                        continue
                    if current_day is None:
                        continue

                    episode_match = EPISODE_RE.search(detail)
                    if episode_match and pending:
                        order += 1
                        scene_id = normalize_scene(
                            int(episode_match.group(1)), pending["scene"]
                        )
                        rows.append({
                            "scene_id": scene_id,
                            "episode": int(episode_match.group(1)),
                            "scene": pending["scene"],
                            "shooting_day": current_day,
                            "shooting_date": current_date,
                            "order": order,
                            "unit": "1st unit",
                            "location": pending["location"],
                            "setting": pending["setting"],
                            "story": text,
                            "characters": pending["characters"],
                            "source_page": pending["source_page"],
                        })
                        pending = None
                        continue

                    if SCENE_RE.fullmatch(first) and setting and text:
                        pending = {
                            "scene": first.upper(),
                            "setting": setting,
                            "location": text,
                            "characters": detail,
                            "source_page": page_number,
                        }
                if stopped:
                    break
            if stopped:
                break

    return {
        "source": {
            "title": "Schedule Style A - Cierny kamen",
            "dated": source_date.isoformat(),
            "file": pdf_path,
            "date_derivation": (
                "Day #1 is the schedule's dated day; each Day Off or numbered "
                "day advances one calendar date."
            ),
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
    print(json.dumps({
        "output": sys.argv[2],
        "rows": len(result["rows"]),
        "first": result["rows"][0] if result["rows"] else None,
        "last": result["rows"][-1] if result["rows"] else None,
    }, ensure_ascii=False, indent=2))
