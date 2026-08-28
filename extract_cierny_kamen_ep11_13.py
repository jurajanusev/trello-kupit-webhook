"""Authoritative extraction of Čierny Kameň episodes 11–13 only."""
from __future__ import annotations

import json
from pathlib import Path

import extract_cierny_kamen_ep07_10 as parser


PDFS = {
    11: Path(r"C:\Users\juraj\Desktop\RIVERDALE\SCENARE\SC_01_11_ČK_1.8_NJ_SG_FINAL.pdf"),
    12: Path(r"C:\Users\juraj\Desktop\RIVERDALE\SCENARE\SC_01_12_ČK_1.8_NJ_KL_FINAL.pdf"),
    13: Path(r"C:\Users\juraj\Desktop\RIVERDALE\SCENARE\SC_01_13_ČK_1.4_MV_KC_FINAL.pdf"),
}
EXPECTED = {11: 51, 12: 52, 13: 55}
OUTPUT = Path(__file__).with_name("cierny_kamen_ep11_13_scenes.json")


def build_payload():
    parser.EXPECTED.update(EXPECTED)
    scenes, sources = [], []
    for episode, path in PDFS.items():
        episode_scenes, source = parser.extract(path, episode)
        if len(episode_scenes) != EXPECTED[episode]:
            raise ValueError(f"episode {episode}: {len(episode_scenes)} scenes")
        scenes.extend(episode_scenes)
        sources.append(source)
    ids = [scene["scene_id"] for scene in scenes]
    if len(ids) != 158 or len(set(ids)) != 158:
        raise ValueError(f"expected 158 unique scene IDs, got {len(ids)}/{len(set(ids))}")
    for order, scene in enumerate(scenes):
        scene["order"] = order
    return {
        "project": "Čierny Kameň", "board_ref": "CzuD55PR",
        "source_kind": "three_final_pdfs_ep11_13", "source_pdfs": sources,
        "episode_counts": {str(key): value for key, value in EXPECTED.items()},
        "scenes": scenes,
        "stats": {"scenes": len(scenes), "unique_scene_ids": len(set(ids)),
                  "missing_prepis": sum(not item["prepis"] for item in scenes),
                  "missing_action": sum(not item["action_raw"] for item in scenes)},
    }


if __name__ == "__main__":
    payload = build_payload()
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["stats"], ensure_ascii=True))
