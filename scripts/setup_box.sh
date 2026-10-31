#!/usr/bin/env bash
# Box setup on a Colab G4: ComfyUI and official H3 weights on local disk.
# No Drive, no tunnel, no credentials on the box. Everything is pinned.
# Each part logs to /root/logs/setup-<part>.log and writes /root/logs/<part>.ok when done.
set -uo pipefail
export PATH=$HOME/.local/bin:$PATH HF_HOME=/root/hf HF_XET_HIGH_PERFORMANCE=1
mkdir -p /root/logs /root/h3/weights /root/h3/runs

COMFY_TAG=v0.43.2
COMFY_SHA=423cbd20511becb1f16122ab518e92e58bfa03d9
MOTION_SHA=518c083d11d80fa5920222ad89889924ee4401c9
H3_REV=912b6e38b2092ec4d2e86d24183e0d59ea059d48
REALISM_REV=039cc8579d7aa357a882d7f4111b25da4f72dccc
CLOSEUP_REV=c89656bd0cb71873133dd2c7a925f306a21c633c
# The author's scheme_a stack for the scene runs (scripts/render_job.py). Third-party weights, pinned.
SINGULARITY_REV=1259cf16cd0b655ba691a32fb46a409142762972     # WarmBloodAban/Minimax-h3_Singularity, ref2va Pruned v1.3 int8 (21.0 GB)
HERETIC_REV=0a9486d17cfb20c1a7abc97118c4d95910b9b1f4        # Momoking/Qwen3-VL-32B-Heretic-MiniMax-H3-NVFP4 (15.7 GB)
BUNNY_NODE_SHA=eda12885d461bc52c2361513b7f56b38c03428e4     # aa335615543-ux/BUNNY_H3_Conditioning_Bridge (source read before pinning: torch + safetensors only, no network, no pickle)
BUNNY_WEIGHT_REV=1c46814a7034030920e1d4a6d4e587bf876b7f9c   # JOKER141/BUNNY_H3_Conditioning_Bridge, V2 weights (22 MB)

command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh

part_comfy() {
  git clone -q --filter=blob:none https://github.com/Comfy-Org/ComfyUI.git /root/h3/ComfyUI &&
  git -C /root/h3/ComfyUI checkout -q "$COMFY_SHA" &&
  git clone -q --filter=blob:none https://github.com/NikoDemon80/ComfyUI-H3-Motion-Context.git /root/h3/ComfyUI/custom_nodes/ComfyUI-H3-Motion-Context &&
  git -C /root/h3/ComfyUI/custom_nodes/ComfyUI-H3-Motion-Context checkout -q "$MOTION_SHA" &&
  uv venv /root/venv-comfy --python 3.12 &&
  uv pip install --python /root/venv-comfy/bin/python -r /root/h3/ComfyUI/requirements.txt --torch-backend=auto &&
  uv pip install --python /root/venv-comfy/bin/python soundfile librosa faster-whisper &&
  /root/venv-comfy/bin/python -c "import torch; print('torch', torch.__version__, torch.cuda.get_device_name(0))"
}

part_models() {
  uv venv /root/venv-hf --python 3.12 && uv pip install --python /root/venv-hf/bin/python "huggingface_hub[hf_xet]" &&
  HF=/root/venv-hf/bin/hf &&
  $HF download Comfy-Org/MiniMax-H3 \
      diffusion_models/minimax_h3_ref2va_pruned_bf16.safetensors \
      text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors \
      vae/minimax_h3_video_vae_fp16.safetensors \
      vae/minimax_h3_audio_vae_fp32.safetensors \
      loras/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors \
      --revision $H3_REV --local-dir /root/h3/weights/h3 &&
  $HF download fal/MiniMax-H3-Realism-People-LoRA h3-realism-people-t2v-i2v-r2v.safetensors \
      --revision $REALISM_REV --local-dir /root/h3/weights/realism &&
  $HF download prithivMLmods/MiniMax-H3-Facial-Realism-CloseUp minimax-h3-facial-realism-closeup-cp2000.safetensors \
      --revision $CLOSEUP_REV --local-dir /root/h3/weights/closeup
}

part_scheme_a() {
  uv venv /root/venv-hf-a --python 3.12 2>/dev/null; uv pip install --python /root/venv-hf-a/bin/python "huggingface_hub[hf_xet]" &&
  HF=/root/venv-hf-a/bin/hf &&
  $HF download WarmBloodAban/Minimax-h3_Singularity Minimax-h3_Singularity_ref2va_Pruned_v1.3_int8.safetensors       --revision $SINGULARITY_REV --local-dir /root/h3/weights/singularity &&
  $HF download Momoking/Qwen3-VL-32B-Heretic-MiniMax-H3-NVFP4 qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors       --revision $HERETIC_REV --local-dir /root/h3/weights/heretic &&
  git clone -q --filter=blob:none https://github.com/aa335615543-ux/BUNNY_H3_Conditioning_Bridge.git /root/h3/weights/bunny_node &&
  git -C /root/h3/weights/bunny_node checkout -q "$BUNNY_NODE_SHA" &&
  $HF download JOKER141/BUNNY_H3_Conditioning_Bridge BUNNY_H3_ActionLogic_Bridge_V2.safetensors       --revision $BUNNY_WEIGHT_REV --local-dir /root/h3/weights/bunny_node/models
}

part_fonts() {
  apt-get update -q && apt-get install -y -q fonts-noto-cjk && fc-cache -f
}

part_qc() {  # mediapipe needs an older numpy than ComfyUI, so face checks live in their own venv
  uv venv /root/venv-qc --python 3.11 &&
  uv pip install --python /root/venv-qc/bin/python "mediapipe==0.10.14" opencv-python-headless librosa resemblyzer "numpy<2" "setuptools<81" &&
  MPLBACKEND=Agg /root/venv-qc/bin/python -c "import mediapipe, cv2; print('qc ok', mediapipe.__version__)"
}

t0=$(date +%s)
( part_comfy  > /root/logs/setup-comfy.log  2>&1 && touch /root/logs/comfy.ok;  echo "comfy done rc=$? $(( $(date +%s) - t0 ))s" >> /root/logs/setup.log ) &
( part_models > /root/logs/setup-models.log 2>&1 && touch /root/logs/models.ok; echo "models done rc=$? $(( $(date +%s) - t0 ))s" >> /root/logs/setup.log ) &
( part_scheme_a > /root/logs/setup-scheme_a.log 2>&1 && touch /root/logs/scheme_a.ok; echo "scheme_a done rc=$? $(( $(date +%s) - t0 ))s" >> /root/logs/setup.log ) &
( part_fonts  > /root/logs/setup-fonts.log  2>&1 && touch /root/logs/fonts.ok;  echo "fonts done rc=$? $(( $(date +%s) - t0 ))s" >> /root/logs/setup.log ) &
( part_qc     > /root/logs/setup-qc.log     2>&1 && touch /root/logs/qc.ok;     echo "qc done rc=$? $(( $(date +%s) - t0 ))s" >> /root/logs/setup.log ) &
wait

M=/root/h3/ComfyUI/models
ln -sf /root/h3/weights/h3/diffusion_models/*.safetensors $M/diffusion_models/
ln -sf /root/h3/weights/h3/text_encoders/*.safetensors    $M/text_encoders/
ln -sf /root/h3/weights/h3/vae/*.safetensors              $M/vae/
ln -sf /root/h3/weights/h3/loras/*.safetensors            $M/loras/
ln -sf /root/h3/weights/realism/*.safetensors             $M/loras/
ln -sf /root/h3/weights/closeup/*.safetensors             $M/loras/
ln -sf /root/h3/weights/singularity/*.safetensors         $M/diffusion_models/
ln -sf /root/h3/weights/heretic/*.safetensors             $M/text_encoders/
ln -sfn /root/h3/weights/bunny_node /root/h3/ComfyUI/custom_nodes/BUNNY_H3_Conditioning_Bridge  # cloned outside custom_nodes so it cannot race the ComfyUI clone
du -sh /root/h3/weights >> /root/logs/setup.log
for part in comfy models scheme_a fonts qc; do
  [ -f /root/logs/$part.ok ] || { echo "FAILED: $part" >> /root/logs/setup.log; touch /root/logs/setup.failed; exit 1; }
done
echo "all done $(( $(date +%s) - t0 ))s" >> /root/logs/setup.log
touch /root/logs/setup.done
