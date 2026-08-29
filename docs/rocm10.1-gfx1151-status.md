# ROCm 10.1 on gfx1151 (Strix Halo) — status 2026-08-29

**TL;DR — ROCm 10.1 (via TheRock) installs and its SDK self-test passes, but the PyTorch
wheel has NO compiled gfx1151 kernels: GPU compute fails with `hipErrorInvalidKernelFile`.
Stay on the ROCm 7.15 stack (torch `2.14.0+rocm7.15`, which works). Re-check when
TheRock/community ship gfx1151-validated 10.1 wheels.** Tested 2 days after ROCm 10 GA.

## What was tested

Installed TheRock ROCm 10.1.0 into a clean python3.12 venv:

```bash
pip install --index-url https://nightly.repo.amd.com/rocm/whl-next/ "rocm[libraries,device-gfx1151]"
# -> rocm-10.1.0a20260829
rocm-sdk test      # 19/19 OK
rocm-sdk targets   # lists gfx1151
```

⚠ **`rocm-sdk test` (19/19) and `rocm-sdk targets` prove nothing about GPU compute.**
Those tests are CPU-side only — shared-library load, install layout, console scripts. None
run a GPU kernel. "targets lists gfx1151" is a *declared* arch, not evidence of working kernels.

PyTorch for ROCm 10.1:

```bash
pip install --index-url https://nightly.repo.amd.com/rocm/whl-next/ torch torchvision torchaudio
# -> torch-2.14.0+rocm10.1.0a20260829, triton-3.8.0+...rocm10.1, torchvision-0.28.0+rocm10.1,
#    torchaudio-2.11.0.3+rocm10.1  (all cp312)
```

```python
import torch
torch.cuda.is_available()          # True
torch.cuda.get_device_name(0)      # 'AMD Radeon 8060S Graphics'   <- detects the iGPU
x = torch.randn(1024, 1024, device='cuda'); (x @ x).sum()
# torch.AcceleratorError: CUDA error: invalid kernel file  (hipErrorInvalidKernelFile)
```

Clean venv (no 7.15 remnants). In a *mixed* 7.15/10.1 environment it SIGSEGVs instead — same
root cause. The install also flags the conflict directly:
`rocm-sdk-device-gfx1151 7.15.0a requires rocm-sdk-libraries==7.15.0a, but you have 10.1.0a`.

## Why

`invalid kernel file` = the wheel's GPU code objects don't include a **gfx1151 (RDNA 3.5)**
target. AMD's *generic* ROCm 10.1 torch was built for datacenter arches. **gfx1151 is not on
AMD's official ROCm support matrix** — it's consumer, community/best-effort, and its support is
added *per ROCm version* by community/TheRock work (7.2 → 7.13 → 7.15 each needed it). 10.1's
gfx1151 kernels simply aren't built/validated yet, 2 days after GA. Not a regression — just
not brought up yet.

## Working stack (unchanged)

`torch 2.14.0+rocm7.15.0a` (kyuz0 gfx1151-tuned) — `torch.cuda` matmul verified, drives the
ComfyUI / MiniMax-H3 video and the LoRA fine-tune stacks. That remains the pin.

## Refs
- https://github.com/ROCm/ROCm/issues/6034 — gfx1151: 93 ML experiments, bf16 bugs
- https://github.com/kyuz0/amd-strix-halo-pytorch-gfx1151-aotriton
- https://github.com/ROCm/TheRock/discussions/655 — self-contained gfx1151 wheels
