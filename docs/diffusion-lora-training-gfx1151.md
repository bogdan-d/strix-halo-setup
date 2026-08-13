# Diffusion image gen + LoRA training on Strix Halo (gfx1151)

Two things this box does that the LLM docs don't cover: generating images, and **training**
(fine-tuning) diffusion LoRAs. Both work on gfx1151, but each has one non-obvious trap that
costs hours if you hit it cold. This records the working path and the two traps.

## Image generation: prefer sd.cpp Vulkan over ComfyUI+ROCm

For inference, the leanest and most stable path is **stable-diffusion.cpp built for Vulkan**,
not the ComfyUI + PyTorch/ROCm stack. Vulkan avoids the hipBLASLt code path that can wedge the
GPU ring under some SDXL workloads, and it coexists cleanly with Vulkan llama.cpp servers.

- SDXL 768x768, 20 steps: **~23 s**. Qwen-Image-2512 (Q4_K_M GGUF) 1024x1024 with the 4-step
  Lightning LoRA: **~54 s**. Memory footprint is small; it runs alongside resident LLMs.
- The `sd-cli` binary needs its lib on the path: `LD_LIBRARY_PATH=<sd-cpp-dir>` (the bundled
  `sd-server-wrapper.sh` sets this, but calling `sd-cli` bare does not).
- ⚠ At 1024px the VAE-decode buffer can exceed the Vulkan single-buffer limit
  (`ErrorOutOfDeviceMemory`, ~11 GB) — add `--vae-tiling`. 768px works without it.
- Qwen-Image needs three files (diffusion GGUF + `qwen_image_vae.safetensors` +
  `Qwen2.5-VL-7B-Instruct-Q8_0.gguf` as `--llm`), per the sd.cpp `docs/qwen_image.md`.

## LoRA training: ai-toolkit on a TheRock ROCm venv

[ai-toolkit](https://github.com/ostris/ai-toolkit) trains SDXL, Flux, and Qwen-Image LoRAs and
runs on gfx1151. Install its requirements into a **TheRock ROCm** venv (the same kind used for
the Unsloth/PyTorch work — torch `2.x.0+rocmX.Y...`), not the system Python.

### Trap 1 — torch / torchvision / torchaudio / torchao must be the SAME ROCm build

ai-toolkit's `requirements` pull `torchao`, and its runtime imports `torchvision` + `torchaudio`.
If pip installs the generic PyPI wheels for those, they mismatch your ROCm torch and blow up with:

```
RuntimeError: operator torchvision::nms does not exist
```

which surfaces downstream as a confusing `transformers` failure
(`Could not import module 'PreTrainedModel'`). Fix: install the **matching** torchvision/torchaudio
from the TheRock index, `--no-deps`, with the **exact same build date** as your torch:

```
IDX=https://rocm.nightlies.amd.com/v2/gfx1151/
pip install --no-deps --index-url $IDX "torchvision==<ver>+rocm<...aDATE>" \
                                       "torchaudio==<ver>+rocm<...aDATE>"
pip install --no-deps "torchao==0.10.0"
```

Match the versions to your torch: torch 2.10 → torchvision 0.25 / torchaudio 2.10 (NOT 0.26/2.9 —
string-sort will pick the wrong one). Verify with a combined
`import torch, torchvision, torchaudio` + `torchvision.ops.nms(...)`. Also **exclude the CUDA-only
packages** `bitsandbytes` and `torchcodec` from the install, and in configs use
`optimizer: "adamw"` (not `adamw8bit`, which needs bitsandbytes). SDXL config: `arch: "sdxl"`,
`noise_scheduler: "ddpm"`, `device: cuda:0` (HIP maps to the cuda device string).

### Trap 2 — ⚠ THROTTLE the training job or it freezes the whole desktop

This is the big one. Launched flat-out, a training run's **MIOpen first-run kernel compilation
pegs every CPU core** for minutes (it JIT-compiles GPU kernels on the host). On a single-iGPU APU
that also renders your desktop, this makes the whole GUI go "not responding" — and starves other
processes of CPU entirely (a headless agent on the box stopped answering, because it couldn't get
a scheduler slice). It is **not** a memory problem and **not** a GPU wedge — it's CPU starvation.

Fix: run training inside a CPU-throttled, memory-capped systemd scope that leaves ~1/3 of the
cores free:

```
systemd-run --user --scope -p CPUQuota=2000% -p CPUWeight=10 -p MemoryMax=45G \
  nice -n 19 ionice -c3  <your training command>
```

`CPUQuota=2000%` = 20 of 32 cores' worth (scale to ~60% of `nproc`x100). Verify it took with
`systemctl --user show <unit>.scope -p CPUQuotaPerSecUSec`. With this, observed load dropped from
"all cores pegged, desktop frozen" to **~4-6/32, box 90% idle, GUI + agents fully responsive**,
same job. Prefer `CPUQuota` over `AllowedCPUs` (hard core-pin) — the latter needs cpuset
delegation to the user manager and is often rejected for `--user` scopes.

The MIOpen compile is a **one-time** cost cached under `~/.cache/miopen`; the second run is far
lighter (in one test, latent caching went from ~4 min/image cold to instant warm). Don't redirect
that cache off its default disk.

### Speed reality

gfx1151 is fine for diffusion *inference* but **slow at diffusion training**: SDXL LoRA at 768px
ran ~**90 s/step** here (GPU-bound; the CPU throttle is not the bottleneck, the iGPU is). A short
smoke run is fine, but a real multi-thousand-step fine-tune is a multi-day job on-box. For heavy
training runs a rented CUDA GPU is dramatically faster; a sensible split is **train on CUDA, run
inference on-box** via the sd.cpp Vulkan path above. On-box training works — it's just slow.
