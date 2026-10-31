"""The scene definitions, the graph builder and the rating pack. No GPU, no network."""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import render_job as rj  # noqa: E402

if not (ROOT / "scenes" / "scenes.json").exists():
    pytest.skip("the scene definitions are not in this repo (see docs/scenes.md)", allow_module_level=True)

DEFS = json.loads((ROOT / "scenes" / "scenes.json").read_text(encoding="utf-8"))
TEMPLATE = json.loads((ROOT / "scenes" / "v9" / "workflow_v9_final.json").read_text(encoding="utf-8"))
CONFIG = json.loads((ROOT / "scenes" / "v9" / "drama_config.json").read_text(encoding="utf-8"))
SECTIONS = ["subject_definitions:", "summary:", "retention_analysis:", "detailed_description:", "overall_soundscape:", "non_diegetic_music:"]
FILES = {a: f"{a}.png" for a in DEFS["assets"]}


def clips():
    return [(s, c) for s in DEFS["scenes"] for c in s["clips"]]


def test_the_matrix_has_the_ten_scenes_with_three_fixed_seeds_each():
    assert [s["id"] for s in DEFS["scenes"]] == ["s01_monologue_cu", "s02_dialogue_two_shot", "s03_ots_reverse_pair", "s04_walk_and_talk", "s05_outburst_push_in",
                                                  "s06_stand_up_compensation", "s07_reaction_cu", "s08_two_fighters", "s09_solo_dance", "s10_hands_tea"]
    assert all(len(s["seeds"]) == 3 and len(set(s["seeds"])) == 3 for s in DEFS["scenes"])
    assert len({x for s in DEFS["scenes"] for x in s["seeds"]}) == 30


def test_frames_are_legal_and_match_the_brief():
    frames = {s["id"]: [c["frames"] for c in s["clips"]] for s in DEFS["scenes"]}
    assert frames["s01_monologue_cu"] == [141] and frames["s02_dialogue_two_shot"] == [141] and frames["s03_ots_reverse_pair"] == [141, 141]
    assert frames["s04_walk_and_talk"] == [192] and frames["s05_outburst_push_in"] == [141] and frames["s06_stand_up_compensation"] == [141]
    assert frames["s07_reaction_cu"] == [90] and frames["s08_two_fighters"] == [192, 192] and frames["s09_solo_dance"] == [294] and frames["s10_hands_tea"] == [192]
    for _, c in clips():
        assert c["frames"] % 17 == 5


@pytest.mark.parametrize("scene,clip", clips(), ids=lambda x: x["id"] if "clips" in x else x["name"])
def test_every_prompt_is_in_the_six_part_structure(scene, clip):
    p = clip["prompt"]
    positions = [p.index(h) for h in SECTIONS]
    assert positions == sorted(positions)
    assert clip["music"] in p
    assert "<Subject 1>" in p
    assert not re.search(r"blood|bleed|gore|wound", p, re.I)  # non-graphic content rule
    if clip["voice"]:
        assert "<Audio 1>" in p and "[reference generation + audio reference]" in p and p.count("<d>[Mandarin]") == 1
    else:
        assert "<Audio" not in p and "<d>" not in p


def test_each_clip_names_a_camera_in_the_official_vocabulary_or_the_author_template():
    vocab = re.compile(r"holds a (completely )?static shot|pushes in|pulls out|tilts up|tracks|moves in an arc shot|shakes slightly|handheld camera")
    for _, c in clips():
        assert vocab.search(c["prompt"]), c["name"]


def test_action_scenes_use_the_action_settings_and_only_those():
    for s in DEFS["scenes"]:
        for c in s["clips"]:
            action = s["id"] in ("s08_two_fighters", "s09_solo_dance")
            assert c["loras"]["closeup"] == (0.15 if action else 0.50)
            assert c["bunny_alpha"] == (0.22 if action else 0.10)
            assert c["loras"]["realism"] == 0.75 and c["loras"]["turbo"] == 0.75
    fight = DEFS["scenes"][7]["clips"]
    assert [c["voice"] for c in fight] == [None, None] and fight[1]["context_from_prev"] and not fight[0]["context_from_prev"]
    assert "percussion" in fight[0]["music"] and "00:06.600" in fight[0]["prompt"]


def test_fight_text_is_the_whitepaper_text_verbatim():
    wp = (Path(ROOT / "scenes" / "v9" / "whitepaper.md"))
    if not wp.exists():
        pytest.skip("whitepaper not on this machine")
    text = wp.read_text(encoding="utf-8")
    fight = DEFS["scenes"][7]["clips"]
    for c in fight:
        for line in c["prompt"].split("\n"):
            if line.startswith(("Immediately during", "During 00:0", "[Shot 1]", "<Subject")):
                assert line in text, line[:80]


def test_v9_prompts_are_the_author_graph_prompts_and_the_dialogue_family_stays_in_its_windows():
    assert DEFS["v9"]["seed_sets"][0] == [2026102201, 2026102202, 2026102609, 2026102204]
    assert DEFS["v9"]["seed_sets"][1] == [s + 1000 for s in DEFS["v9"]["seed_sets"][0]]
    for seg, nid in zip(CONFIG["segments"], ("20", "40", "60", "80")):
        assert f"<d>[Mandarin]{seg['line']}</d>" in TEMPLATE[nid]["inputs"]["prompt"]
        assert TEMPLATE[{"20": "25", "40": "45", "60": "65", "80": "85"}[nid]]["inputs"]["noise_seed"] == seg["seed"]


@pytest.mark.parametrize("scene", DEFS["scenes"], ids=lambda s: s["id"])
def test_every_scene_builds_a_complete_graph(scene):
    graph, saves = rj.chain_graph(TEMPLATE, scene["clips"], scene["seeds"][0], "p", FILES)
    assert rj.dangling(graph) == [] and len(saves) == len(scene["clips"])
    assert graph["2"]["inputs"]["strength_model"] == scene["clips"][0]["loras"]["realism"]
    for clip, save in zip(scene["clips"], saves):
        tag = save.split("_")[0]
        r2v = graph[f"{tag}_40"] if clip["context_from_prev"] else graph[f"{tag}_20"]
        assert r2v["inputs"]["length"] == clip["frames"] and r2v["inputs"]["prompt"] == clip["prompt"]
        assert ("ref_audios.ref_audio_0" in r2v["inputs"]) == bool(clip["voice"])
        assert sum(k.startswith("ref_images.") for k in r2v["inputs"]) == len(clip["refs"])


def test_the_second_fight_clip_continues_the_first_inside_one_graph():
    graph, saves = rj.chain_graph(TEMPLATE, DEFS["scenes"][7]["clips"], DEFS["scenes"][7]["seeds"][0], "p", FILES)
    assert graph["c2_42"]["inputs"]["context_latent"] == ["c1_27", 0]
    assert graph["c2_48"]["inputs"]["context_latent"] == ["c1_27", 0]
    assert graph["c2_48"]["inputs"]["match_spread"] is False and graph["c2_48"]["inputs"]["tuning"] == "manual"


def test_v9_graph_is_his_with_the_tail_lock_ported_and_the_losses_listed():
    graph, saves, lost = rj.v9_graph(TEMPLATE, CONFIG, DEFS["v9"]["seed_sets"][0], "p")
    assert saves == ["35", "55", "75", "95"] and rj.dangling(graph) == []
    assert not any(n in graph for n in ("901", "902", "903", "904"))
    for nid in ("662", "663"):
        assert "strength" not in graph[nid]["inputs"] and "positive" in graph[nid]["inputs"] and "conditioning" not in graph[nid]["inputs"]
    assert graph["662"]["inputs"]["frame_idx"] == 107 and graph["663"]["inputs"]["frame_idx"] == 136
    assert graph["66"]["inputs"]["conditioning"] == ["663", 0] and graph["67"]["inputs"]["latent_image"] == ["60", 1]
    assert graph["22"]["inputs"]["steps"] == 12 and graph["24"]["inputs"]["sampler_name"] == "res_multistep"
    assert graph["6"]["inputs"]["clip_name"] == rj.ENCODER and graph["1"]["inputs"]["unet_name"] == rj.UNET
    assert any("strength" in x for x in lost) and any("17" in x for x in lost)


def test_the_no_reference_first_pass_removes_every_audio_mention_and_keeps_two_segments():
    graph, saves, _ = rj.v9_graph(TEMPLATE, CONFIG, [1, 2, 0, 0], "p", only_first_two=True, no_audio=True)
    assert saves == ["35", "55"] and rj.dangling(graph) == []
    for nid in ("20", "40"):
        assert "<Audio" not in graph[nid]["inputs"]["prompt"] and "ref_audios.ref_audio_0" not in graph[nid]["inputs"]
        assert "<d>[Mandarin]" in graph[nid]["inputs"]["prompt"]
    assert not any(int(n) >= 60 for n in graph)


def test_voice_extraction_filter_is_his_verbatim():
    assert rj.ASSET_VOICE_FILTER.format(fade="3.15") == "afade=t=in:st=0:d=0.02,afade=t=out:st=3.15:d=0.05,pan=stereo|c0=c0|c1=c0"


def test_every_asset_has_a_producer_that_exists():
    ids = {c["id"] for c in DEFS["casts"]} | {"v9_voiceseed", "repo"}
    for name, a in DEFS["assets"].items():
        assert a["producer"] in ids, name
        if a["producer"] == "repo":
            assert (ROOT / a["file"]).exists(), a["file"]


def test_the_rating_pack_lists_scenes_claims_and_clips(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("needs ffmpeg")
    shutil.copytree(ROOT / "scenes", tmp_path / "scenes", ignore=shutil.ignore_patterns("assets"))
    scene = DEFS["scenes"][6]
    job = tmp_path / "scene_results" / f"{scene['id']}__{scene['seeds'][0]}"
    job.mkdir(parents=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=24:d=3.75", "-f", "lavfi", "-i", "sine=d=3.75", "-shortest", str(job / "clip1.mp4")], check=True)
    meta = {"job": job.name, "render_seconds": 61.0, "peak_vram_mb": 70000, "wall_seconds": 90.0,
            "clips": [{"name": "clip1", "file": "clip1.mp4", "frames": 90, "mean_db": -20.0, "max_db": -3.0, "transcript_blind": "什么他签字了",
                       "frame_stats": {"adjacent_max": 3.0, "adjacent_over_15": 0, "drift_from_first_frame_2hz": [0.0, 5.0]}}]}
    (job / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "rate_pack.py"), str(tmp_path)], check=True, capture_output=True)
    index = (tmp_path / "scene_results" / "index.md").read_text(encoding="utf-8")
    assert "## s07_reaction_cu" in index and "- [ ] Sampling for a 90-frame clip" in index and "render 61.0s" in index
    assert (job / "clip1_grid.jpg").exists() and "not rendered" in index
