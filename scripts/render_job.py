#!/usr/bin/env python3
"""Runs on the box: render one scene (or the V9 reproduction, or an asset job) once, with the author's scheme_a stack, and record what happened.

No gates, no retakes, no build cache. A job either writes /root/h3/scene_out/<job>/meta.json (done) or FAILED.json (failed) and exits.

    render_job.py <scene id> <seed>        a scene from scenes/scenes.json
    render_job.py v9 <first seed>          the four-segment V9 graph, with that seed set (his seeds, or his + 1000, or his + 2000)
    render_job.py v9_voiceseed             the no-reference first pass and the voice extraction his way (whitepaper 6.5 (2) step 1)
    render_job.py cast_fighter_a           a new character, the same no-reference casting as before, one frame taken automatically

Graphs are built from his own workflow_v9_final.json: the model stack, scheduler, sigmas, sampler, bridge and JoinMatch nodes are his, copied
node for node. Per scene only the prompt, length, seed, references, LoRA strengths and BUNNY alpha change.
"""
import argparse
import copy
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

H3 = Path("/root/h3")
SCENES = H3 / "scenes" / "scenes.json"
TEMPLATE = H3 / "scenes" / "v9" / "workflow_v9_final.json"
CONFIG = H3 / "scenes" / "v9" / "drama_config.json"
OUT = H3 / "scene_out"
ASSET_OUT = H3 / "scene_assets"
UNET = "Minimax-h3_Singularity_ref2va_Pruned_v1.3_int8.safetensors"
ENCODER = "qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors"

SHARED = ["1", "2", "3", "4", "5", "6", "7", "8", "22", "23", "24"]  # models, LoRAs, sigma shift, scheduler, sigmas tail, sampler select
PROTO_FIRST = ["20", "21", "25", "26", "27", "30", "31", "32", "33", "34", "35"]  # a clip with no motion context
PROTO_NEXT = ["40", "41", "42", "45", "46", "47", "48", "50", "51", "52", "53", "54", "55"]  # a clip continuing the previous one
ASSET_VOICE_FILTER = "afade=t=in:st=0:d=0.02,afade=t=out:st={fade}:d=0.05,pan=stereo|c0=c0|c1=c0"  # whitepaper 6.5 (2) step 1, verbatim


# ---- pure graph building (tested locally, no ComfyUI needed) ---------------------------------------------------------------------------

def instantiate(template: dict, ids: list, tag: str, prev_out: str = None) -> dict:
    """Copy a clip's nodes out of his graph under new ids. A reference to a node outside the copied set stays, except the context latent,
    which becomes the previous clip's output."""
    nodes = {}
    for nid in ids:
        node = copy.deepcopy(template[nid])
        for name, value in node["inputs"].items():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and value[0] in template:
                if value[0] in ids:
                    node["inputs"][name] = [f"{tag}_{value[0]}", value[1]]
                elif name == "context_latent":
                    node["inputs"][name] = [prev_out, 0]
        nodes[f"{tag}_{nid}"] = node
    return nodes


def chain_graph(template: dict, clips: list, seed: int, prefix: str, files: dict) -> tuple[dict, list]:
    """clips: scene clip dicts. files: asset id -> file name inside ComfyUI/input. Returns (graph, [save node id per clip])."""
    graph = {nid: copy.deepcopy(template[nid]) for nid in SHARED}
    first = clips[0]["loras"]
    graph["2"]["inputs"]["strength_model"] = first["realism"]
    graph["3"]["inputs"]["strength_model"] = first["closeup"]
    graph["4"]["inputs"]["strength_model"] = first["turbo"]
    saves, prev_out = [], None
    for i, clip in enumerate(clips, start=1):
        tag = f"c{i}"
        cont = clip["context_from_prev"]
        assert not cont or prev_out, "the first clip cannot continue a previous one"
        ids = PROTO_NEXT if cont else PROTO_FIRST
        nodes = instantiate(template, ids, tag, prev_out)
        r2v, bunny, noise, save, out = (f"{tag}_40", f"{tag}_41", f"{tag}_45", f"{tag}_55", f"{tag}_48") if cont else \
                                       (f"{tag}_20", f"{tag}_21", f"{tag}_25", f"{tag}_35", f"{tag}_27")
        inputs = nodes[r2v]["inputs"]
        for key in [k for k in inputs if k.startswith("ref_images.") or k.startswith("ref_audios.")]:
            del inputs[key]
        for k, asset in enumerate(clip["refs"]):
            nodes[f"{tag}_img{k}"] = {"class_type": "LoadImage", "inputs": {"image": files[asset]}}
            inputs[f"ref_images.ref_image_{k}"] = [f"{tag}_img{k}", 0]
        if clip["voice"]:
            nodes[f"{tag}_aud"] = {"class_type": "LoadAudio", "inputs": {"audio": files[clip["voice"]]}}
            inputs["ref_audios.ref_audio_0"] = [f"{tag}_aud", 0]
        inputs["length"] = clip["frames"]
        inputs["prompt"] = clip["prompt"]
        nodes[bunny]["inputs"]["alpha"] = clip["bunny_alpha"]
        nodes[noise]["inputs"]["noise_seed"] = seed + (i - 1)
        nodes[save]["inputs"]["filename_prefix"] = f"{prefix}_{clip['name']}"
        graph.update(nodes)
        saves.append(save)
        prev_out = out
    return graph, saves


def dangling(graph: dict) -> list:
    """Every reference must point at a node that exists."""
    bad = []
    for nid, node in graph.items():
        for name, value in node["inputs"].items():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and value[0] not in graph:
                bad.append((nid, name, value[0]))
    return bad


def port_taillock(graph: dict, seg3_frames=(107, 136)) -> list:
    """His two tail-lock nodes against the current MiniMaxH3AddGuide: inputs are positive, vae, audio_vae, latent, image, audio, frame_idx and the
    one output is the conditioning (no latent, no strength). Image and frame indices are his. Returns what could not be carried over."""
    lost = []
    for nid, frame in zip(("662", "663"), seg3_frames):
        node = graph[nid]["inputs"]
        node["positive"] = node.pop("conditioning")
        node.pop("latent")  # kept as an input, see below
        node["latent"] = ["60", 1]
        if "strength" in node:
            lost.append(f"node {nid}: strength {node.pop('strength')} dropped, the current node has no strength input and anchors at full weight")
        node["frame_idx"] = frame
    graph["663"]["inputs"]["positive"] = ["662", 0]
    graph["66"]["inputs"]["conditioning"] = ["663", 0]
    graph["67"]["inputs"]["latent_image"] = ["60", 1]  # the old node returned a modified latent, the new one returns only conditioning
    lost.append("the tail lock no longer rewrites the sampler's latent: the old AddGuide returned (conditioning, latent), the current one returns only conditioning")
    lost.append(f"frame_idx 107 is not a multiple of 17; the whitepaper (5.7 section 3) says guides must sit on 17k, 136 does, 107 does not. Kept as he has it")
    return lost


def v9_graph(template: dict, config: dict, seeds: list, prefix: str, only_first_two: bool = False, no_audio: bool = False) -> tuple[dict, list, list]:
    """His V9 graph with his config applied the way his run_drama.py does it (seeds, per-segment save prefix), the unavailable nodes removed
    and the tail lock ported. Returns (graph, save node ids, what could not be carried over)."""
    graph = copy.deepcopy(template)
    lost = []
    for nid in ("901", "902", "903", "904"):  # H3SaveAVLatent: a custom node of his that is not on this box; it only saved checkpoints
        graph.pop(nid, None)
    lost.append("nodes 901-904 (H3SaveAVLatent checkpoints) removed: not installed here, they only wrote resume files and feed nothing")
    for sid, seed in zip(("25", "45", "65", "85"), seeds):
        graph[sid]["inputs"]["noise_seed"] = seed
    for seg, sid in enumerate(("35", "55", "75", "95"), start=1):
        graph[sid]["inputs"]["filename_prefix"] = f"{prefix}_Seg0{seg}"
    for key, nid in (("realism_lora_strength", "2"), ("closeup_lora_strength", "3")):
        graph[nid]["inputs"]["strength_model"] = config[key]
    for nid in ("21", "41", "61", "81"):
        graph[nid]["inputs"]["alpha"] = config["bunny_alpha"]
    lost += port_taillock(graph) if not only_first_two else []
    if only_first_two:
        keep = {nid for nid in graph if nid in SHARED or nid in ("10", "11", "12", "13") or 20 <= int(nid) < 60}
        graph = {nid: graph[nid] for nid in graph if nid in keep}
    if no_audio:
        for nid in ("20", "40"):
            inputs = graph[nid]["inputs"]
            inputs.pop("ref_audios.ref_audio_0", None)
            inputs["prompt"] = strip_audio_reference(inputs["prompt"])
        for nid in ("12", "13", "14"):
            graph.pop(nid, None)
    saves = ["35", "55"] if only_first_two else ["35", "55", "75", "95"]
    return graph, saves, lost


def strip_audio_reference(prompt: str) -> str:
    """The same prompt with every mention of the reference audio removed, for the first pass that has no reference audio."""
    p = "\n".join(line for line in prompt.split("\n") if not line.startswith("<Audio 1>"))
    p = p.replace("[reference generation + audio reference]", "[reference generation]")
    p = re.sub(r",? ?(using|guided by) the vocal timbre of <Audio 1>", "", p)
    p = re.sub(r" referenced from <Audio 1>", "", p)
    p = re.sub(r",? while preserving her exact female vocal identity from <Audio 1>", "", p)
    p = re.sub(r",? while preserving his exact baritone vocal identity from <Audio 1>", "", p)
    p = re.sub(r"\s*preserving her exact female vocal identity from <Audio 1>", "", p)
    assert "<Audio" not in p, [m for m in re.findall(r"[^.]*<Audio[^.]*", p)]
    return p


# ---- measurements ----------------------------------------------------------------------------------------------------------------------

def volume_db(path: Path) -> dict:
    err = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-vn", "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True).stderr
    mean, peak = re.search(r"mean_volume: (-?[\d.]+) dB", err), re.search(r"max_volume: (-?[\d.]+) dB", err)
    return {"mean_db": float(mean.group(1)) if mean else None, "max_db": float(peak.group(1)) if peak else None}


def frame_stats(path: Path) -> dict:
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-vf", "scale=168:96", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    v = np.frombuffer(raw, np.uint8).reshape(-1, 96, 168, 3).astype(np.float32)
    adj = np.abs(v[1:] - v[:-1]).mean(axis=(1, 2, 3))
    two_hz = v[::12]
    drift = np.abs(two_hz - v[0]).mean(axis=(1, 2, 3))
    return {"frames": int(len(v)), "adjacent_mean": round(float(adj.mean()), 2), "adjacent_max": round(float(adj.max()), 2),
            "adjacent_over_15": int((adj > 15).sum()), "drift_from_first_frame_2hz": [round(float(x), 1) for x in drift]}


def video_seconds(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout.strip().rstrip(",")
    return int(out) / 24.0


class VramPeak(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.peak, self.stop = 0, False

    def run(self):
        while not self.stop:
            try:
                out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10).stdout
                self.peak = max(self.peak, int(out.split()[0]))
            except Exception:
                pass
            time.sleep(2)


def measure_clip(path: Path, dialogue: bool) -> dict:
    row = {"file": path.name, "video_seconds": video_seconds(path), **volume_db(path), "frame_stats": frame_stats(path)}
    if dialogue:
        from engine.transcribe import transcribe
        words = transcribe(path)
        row["transcript_blind"] = "".join(w["word"] for w in words)
        row["words"] = [[w["word"], round(w["start"], 2), round(w["end"], 2)] for w in words]
    return row


# ---- running on the box ----------------------------------------------------------------------------------------------------------------

def comfy_names() -> tuple:
    from engine import comfy
    m = comfy.COMFY / "models"
    for path in (m / "diffusion_models" / UNET, m / "text_encoders" / ENCODER):
        if not path.exists():
            raise RuntimeError(f"missing {path.name}: the scheme_a stack is not installed, and there is no fallback")
    return comfy


def stage(comfy, asset_defs: dict, wanted: list) -> dict:
    """Copy each asset into ComfyUI/input and return asset id -> input file name."""
    import shutil
    files = {}
    for asset in wanted:
        src = H3 / asset_defs[asset]["file"]
        if not src.exists():
            raise RuntimeError(f"asset {asset} is missing at {src}")
        name = f"{asset}{src.suffix}"
        shutil.copy2(src, comfy.COMFY / "input" / name)
        files[asset] = name
    return files


def run_graph(comfy, graph: dict, label: str, saves: list) -> dict:
    t0 = time.time()
    entry = comfy.submit(graph, label)
    seconds = round(time.time() - t0, 1)
    found = {}
    for nid, out in entry["outputs"].items():
        for items in out.values():
            for item in items if isinstance(items, list) else []:
                if isinstance(item, dict) and str(item.get("filename", "")).endswith(".mp4"):
                    found[nid] = comfy.COMFY / "output" / item.get("subfolder", "") / item["filename"]
    missing = [s for s in saves if s not in found]
    if missing:
        raise RuntimeError(f"no video from node(s) {missing}: {json.dumps(entry['outputs'])[:600]}")
    return {"seconds": seconds, "videos": {s: found[s] for s in saves}}


def finish(job_dir: Path, meta: dict) -> None:
    (job_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")


def job_scene(defs: dict, scene_id: str, seed: int) -> dict:
    import shutil
    scene = next(s for s in defs["scenes"] if s["id"] == scene_id)
    assert seed in scene["seeds"], f"{seed} is not one of the fixed seeds {scene['seeds']}"
    job_dir = OUT / f"{scene_id}__{seed}"
    comfy = comfy_names()
    wanted = sorted({a for c in scene["clips"] for a in c["refs"] + ([c["voice"]] if c["voice"] else [])})
    files = stage(comfy, defs["assets"], wanted)
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    graph, saves = chain_graph(template, scene["clips"], seed, f"scenes/{job_dir.name}", files)
    bad = dangling(graph)
    if bad:
        raise RuntimeError(f"graph has dangling references: {bad}")
    comfy.start_comfy()
    vram = VramPeak()
    vram.start()
    result = run_graph(comfy, graph, job_dir.name, saves)
    vram.stop = True
    clips = []
    for clip, save in zip(scene["clips"], saves):
        dst = job_dir / f"{clip['name']}.mp4"
        shutil.copy2(result["videos"][save], dst)
        (job_dir / f"{clip['name']}.prompt.txt").write_text(clip["prompt"], encoding="utf-8")
        row = {"name": clip["name"], "frames": clip["frames"], "intent": clip["intent"], "bunny_alpha": clip["bunny_alpha"], "loras": clip["loras"]}
        clips.append({**row, **measure_clip(dst, scene["dialogue"] and bool(clip["voice"]))})
    return {"job": job_dir.name, "kind": "scene", "scene": scene_id, "seed": seed, "render_seconds": result["seconds"], "peak_vram_mb": vram.peak,
            "total_frames": scene["total_frames"], "clips": clips, "claims": scene["claims"]}


def job_v9(defs: dict, first_seed: int) -> dict:
    import shutil
    v9 = defs["v9"]
    seeds = next(s for s in v9["seed_sets"] if s[0] == first_seed)
    job_dir = OUT / f"v9__{first_seed}"
    comfy = comfy_names()
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    # his workflow loads images and audio by file name from ComfyUI/input
    names = {"10": "author_linwei", "11": "author_chenmo", "14": "author_linwei_profile", "661": "author_taillock", "12": "author_linwei_voice", "13": "author_chenmo_voice"}
    files = stage(comfy, defs["assets"], list(names.values()))
    graph, saves, lost = v9_graph(template, config, seeds, f"scenes/{job_dir.name}")
    for nid, asset in names.items():
        key = "audio" if nid in ("12", "13") else "image"
        graph[nid]["inputs"][key] = files[asset]
    bad = dangling(graph)
    if bad:
        raise RuntimeError(f"graph has dangling references: {bad}")
    comfy.start_comfy()
    vram = VramPeak()
    vram.start()
    result = run_graph(comfy, graph, job_dir.name, saves)
    vram.stop = True
    clips = []
    for n, save in enumerate(saves, start=1):
        dst = job_dir / f"seg{n}.mp4"
        shutil.copy2(result["videos"][save], dst)
        clips.append({"name": f"seg{n}", "speaker": config["segments"][n - 1]["speaker"], "line": config["segments"][n - 1]["line"], **measure_clip(dst, True)})
    return {"job": job_dir.name, "kind": "v9", "seeds": seeds, "render_seconds": result["seconds"], "peak_vram_mb": vram.peak, "clips": clips,
            "not_carried_over": lost, "claims": v9["claims"]}


def job_voiceseed(defs: dict) -> dict:
    import shutil
    seg = defs["voiceseed"]
    job_dir = OUT / "v9_voiceseed"
    comfy = comfy_names()
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    files = stage(comfy, defs["assets"], ["author_linwei", "author_chenmo"])
    graph, saves, _ = v9_graph(template, config, seg["seeds"] + [0, 0], "scenes/v9_voiceseed", only_first_two=True, no_audio=True)
    graph["10"]["inputs"]["image"], graph["11"]["inputs"]["image"] = files["author_linwei"], files["author_chenmo"]
    bad = dangling(graph)
    if bad:
        raise RuntimeError(f"graph has dangling references: {bad}")
    comfy.start_comfy()
    result = run_graph(comfy, graph, "v9_voiceseed", saves)
    ASSET_OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, save, start, length in (("native_linwei_seed_stereo.wav", "35", 0.85, 3.20), ("native_chenmo_seed_stereo.wav", "55", 1.05, 3.90)):
        src = job_dir / f"{name[7:13]}_pass.mp4"
        shutil.copy2(result["videos"][save], src)
        dst = ASSET_OUT / name
        fade = f"{length - 0.05:.2f}"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(start), "-t", str(length), "-i", str(src), "-vn", "-af", ASSET_VOICE_FILTER.format(fade=fade),
                        "-ar", "32000", "-ac", "2", "-acodec", "pcm_s16le", str(dst)], check=True)
        shutil.copy2(dst, job_dir / name)
        from engine.transcribe import transcribe
        words = transcribe(dst)
        rows.append({"asset": name, "ss": start, "t": length, **volume_db(dst), "transcript_blind": "".join(w["word"] for w in words)})
    return {"job": "v9_voiceseed", "kind": "voiceseed", "render_seconds": result["seconds"], "assets": rows}


def job_cast(defs: dict, job_id: str) -> dict:
    import shutil
    from engine import comfy
    from engine.prompts import cast_prompt
    cast = next(c for c in defs["casts"] if c["id"] == job_id)
    comfy_names()
    comfy.ENGINE = {**comfy.ENGINE, "unet": UNET, "encoder": ENCODER}  # stacks() reads the module's ENGINE
    prompt = cast_prompt({"scene": cast["scene"], "style": cast["style"]}, cast["who"])
    comfy.start_comfy()
    entry = run_graph_plain(comfy, comfy.clip_graph(prompt, 124, cast["seed"], f"scenes/{job_id}/clip"), job_id)
    job_dir = OUT / job_id
    shutil.copy2(entry["path"], job_dir / "clip.mp4")
    ASSET_OUT.mkdir(parents=True, exist_ok=True)
    png = ASSET_OUT / f"{cast['asset']}.png"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "4.8", "-i", str(job_dir / "clip.mp4"), "-frames:v", "1", str(png)], check=True)
    shutil.copy2(png, job_dir / png.name)
    (job_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    return {"job": job_id, "kind": "cast", "render_seconds": entry["seconds"], "asset": png.name}


def run_graph_plain(comfy, graph: dict, label: str) -> dict:
    t0 = time.time()
    entry = comfy.submit(graph, label)
    return {"seconds": round(time.time() - t0, 1), "path": comfy.saved_mp4(entry)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("job")
    ap.add_argument("seed", nargs="?", type=int)
    args = ap.parse_args()
    sys.path.insert(0, str(H3))
    defs = json.loads(SCENES.read_text(encoding="utf-8"))
    job_name = args.job if args.job.startswith(("cast_", "v9_voiceseed")) else f"{args.job}__{args.seed}"
    job_dir = OUT / job_name
    import shutil
    if job_dir.exists():
        shutil.rmtree(job_dir)
    job_dir.mkdir(parents=True)
    t0 = time.time()
    try:
        if args.job == "v9":
            meta = job_v9(defs, args.seed)
        elif args.job == "v9_voiceseed":
            meta = job_voiceseed(defs)
        elif args.job.startswith("cast_"):
            meta = job_cast(defs, args.job)
        else:
            meta = job_scene(defs, args.job, args.seed)
    except BaseException as exc:  # noqa: BLE001 - whatever happens, the worker must be told
        (job_dir / "FAILED.json").write_text(json.dumps({"job": job_name, "error": f"{exc.__class__.__name__}: {exc}"[:3000], "seconds": round(time.time() - t0, 1)}), encoding="utf-8")
        print(f"FAILED {job_name}: {exc}")
        return 1
    meta["wall_seconds"] = round(time.time() - t0, 1)
    finish(job_dir, meta)
    print(f"DONE {job_name} render {meta['render_seconds']}s wall {meta['wall_seconds']}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
