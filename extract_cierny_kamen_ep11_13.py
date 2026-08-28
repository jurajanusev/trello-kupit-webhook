"""Authoritative extraction of Čierny Kameň episodes 11–13 only."""
from __future__ import annotations

import json
import hashlib
import re
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
    repair_parallel_scenes(scenes)
    return {
        "project": "Čierny Kameň", "board_ref": "CzuD55PR",
        "source_kind": "three_final_pdfs_ep11_13", "source_pdfs": sources,
        "episode_counts": {str(key): value for key, value in EXPECTED.items()},
        "scenes": scenes,
        "stats": {"scenes": len(scenes), "unique_scene_ids": len(set(ids)),
                  "missing_prepis": sum(not item["prepis"] for item in scenes),
                  "missing_action": sum(not item["action_raw"] for item in scenes)},
    }


def _set_actions(by_id, assignments):
    for scene_id, blocks in assignments.items():
        raw = "\n\n".join(blocks).strip()
        if not raw or raw.casefold() == "paralelne":
            raise ValueError(f"{scene_id}: empty parallel scene")
        by_id[scene_id]["action_raw"] = raw
        by_id[scene_id]["action_markdown"] = parser.raw_to_markdown(raw)
        by_id[scene_id]["action_sha256"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _blocks(text):
    text = re.sub(r"(\([^)]*prestrih[^)]*\))", r"\n\n\1", text, flags=re.I)
    return [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()]


def repair_parallel_scenes(scenes):
    """Split explicitly intercut scenes instead of leaving PARALELNE cards empty."""
    by_id = {scene["scene_id"]: scene for scene in scenes}

    # 11/01-04 are carried by the final numbered segment 11/04.
    out = {key: [] for key in ("11/01", "11/02", "11/03", "11/04")}
    current = "11/01"
    for block in _blocks(by_id["11/04"]["action_raw"]):
        key = block.casefold()
        if "prestrih" in key and "dogy sedí" in key:
            current = "11/02"
        elif "prestrih" in key and "baby" in key:
            current = "11/01"
        elif "prestrih" in key and "chalani" in key:
            current = "11/03"
        elif "prestrih" in key and "bety je v riaditeľni" in key:
            current = "11/04"
        out[current].append(block)
    _set_actions(by_id, out)

    # Ples and police search, 11/37-43, are carried by 11/43.
    out = {key: [] for key in ("11/37", "11/38", "11/39LP", "11/40LP", "11/41", "11/42", "11/43")}
    current = "11/37"
    for block in _blocks(by_id["11/43"]["action_raw"]):
        key = block.casefold()
        if "prestrih do andyho bytu" in key and "sedí za stolom" in key:
            current = "11/39LP"
        elif "prestrih pred ubytovňu" in key:
            current = "11/40LP"
        elif "andy otvára dvere" in key or "policajti pokračujú" in key or "policajt pri prehliadke" in key or "keler nesie kufrík" in key:
            current = "11/41"
        elif "prestrih na ples-pódium" in key:
            current = "11/38"
        elif "prestrih na ples-hľadisko" in key or "prestrih na ples)" in key:
            current = "11/42"
        elif "prestrih na chodbu" in key:
            current = "11/43"
        out[current].append(block)
    _set_actions(by_id, out)

    # River rescue, 13/31-35, is carried by 13/35.
    blocks = _blocks(by_id["13/35"]["action_raw"])
    out = {key: [] for key in ("13/31", "13/32", "13/33", "13/34", "13/35")}
    for index, block in enumerate(blocks):
        if index <= 6 or 9 <= index <= 10 or 12 <= index <= 17 or 19 <= index <= 23:
            target = "13/31"
        elif index in {7, 8, 11}:
            target = "13/32"
        elif index in {18, 26}:
            target = "13/33"
        elif 24 <= index <= 31:
            target = "13/34"
        else:
            target = "13/35"
        out[target].append(block)
    _set_actions(by_id, out)

    # Podcast and listeners, 13/40-45, are carried by 13/45.
    out = {key: [] for key in ("13/40", "13/41LP", "13/42LP", "13/43LP", "13/44LP", "13/45")}
    current = "13/40"
    for block in _blocks(by_id["13/45"]["action_raw"]):
        key = block.casefold()
        if "prestrih k révayovcom" in key:
            current = "13/41LP"
        elif "prestrih do betinho domu" in key:
            current = "13/42LP"
        elif "prestrih do alexovej izby" in key:
            current = "13/43LP"
        elif "prestrih na policajnú stanicu" in key:
            current = "13/44LP"
        elif "prestrih k fefemu" in key:
            current = "13/45"
        elif "prestrih do redakcie" in key:
            current = "13/40"
        out[current].append(block)
    _set_actions(by_id, out)


if __name__ == "__main__":
    payload = build_payload()
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["stats"], ensure_ascii=True))
