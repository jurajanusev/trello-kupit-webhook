from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


RENAME_MAP = {"01/12FLASH": "01/12LP"}


def split_old_description(value: str) -> tuple[str, str]:
    match = re.search(
        r"\*\*PREPIS:\s*(?P<title>.*?)\*\*\s*(?P<body>.*)\Z",
        value or "",
        flags=re.S | re.I,
    )
    if not match:
        raise ValueError("old description has no PREPIS")
    return match.group("title").strip(), match.group("body").strip()


def normalized(value: str) -> str:
    value = re.sub(r"\*\*(?P<speaker>[^*\n]+?):\*\*", r"\g<speaker>", value)
    return re.sub(r"\s+", " ", value).strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old-root", type=Path, required=True)
    parser.add_argument("--new-payload", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = json.loads(args.new_payload.read_text(encoding="utf-8"))
    new_by_id = {scene["scene_id"]: scene for scene in payload["scenes"]}
    episodes = []
    totals = {
        "matched": 0,
        "renamed": len(RENAME_MAP),
        "created": 0,
        "removed": 0,
        "content_changed": 0,
        "title_changed": 0,
    }
    for episode in range(1, 7):
        if episode <= 5:
            old_path = args.old_root / (
                f"cierny_kamen_ep{episode:02d}_cards.json"
            )
            old_payload = json.loads(old_path.read_text(encoding="utf-8"))
            old_by_id = {card["number"]: card for card in old_payload["cards"]}
        else:
            old_by_id = {}

        comparable = {}
        for old_id, card in old_by_id.items():
            comparable[RENAME_MAP.get(old_id, old_id)] = (old_id, card)
        new_episode = {
            scene_id: scene
            for scene_id, scene in new_by_id.items()
            if scene["episode"] == episode
        }
        added = sorted(set(new_episode) - set(comparable))
        removed = sorted(set(comparable) - set(new_episode))
        matched = sorted(set(new_episode) & set(comparable))
        content_changed = []
        title_changed = []
        for scene_id in matched:
            _old_id, old_card = comparable[scene_id]
            old_title, old_body = split_old_description(
                old_card["description"]
            )
            new_scene = new_episode[scene_id]
            if normalized(old_title) != normalized(new_scene["prepis"]):
                title_changed.append(scene_id)
            if normalized(old_body) != normalized(new_scene["action_raw"]):
                content_changed.append(scene_id)
        entry = {
            "episode": episode,
            "old": len(old_by_id),
            "new": len(new_episode),
            "matched": len(matched),
            "renames": (
                [{"from": "01/12FLASH", "to": "01/12LP"}]
                if episode == 1 else []
            ),
            "added": added,
            "removed": removed,
            "content_changed_count": len(content_changed),
            "content_changed": content_changed,
            "title_changed_count": len(title_changed),
            "title_changed": title_changed,
        }
        episodes.append(entry)
        totals["matched"] += len(matched)
        totals["created"] += len(added)
        totals["removed"] += len(removed)
        totals["content_changed"] += len(content_changed)
        totals["title_changed"] += len(title_changed)
    output = {"totals": totals, "episodes": episodes}
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(totals, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
