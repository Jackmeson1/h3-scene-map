"""ComfyUI on the box: check it is the pinned build, start it, submit graphs, build the H3 clip graph."""

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

COMFY = Path("/root/h3/ComfyUI")
API = "http://127.0.0.1:8188"
WIDTH, HEIGHT = 1344, 768

# Part of every render step's key: changing any of this invalidates what it produced.
ENGINE = {
    "comfy": "423cbd20511becb1f16122ab518e92e58bfa03d9",
    "motion_context": "518c083d11d80fa5920222ad89889924ee4401c9",
    "unet": "minimax_h3_ref2va_pruned_bf16.safetensors",
    "encoder": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
    "video_vae": "minimax_h3_video_vae_fp16.safetensors",
    "audio_vae": "minimax_h3_audio_vae_fp32.safetensors",
    "loras": [
        ["h3-realism-people-t2v-i2v-r2v.safetensors", 0.75],
        ["minimax-h3-facial-realism-closeup-cp2000.safetensors", 0.50],
        ["minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors", 0.75],
    ],
    "steps": 12,
    "shift": [12.0, 3.0],
    "sigma_tail": [3, 0.5],
    "context": [22, 18],
    "join_match": {"strength": 0.35, "min_excess": 2.5, "match_spread": False, "min_excess_spread": 2.5,
                   "match_detail": False, "min_excess_detail": 2.5, "tuning": "manual"},
}


LOCK = Path(__file__).resolve().parent / "engine.lock.json"
MOTION_DIR = COMFY / "custom_nodes" / "ComfyUI-H3-Motion-Context"


def weight_files() -> dict:
    """Every weight file ENGINE names, by file name, with where ComfyUI loads it from."""
    models = COMFY / "models"
    files = {ENGINE["unet"]: models / "diffusion_models", ENGINE["encoder"]: models / "text_encoders",
             ENGINE["video_vae"]: models / "vae", ENGINE["audio_vae"]: models / "vae"}
    for name, _ in ENGINE["loras"]:
        files[name] = models / "loras"
    return {name: folder / name for name, folder in files.items()}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def fingerprint() -> dict:
    """What is actually installed: both git SHAs, whether tracked files were modified, and every weight's size."""
    found = {"weights": {}}
    for label, repo in (("comfy", COMFY), ("motion_context", MOTION_DIR)):
        try:
            found[label] = _git(repo, "rev-parse", "HEAD")
            found[label + "_dirty"] = bool(_git(repo, "status", "--porcelain", "--untracked-files=no"))
        except (OSError, subprocess.CalledProcessError) as exc:
            found[label] = f"unreadable: {exc.__class__.__name__}"
            found[label + "_dirty"] = None
    for name, path in weight_files().items():
        found["weights"][name] = os.stat(path).st_size if path.exists() else None  # follows the symlinks setup makes
    return found


def engine_problems(found: dict, lock: dict) -> list[str]:
    """Differences between what is installed and ENGINE plus the pinned weight sizes. Empty means safe to render."""
    problems = []
    for label in ("comfy", "motion_context"):
        if found[label] != ENGINE[label]:
            problems.append(f"{label} is at {found[label]}, ENGINE pins {ENGINE[label]}")
        if found.get(label + "_dirty"):
            problems.append(f"{label} has modified tracked files")
    pinned = (lock or {}).get("weights", {})
    for name, size in found["weights"].items():
        if size is None:
            problems.append(f"weight {name} is missing")
        elif name not in pinned:
            problems.append(f"weight {name} has no pinned size in engine.lock.json (run make.py --pin-engine on a known-good box)")
        elif pinned[name] != size:
            problems.append(f"weight {name} is {size} bytes, pinned {pinned[name]}")
    return problems


def verify_engine() -> None:
    """Refuse to touch the GPU unless the installed ComfyUI, Motion Context and weights are the pinned ones."""
    lock = json.loads(LOCK.read_text(encoding="utf-8")) if LOCK.exists() else None
    problems = engine_problems(fingerprint(), lock)
    if lock is None:
        problems.append("engine/engine.lock.json is missing (run make.py --pin-engine on a known-good box)")
    if problems:
        raise RuntimeError("engine check failed, refusing to render:\n  " + "\n  ".join(problems))


def pin_engine() -> dict:
    """Record the installed weight sizes. Only allowed when both git SHAs already match ENGINE; the sizes are then
    trusted on first use, since nothing else on disk says what the right sizes are."""
    found = fingerprint()
    problems = [p for p in engine_problems(found, {"weights": found["weights"]})]
    if problems:
        raise RuntimeError("refusing to pin, the install does not match ENGINE:\n  " + "\n  ".join(problems))
    LOCK.write_text(json.dumps({"comfy": ENGINE["comfy"], "motion_context": ENGINE["motion_context"], "weights": found["weights"]}, indent=1), encoding="utf-8")
    return found


def comfy_up() -> bool:
    try:
        urllib.request.urlopen(f"{API}/system_stats", timeout=3)
        return True
    except Exception:
        return False


def start_comfy() -> None:
    if comfy_up():
        return
    out = open("/root/logs/comfyui.log", "a")
    subprocess.Popen(
        ["/root/venv-comfy/bin/python", "main.py", "--listen", "127.0.0.1", "--port", "8188", "--highvram"],
        cwd=COMFY, stdout=out, stderr=subprocess.STDOUT, start_new_session=True,
    )
    for _ in range(180):
        if comfy_up():
            return
        time.sleep(2)
    raise RuntimeError("ComfyUI did not start, see /root/logs/comfyui.log")


def submit(graph: dict, label: str) -> dict:
    body = json.dumps({"prompt": graph}).encode()
    req = urllib.request.Request(f"{API}/prompt", data=body, headers={"Content-Type": "application/json"})
    try:
        resp = json.load(urllib.request.urlopen(req, timeout=30))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{label}: rejected: {exc.read().decode(errors='ignore')[:3000]}") from exc
    if resp.get("node_errors"):
        raise RuntimeError(f"{label}: node errors: {json.dumps(resp['node_errors'], ensure_ascii=False)[:3000]}")
    pid = resp["prompt_id"]
    while True:
        time.sleep(3)
        hist = json.load(urllib.request.urlopen(f"{API}/history/{pid}", timeout=20))
        if pid in hist:
            entry = hist[pid]
            status = entry.get("status", {})
            if status.get("status_str") == "error":
                raise RuntimeError(f"{label}: failed: {json.dumps(status, ensure_ascii=False)[:3000]}")
            return entry


def saved_mp4(entry: dict) -> Path:
    for out in entry["outputs"].values():
        for items in out.values():
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict) and str(item.get("filename", "")).endswith(".mp4"):
                    return COMFY / "output" / item.get("subfolder", "") / item["filename"]
    raise RuntimeError(f"no mp4 in outputs: {json.dumps(entry['outputs'])[:800]}")


def to_input(path: Path) -> str:
    """ComfyUI only loads images and audio from its input folder."""
    name = f"{path.parent.name}_{path.name}"
    shutil.copy2(path, COMFY / "input" / name)
    return name


def stacks() -> dict:
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": ENGINE["unet"], "weight_dtype": "default"}},
        "6": {"class_type": "CLIPLoader", "inputs": {"clip_name": ENGINE["encoder"], "type": "minimax", "device": "default"}},
        "7": {"class_type": "VAELoader", "inputs": {"vae_name": ENGINE["video_vae"]}},
        "8": {"class_type": "VAELoader", "inputs": {"vae_name": ENGINE["audio_vae"]}},
    }
    prev = "1"
    for i, (name, strength) in enumerate(ENGINE["loras"]):
        nid = str(2 + i)
        g[nid] = {"class_type": "LoraLoaderModelOnly",
                  "inputs": {"model": [prev, 0], "lora_name": name, "strength_model": strength}}
        prev = nid
    g["5"] = {"class_type": "MiniMaxH3SigmaShift",
              "inputs": {"model": [prev, 0], "shift_video": ENGINE["shift"][0], "shift_audio": ENGINE["shift"][1]}}
    g["22"] = {"class_type": "BasicScheduler", "inputs": {"model": ["5", 0], "scheduler": "simple", "steps": ENGINE["steps"], "denoise": 1.0}}
    g["23"] = {"class_type": "MiniMaxH3SigmasTail",
               "inputs": {"sigmas": ["22", 0], "tail_steps": ENGINE["sigma_tail"][0], "strength": ENGINE["sigma_tail"][1]}}
    g["24"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}}
    return g


def clip_graph(prompt: str, length: int, seed: int, prefix: str, images=(), audio=None,
               index: int = 0, prev_latent: str = None, latent_prefix: str = None, fps: int = 24) -> dict:
    """index 0 renders a standalone clip; index >= 1 saves a latent, and index >= 2 continues prev_latent."""
    g = stacks()
    inputs = {"clip": ["6", 0], "vae": ["7", 0], "audio_vae": ["8", 0], "width": WIDTH, "height": HEIGHT,
              "length": length, "ref_image_size": "max", "prompt": prompt}
    for i, name in enumerate(images):
        nid = str(10 + i)
        g[nid] = {"class_type": "LoadImage", "inputs": {"image": name}}
        inputs[f"ref_images.ref_image_{i}"] = [nid, 0]
    if audio:
        g["12"] = {"class_type": "LoadAudio", "inputs": {"audio": audio}}
        inputs["ref_audios.ref_audio_0"] = ["12", 0]
    g["20"] = {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": inputs}
    g["25"] = {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}}

    cond, trim, latent = ["20", 0], 0, ["27", 0]
    if index > 1:
        video_ctx, audio_ctx = ENGINE["context"]
        g["41"] = {"class_type": "MiniMaxH3MotionContextLoadLatent", "inputs": {"latent_path": prev_latent, "clip_index": index - 1}}
        g["42"] = {"class_type": "MiniMaxH3MotionContext",
                   "inputs": {"conditioning": ["20", 0], "vae": ["7", 0], "latent": ["20", 1], "context_length": str(video_ctx),
                              "audio_context_length": audio_ctx, "context_latent": ["41", 0]}}
        cond, trim = ["42", 0], ["42", 1]
    g["26"] = {"class_type": "BasicGuider", "inputs": {"model": ["5", 0], "conditioning": cond}}
    g["27"] = {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["25", 0], "guider": ["26", 0], "sampler": ["24", 0], "sigmas": ["23", 0], "latent_image": ["20", 1]}}
    if index > 1:
        g["48"] = {"class_type": "MiniMaxH3JoinMatch",
                   "inputs": {"samples": ["27", 0], "context_length": ["42", 1], "context_latent": ["41", 0], **ENGINE["join_match"]}}
        latent = ["48", 0]
    if index >= 1:
        g["49"] = {"class_type": "MiniMaxH3MotionContextSaveLatent",
                   "inputs": {"latent": latent, "filename_prefix": f"{latent_prefix}/clip", "clip_index": index}}
    g["30"] = {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": latent}}
    g["31"] = {"class_type": "VAEDecode", "inputs": {"samples": ["30", 0], "vae": ["7", 0]}}
    g["32"] = {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["30", 1], "vae": ["8", 0]}}
    g["33"] = {"class_type": "MiniMaxH3MotionContextTrim",
               "inputs": {"images": ["31", 0], "audio": ["32", 0], "trim_frames": trim, "fps": float(fps), "match_tail": True}}
    g["34"] = {"class_type": "CreateVideo", "inputs": {"images": ["33", 0], "audio": ["33", 1], "fps": float(fps)}}
    g["35"] = {"class_type": "SaveVideo", "inputs": {"video": ["34", 0], "filename_prefix": prefix, "format": "mp4", "codec": "h264"}}
    return g
