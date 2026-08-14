# Strix Halo Local AI Setup

Local LLM/VLM + image/video generation + NPU inference for AMD Strix Halo APU (Ryzen AI MAX+ 395, Radeon 8060S iGPU, XDNA2 NPU) with 128GB unified LPDDR5X (124GiB visible to Linux; the iGPU addresses up to 108GiB of it via GTT — capped on purpose, see boot parameters).

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  GPU (Vulkan RADV + ROCm toolboxes — GTT capped at 108GiB)      │
│  ├─ llama-server (Vulkan, llama.cpp)     port 8001               │
│  │  └─ Qwen3.6-35B-A3B MTP (UD-Q4_K_XL, primary; 256k-capable,  │
│  │     run at 128k ctx). Switchable: Qwen3.6-27B / Gemma / DS4  │
│  ├─ llama-server-qwen38 (Vulkan)        port 8022               │
│  │  └─ Qwen3.8-27B VL + native MTP (UD-Q4_K_XL + mmproj-F16)    │
│  │     second resident: vision + writing. Replaced Muse-Glimmer │
│  ├─ ComfyUI (ROCm toolbox)             port 7860               │
│  │  └─ Image/video gen (Wan 2.2, HunyuanVideo, Qwen Image)     │
│  ├─ llama-surya2 (ROCm toolbox)        port 8093 (on-demand)   │
│  │  └─ Surya 2 OCR VLM 650M (document OCR)                      │
│  └─ surya-server (podman, dedicated)   port 8090 (legacy)      │
│     └─ Surya v1 layout+OCR                                      │
│                                                                  │
│  NPU (XDNA2 — 51 TOPS, 47μs latency)                           │
│  └─ FastFlowLM (flm-asr.service)        port 52625 (on-demand)  │
│     └─ Whisper STT for Jarvis (off CPU) + small LLMs           │
└──────────────────────────────────────────────────────────────────┘
```

All GPU services run as **systemd user services**; the two resident LLM servers (:8001, :8022) and ComfyUI auto-start on boot, the rest start on demand.

## Hardware

| Component | Details |
|-----------|---------|
| Board | Sixunited AXB35 (BeyondMax Series) |
| CPU | AMD Ryzen AI MAX+ 395 (32 threads) |
| GPU | Radeon 8060S (RDNA 3.5, gfx1151) |
| VRAM | BIOS VGM carve: **1GB** (deliberate — GPU allocates from GTT instead) |
| NPU | XDNA2 aie2p 6x8 (PCI c7:00.1, 1022:17f0 rev 11) |
| RAM | 128GB LPDDR5X-8000 physical; **124GiB visible to Linux** |
| GTT | 124GiB window, pinned pages capped at **108GiB** (`amdgpu.gttsize=126976`, `ttm.pages_limit=28311552`) — see [Kernel boot parameters](#kernel-boot-parameters) |
| BIOS | AMI v1.07 |

## Software stack

| Component | Version | Notes |
|-----------|---------|-------|
| Kernel | 7.2.0-rc3 (vanilla) | COPR `@kernel-vanilla/mainline-wo-mergew` |
| Mesa | 25.3.6 (Vulkan 1.4.341) | Vulkan RADV driver |
| llama.cpp | fresh upstream `~/llama.cpp` @ `69bf643` (2026-08-08, Vulkan build) | Native MTP speculative decoding (`--spec-type draft-mtp`). The old `~/llama-cpp-turboquant` fork is retired for the LLM path. |
| ROCm | 7.2 (kyuz0 toolbox) | For VLM + ComfyUI containers |

> **Vulkan users:** pin the *date-stamped* kyuz0 tag. A later build on the floating
> tag cost 2.3x on token generation here. See [docs/vulkan-pinned-build.md](docs/vulkan-pinned-build.md).
| XRT | 2.23.0 | NPU runtime, built from `~/xdna-driver` |
| amdxdna | 2.23.0 (DKMS) | NPU kernel module |
| FastFlowLM | v0.9.36 | NPU inference server |
| Unsloth | 2026.7.4 (torch 2.11.0+rocm7.13.0) | Fine-tuning, isolated venv at `~/.unsloth/studio`. See [`docs/unsloth-rocm-gfx1151.md`](docs/unsloth-rocm-gfx1151.md) |

## Quick start

```bash
git clone https://github.com/sypherin/strix-halo-setup.git
cd strix-halo-setup
chmod +x setup.sh bin/*.sh patches/*.sh
./setup.sh
systemctl --user start llama-server comfyui
```

For NPU setup, see [NPU Setup](#npu-setup) below.

### Vulkan kernels for the DeepSeek-V4 ops

Five compute shaders implementing DSv4's custom GGML operations on Vulkan — the first
such implementations I can find, since upstream is adding them CPU-only and the fork
they target ships CPU + Metal. 1,153 insertions, 64 numerics tests, verified on gfx1151.
Applying them takes a fork that produced **zero tokens in 30 minutes** to coherent
generation at 12.3 t/s. Patch series + apply instructions:
[`patches/vulkan-dsv4-kernels/`](patches/vulkan-dsv4-kernels/).

## DeepSeek V4 Flash (284B) — frontier-scale, fully local

A **284B-parameter model at full 131k context** on this box, GPU-offloaded via Vulkan,
no CUDA. 130 t/s prompt, 12 t/s generation, ~5% decay to 4k depth. Measured 2026-08-01.
Includes the traps that cost a day (the `llama-cli` interactive-EOF loop that mimics a
hung model, Vulkan's ~5GB single-allocation cap, reasoning-budget starvation, the
q8_0-KV throughput penalty) and an honest quality verdict against a strict spec
benchmark. Full writeup: [`docs/deepseek-v4-flash-284b.md`](docs/deepseek-v4-flash-284b.md).

```bash
llama-server -m DeepSeek-V4-Flash-0731-UD-IQ2_XXS-00001-of-00003.gguf \
  -ngl 99 -c 131072 -ub 1024 -fa on -np 1 --cache-prompt --reasoning-budget 4096
```

## Claude Code on local Qwen3.6 (offline, 256k, MTP)

Run the **Claude Code CLI against the local Qwen3.6-35B-A3B** model — fully offline,
zero API cost, 256k context — for real coding on large codebases. Built + verified
2026-07-10. Full writeup: [`docs/claude-code-local-qwen3.6-mtp.md`](docs/claude-code-local-qwen3.6-mtp.md).

```bash
ccr code                     # from any project dir → Claude Code driving local Qwen3.6
ccr code -p "refactor foo"   # one-shot / headless
ccr status                   # is the router up?
ccr restart                  # after any model/config change
```

```
Claude Code CLI ──► claude-code-router (ccr, :3456) ──► llama-server (:8001)
                                                        Qwen3.6-35B-A3B MTP, Vulkan/RADV, 256k
```

- **Model:** unsloth `Qwen3.6-35B-A3B-MTP-GGUF` (UD-Q4_K_XL, ~22.85 GB) with **native
  multi-token-prediction** speculative decoding — the MTP layers are grafted into the GGUF.
- **The MTP win:** `--spec-type draft-mtp` gives **~75–86 t/s** on coding prompts (draft
  acceptance 65–80%) vs ~61 t/s no-MTP. A classic separate 0.8B draft model *backfired*
  (~27 t/s, ~20% acceptance) — don't use it. No penalty at 256k (~74–80 t/s).
- **ccr config:** [`configs/claude-code-router.config.json`](configs/claude-code-router.config.json)
  (lives at `~/.claude-code-router/config.json`; `ccr restart` after edits).

### Switching the :8001 model

`:8001` runs one model at a time as a systemd user service. Flip between them with
[`bin/strix-llm-switch.sh`](bin/strix-llm-switch.sh):

```bash
~/bin/strix-llm-switch.sh qwen    # → Qwen3.6-35B-A3B MTP (llama-server.service, the default)
~/bin/strix-llm-switch.sh qwen27  # → Qwen3.6-27B dense (llama-server-qwen27b.service)
~/bin/strix-llm-switch.sh gemma   # → Gemma 4 26B-A4B (llama-server-gemma.service)
~/bin/strix-llm-switch.sh ds4     # → DeepSeek-V4-Flash 284B (llama-server-ds4.service)
```

It writes `~/.config/strix-llm-unit` as the single source of truth so a liveness watchdog
revives the *currently-selected* unit instead of fighting the swap.

**Thinking is now OFF at the server (2026-08-14).** The unit runs `--reasoning off`, so
Qwen3.6's hybrid thinking is opt-**in** per request with
`chat_template_kwargs: {"enable_thinking": true}`. This inverts the earlier setup, where
thinking was on by default and every small-`max_tokens` caller had to remember to send
`enable_thinking: false` or reasoning silently ate the budget and `content` came back
empty — off-by-default turned a recurring caller-side foot-gun into an explicit opt-in.

### The second resident — Qwen3.8-27B VL on :8022 (and the Glimmer story)

Since 2026-08-08 the box keeps a **second model resident** alongside the :8001 primary,
for vision + writing work (the 35B-A3B is text-only). Two models held that seat:

- **Muse-Glimmer-30B** (2026-08-08 → 08-14): vision 30B on a custom **ROCm-FP4** build,
  ~26.5 t/s — FP4-on-ROCm beats Q4_K-on-Vulkan on this bandwidth-bound part. Full
  writeup: [`docs/muse-glimmer-30b-strix.md`](docs/muse-glimmer-30b-strix.md). The unit
  (`llama-server-glimmer-fpx`) is disabled but kept on disk as a rollback.
- **Qwen3.8-27B** (2026-08-14 →, current): native **vision (mmproj) + native MTP** in one
  model, unsloth UD-Q4_K_XL + mmproj-F16, served by the same upstream llama.cpp Vulkan
  build as :8001 — one stack instead of a bespoke FP4 build. ~22 t/s tg with **61% MTP
  draft acceptance**, 256k ctx, `--parallel 2`. Recommended sampling (temp 0.7, top-p 0.8,
  top-k 20, presence 1.5) is baked into the unit, reasoning off by default.
  Unit: [`systemd/llama-server-qwen38.service`](systemd/llama-server-qwen38.service).

## vLLM on gfx1151 — many-user serving

**vLLM runs on Strix Halo.** Serving and generating, verified 2026-08-03 via the
[lemonade-sdk/vllm-rocm](https://github.com/lemonade-sdk/vllm-rocm) qualified bundle with
Qwen3.6-27B-AWQ-INT4. This is the workload llama.cpp with `--parallel 1` does not cover:
**111 t/s aggregate across 32 concurrent users** (19.6x scaling over single-stream), on one
desktop-class box. Full writeup: [`docs/vllm-gfx1151.md`](docs/vllm-gfx1151.md).

**Muse-Glimmer-30B (vision, 30B):** ~26.5 t/s on a custom ROCm-FP4 build; FP4-on-ROCm beats Q4_K-on-Vulkan (bandwidth-bound). Full writeup: [`docs/muse-glimmer-30b-strix.md`](docs/muse-glimmer-30b-strix.md).

```bash
bin/vllm-serve-strix.sh                 # defaults: AWQ 27B, :8107, eager, max_num_seqs 256
MEM_FRAC=0.5 PORT=8107 bin/vllm-serve-strix.sh /path/to/hf-model
```

| concurrency | aggregate t/s | per-user t/s |
|---|---|---|
| 1  | 5.66  | 5.66 |
| 8  | 38.6  | 4.84 |
| 16 | 71.3  | 4.46 |
| 32 | 111.2 | 3.48 |

- **Do not use it as a daily driver.** `:8001` (35B-A3B MoE + MTP) does 66–86 t/s
  single-stream — roughly 10x faster for one developer. vLLM's win is concurrency only.
- **These are floor numbers** — measured with `--enforce-eager`, so torch.compile *and* HIP
  graph capture were disabled. Graph capture is untried on purpose:
  [vllm-project#32180](https://github.com/vllm-project/vllm/issues/32180) reports it hanging
  the gfx1151 driver, which would take every other GPU service down with it.
- **The one rule:** launch through the bundle's own `bin/vllm-server` shim. Every "packaging
  bug" worth hours — `Failed to infer device type`, a CUDA `flash_attn` import error,
  `EngineDeadError` in `kernel_paged_attention_2d` — is really that shim's missing env
  (`CC`, the real amdsmi, `LD_LIBRARY_PATH`), not a gfx1151 defect.

## Performance benchmarks

### LLM inference

**Both drivers run Q4 with native MTP** (`--spec-type draft-mtp`) on a fresh upstream llama.cpp
Vulkan build. Numbers are the server's own `timings` on real chat-completion requests (250-word
generation, warm), i.e. actual end-user throughput including the jinja chat template.

| Model | Quant + MTP | Sustained tg | Peak | Draft accept | Role |
|-------|-------------|:-:|:-:|:-:|------|
| **Qwen3.6-35B-A3B** (3B active) | UD-Q4_K_XL, MTP n=3, q8_0 KV | **~66-78 t/s** | 86 | 44-80% | **PRIMARY :8001 driver** (`strix-llm-switch qwen`) — MoE, proven agent driver, 256k ctx. ~66 on general text, up to ~78 on code (higher accept) |
| Qwen3.6-27B (DENSE, 27B active) | UD-Q4_K_XL, MTP n=5, q8_0 KV | **~20-22 t/s** | 25 | 30-58% | experimental *alternate* (not default): dense, vision, stronger coder, 256k ctx. MTP only ~1.7x here (dense) |
| **Qwen3.8-27B VL** (DENSE, 27B active) | UD-Q4_K_XL + mmproj-F16, MTP n=2, q8_0 KV | **~22 t/s** | — | ~61% | **SECOND RESIDENT :8022** — native vision + native MTP in one model; the box's vision/writing driver since 2026-08-14 |
| **Gemma-4-26B-A4B** (4B active) | UD-Q4_K_XL, MTP n=3, f16 KV | **~78 t/s** | 82 | 66-71% | switchable: vision-capable, strong extraction/structured-output |

**Optimal MTP settings (tuned 2026-07-14):**

- `--spec-draft-n-max 3` is the sweet spot for both. Going higher (5/6/8) *lowers* throughput: the
  MTP head's draft acceptance craters past ~3 tokens (n=8 dropped Gemma to ~40 t/s).
- KV cache: use **`f16` for Gemma MTP** (about 10% over `q8_0`: 82 vs 74 peak). Qwen keeps `q8_0`
  (its 256k context needs the smaller KV, and f16's gain there is marginal).
- Always: `-fa 1`, `--ubatch-size 1024`, `-ngl 99`, and `-ngld 99` to offload the draft head too.

Tuned Gemma Q4+MTP launch:

```bash
llama-server -m gemma-4-26B-A4B-it-UD-Q4_K_XL.gguf \
  -md mtp-gemma-4-26B-A4B-it.gguf --spec-type draft-mtp --spec-draft-n-max 3 -ngld 99 \
  -ngl 99 -fa 1 --ubatch-size 1024 -ctk f16 -ctv f16 --parallel 1 --no-warmup --jinja --port 8001
```

The MTP draft head `mtp-gemma-4-26B-A4B-it.gguf` (~0.46GB) lives *inside* the regular
`unsloth/gemma-4-26B-A4B-it-GGUF` repo (a separate head file, not a single fused gguf). Load it with
`--spec-type draft-mtp`; `draft-simple` tries to load the head as a full model and fails with
"failed to create llama_context".

**Cross-machine (2026-07-14):** against a reported HP Zbook Ultra G1a laptop running the same models
via Lemonade/Vulkan, this desktop wins both: Gemma-4-26B-A4B MTP **78-82 vs 72**, Qwen3.6-35B-A3B MTP
**78 vs 65**. For a 4B-active MoE the lever is MTP, not quant (Q4 *non*-MTP was only ~48 t/s; Q4+MTP ~78).

**⚠ Qwen3.6-27B DENSE + MTP (EXPERIMENTAL ALTERNATE — not the default).** The primary :8001 driver is
the Qwen3.6-35B-A3B MoE above; the 27B is a documented option you can flip to, not the standing driver.
The dense 27B is bandwidth-bound at **~12 t/s non-MTP** (it reads all 17.9 GB of Q4 weights per token
against ~256 GB/s), and its built-in MTP head only lifts it to **~20-22 t/s** at 256k (measured across 9
runs, draft acceptance ~30-58%). That is about **1.7x**, NOT the ~6x a MoE gets. On a dense model MTP is
hard-capped at (draft_len + 1) x the base rate, and acceptance is low, so a dense 27B simply cannot reach
MoE-class throughput on this box. **Correction:** an earlier revision of this file listed the 27B at
~77 t/s; that figure was the 35B-A3B MoE mislabeled during a messy benchmarking session (the MoE has only
3B active per token, so its base rate is far higher). It is corrected here after a clean re-bench, with
thanks to the r/LocalLLaMA reader who flagged it. MTP is still lossless (the main model verifies every
token). The 27B is vision-capable (ships an mmproj) and a stronger coder, so it can be worth the flip if
you want vision + coding and can live with ~20 t/s. Flip to it with `strix-llm-switch.sh qwen27`; revert
to the 35B with `strix-llm-switch.sh qwen`.

Launch (see `systemd/llama-server-qwen27b.service`):
```bash
llama-server -m Qwen3.6-27B-UD-Q4_K_XL.gguf --spec-type draft-mtp --spec-draft-n-max 5 -ngld 99 \
  --ctx-size 262144 -ngl 99 -fa 1 --ubatch-size 1024 -ctk q8_0 -ctv q8_0 --parallel 1 --port 8001
```
**Note:** keep `--reasoning-budget/--reasoning-format` off the 27B unit and suppress thinking with
`enable_thinking:false` per request; letting a slow model think just burns the token budget.
(A previous version of this note claimed those flags "tanked" the 27B from ~77 to ~22 t/s. That was the
same 35B-vs-27B mixup as above, not a real reasoning-flag effect: the dense 27B runs ~20-22 t/s either
way.) The 27B-MTP gguf (single file, embedded head) is `unsloth/Qwen3.6-27B-MTP-GGUF`. **Still
validating**: watch for monologuing / degraded tool-following in real agent loops before trusting it
over the 35B MoE.

The Q8 / 128k tables below are the earlier (May) baseline, kept for host-config and kernel reference.

#### Gemma 4 26B-A4B-it UD-Q8_K_XL — kernel 7.0 stable

Tested 2026-05-23 against the live llama-server on `:8001`. Host: kernel
7.0.0-261 vanilla, Mesa 25.3.6, Vulkan RADV, llama-cpp-turboquant build.

| Metric | Value | Notes |
|--------|-------|-------|
| Prompt processing (pp) | **~720 t/s** | 10K-token prompt, 3-run avg (warm runs: 698, 741 t/s) |
| Token generation (tg) | **~41 t/s** | 64-token generation, 3-run avg, hot |
| Time to first token | **~269ms** | Short prompt, streamed, 3-run avg (257, 275, 274 ms) |
| Context size | 131072 | KV cache: q8_0 |

#### Qwen3.6-35B-A3B UD-Q8_K_XL — kernel 7.0 stable

Tested 2026-04-29 against the live llama-server on `:8001`. Host: kernel
7.0.0-261 vanilla, Mesa 25.3.6, Vulkan RADV, llama-cpp-turboquant build.

| Metric | Value | Notes |
|--------|-------|-------|
| Prompt processing (pp) | **~839 t/s** | 10,223-token prompt |
| Token generation (tg) | **~44 t/s** | 64-token generation, no reasoning |
| Time to first token | **~254ms** | 23-token prompt, --no-warmup hot |
| Context size | 131072 | KV cache: q8_0 |

Numbers in both tables are taken from the server's own `timings` field on real
OpenAI-compatible chat-completion requests, not synthetic `llama-bench` runs —
i.e. they reflect actual end-user latency including the chat template + jinja
rendering.

**Trade quantified.** Moving from Qwen3.6-35B-A3B (3B active) to Gemma 4 26B-A4B
(4B active) costs ~14% on pp (839 → 720), ~7% on tg (44 → 41), and adds ~15ms
on TTFT (254 → 269). All within the expected ~33% active-param ratio. Decode
quality on long-form extraction + structured-output workloads improved enough
to justify the throughput cost for this box's workload mix; your mileage will
depend on what you're shipping.

**Note on long-generation throughput.** Streaming a 512-token reply with the
default `--reasoning-budget 500` and the model's built-in thinking mode produced
~7 t/s wall-clock on a single request. The slowdown is not a Vulkan/host issue
— Qwen3.6 silently emits thinking tokens that don't get counted in `predicted_n`,
so the t/s reported is artificially low. For "real" tg comparisons against
non-thinking models, set `--reasoning-budget 0` or use a no-reasoning system
prompt.

#### Legacy baseline — Qwen3.5-122B-A10B UD-Q4_K_XL (kernel 7.0-rc6)

Retained for host-config reference. Tested kernel 7.0-rc6, Mesa 25.3.6.

| Metric | Value | Notes |
|--------|-------|-------|
| Prompt processing (pp) | 393 t/s | ~2K token prompt |
| Token generation (tg) | 22 t/s | Stable across runs |
| Time to first token | ~430ms | Short prompts |
| Context size | 65536 | KV cache: q8_0 |

#### Kernel comparison

| Metric | Kernel 6.19.9 | Kernel 7.0-rc6 | Change |
|--------|--------------|----------------|--------|
| pp | 287-351 t/s | 393 t/s | +12-37% |
| tg | 22-23 t/s | 22 t/s | No change |

Kernel 7.0 significantly improves prompt processing via RADV/Vulkan improvements, but token generation is memory-bandwidth bound and unchanged.

#### Optimization history

| Setting | Tested values | Winner | Notes |
|---------|--------------|--------|-------|
| `--ubatch-size` | 512, 1024, 2048 | **1024** | pp 320 vs 266 vs 320, diminishing returns at 2048 |
| `--kv-unified` | on, off | **off** | Hurt pp, broke prompt caching, no tg benefit |
| `-ctk`/`-ctv` | turbo2, q8_0 | **q8_0** | turbo2 not supported on Vulkan (SET_ROWS op missing) |
| `-fa` | on, off | **on** | Required for good performance on Strix Halo |

## Services

| Service | Port | Backend | Startup | Description |
|---------|------|---------|---------|-------------|
| `llama-server` | 8001 | Vulkan | auto | **Primary LLM — Qwen3.6-35B-A3B MTP** (fresh upstream llama.cpp, Vulkan RADV) |
| `llama-server-qwen38` | 8022 | Vulkan | auto | **Second resident — Qwen3.8-27B VL + MTP** (vision + writing; replaced Muse-Glimmer 2026-08-14) |
| `llama-server-qwen27b` | 8001 | Vulkan | via switch | Alternate — Qwen3.6-27B dense. Bind-conflicts with `llama-server`; flip with `strix-llm-switch.sh qwen27` |
| `llama-server-gemma` | 8001 | Vulkan | via switch | Alternate — Gemma 4 26B-A4B. Bind-conflicts with `llama-server`; flip with `strix-llm-switch.sh gemma` |
| `comfyui` | 7860 | ROCm | auto | Image/video gen (kyuz0 toolbox container) |
| `llama-surya2` | 8093 | ROCm | on-demand | Surya 2 OCR VLM 650M (document OCR) |
| `flm-asr` | 52625 | NPU | on-demand | Whisper STT for the Jarvis voice assistant (offloaded from CPU) + small LLMs |
| `lemonade` | 8000 | Vulkan | manual | Web UI + sd-cpp (optional) |

### Managing services

```bash
# Status
systemctl --user status llama-server llama-server-qwen38 comfyui

# Start/stop
systemctl --user start llama-server
systemctl --user stop llama-server

# Logs
journalctl --user -u llama-server -f

# Health check
curl http://localhost:8001/health
```

## Kernel boot parameters

Required for optimal Strix Halo unified memory performance (current since 2026-08-09):

```
amd_iommu=off amdgpu.gttsize=126976 ttm.pages_limit=28311552
```

- `amd_iommu=off` — replaces the earlier `iommu=pt`. Benchmarked on Strix Halo as **5-12%
  faster than either IOMMU-enabled mode** (Lars Urban's numbers in kyuz0's toolboxes repo,
  issue #66); fine on a box that needs no VFIO/SR-IOV passthrough
- `amdgpu.gttsize=126976` — GTT window of 124GiB (126976 MiB) so the iGPU can address nearly all system RAM
- `ttm.pages_limit=28311552` — pinned-pages cap of **108GiB** (28311552 × 4KiB), deliberately
  ~16GiB *below* the GTT window. An earlier revision matched the cap to the window (124GiB ==
  all of RAM); that let GPU allocations starve the host — a second model load OOM-killed the
  whole desktop with "nothing killable" (2026-08-08) because every large process was pinned.
  Capping TTM at 108GiB keeps a floor of host-reclaimable RAM no model load can take.

> **⚠ The TTM cap can be silently clamped — verify it at runtime, not just on the cmdline.**
> Setting `ttm.pages_limit=` on the kernel cmdline is necessary but *not always sufficient*: on some boots the live value is clamped back toward the ~96GiB default, so `cat /sys/module/ttm/parameters/pages_limit` reads something other than what the cmdline asked for. When that happens, any model whose weights exceed the live cap (e.g. the 90.9GiB DeepSeek-V4-Flash mixed q2/q4/q8 quants) fails to load or thrashes — even though the cmdline looks correct. The symptom is a "needs a smaller base model / exceeds the box" style failure that disappears once the live cap is actually applied.
>
> Fix: enforce it at runtime and persist it with a tiny boot service. **The service must
> write the SAME value as the cmdline** — a service still carrying an old value silently
> re-widens (or re-narrows) the cap on every boot.
> ```bash
> cat /sys/module/ttm/parameters/pages_limit          # check the LIVE value first (pages)
> echo 28311552 | sudo tee /sys/module/ttm/parameters/pages_limit   # 28311552 x 4KiB = 108GiB
> # persist across reboots — see systemd/ttm-pages-limit.service
> sudo cp systemd/ttm-pages-limit.service /etc/systemd/system/
> sudo systemctl enable --now ttm-pages-limit.service
> cat /sys/module/ttm/parameters/pages_limit          # must now read 28311552
> ```
> The service only writes one sysfs number, depends on nothing, and no-ops on failure, so it can never delay or block boot.

Pairs with the BIOS: **VGM/UMA set to the 1GB minimum**, NOT a big dedicated carve. The GPU then allocates from GTT on demand — RAM stays flexible between CPU and GPU instead of being hard-partitioned at boot. (An earlier revision of this setup used a 96GB VGM carve, which left Linux only ~31GB of system RAM; that approach is retired and this README previously described it.)

Set via `grubby` or `/etc/default/grub`.

## Containers (toolboxes)

| Container | Image | Status | Purpose |
|-----------|-------|--------|---------|
| `llama-rocm-7.2` | `kyuz0/amd-strix-halo-toolboxes:rocm-7.2` | running | ROCm LLM inference (VLM) |
| `strix-halo-comfyui` | `kyuz0/amd-strix-halo-comfyui:latest` | running | ComfyUI image/video gen |
| `strix-halo-image-video` | `kyuz0/amd-strix-halo-image-video:latest` | available | Qwen Image Studio + Wan 2.2 |
| `llama-vulkan-radv` | `kyuz0/amd-strix-halo-toolboxes:vulkan-radv` | available | Vulkan LLM (backup) |

### Available kyuz0 toolboxes

| Toolbox | Docker Tag | Purpose |
|---------|-----------|---------|
| Vulkan RADV | `kyuz0/amd-strix-halo-toolboxes:vulkan-radv` | llama.cpp Vulkan (most stable) |
| ROCm 7.2 | `kyuz0/amd-strix-halo-toolboxes:rocm-7.2` | llama.cpp ROCm (long context) |
| ComfyUI | `kyuz0/amd-strix-halo-comfyui:latest` | Image/video gen (ROCm TheRock) |
| Image/Video | `kyuz0/amd-strix-halo-image-video:latest` | Qwen Image + Wan 2.2 + ComfyUI |
| vLLM | `kyuz0/vllm-therock-gfx1151:latest` | vLLM serving (ROCm TheRock) |
| Finetuning | `kyuz0/amd-strix-halo-llm-finetuning:latest` | LoRA/QLoRA training (ROCm) |
| Voice | `kyuz0/amd-strix-halo-voice:latest` | VibeVoice TTS + voice cloning |

## NPU Setup

The XDNA2 NPU requires an out-of-tree driver build — the kernel's built-in amdxdna v0.6.0 has a version mismatch with newer XRT. The COPR `xanderlent/amd-npu-driver` packages (April 2025) are also outdated.

### Build and install from source

```bash
# Clone AMD's xdna-driver repo
git clone --depth 1 https://github.com/amd/xdna-driver.git ~/xdna-driver
cd ~/xdna-driver
git submodule update --init --recursive

# Install dependencies
sudo dnf install -y ninja-build jq

# Build XRT base + NPU packages
cd xrt/build
bash build.sh -npu -opt
sudo rpm -Uvh --force Release/xrt_*-base.rpm Release/xrt_*-npu.rpm

# Build and install the xdna driver plugin (includes DKMS kernel module)
cd ../../build
bash build.sh -release -install_prefix /opt/xilinx/xrt
sudo rpm -Uvh --force Release/xrt_plugin.*-amdxdna.rpm

# Verify NPU is detected
source /opt/xilinx/xrt/setup.sh
xrt-smi examine
# Should show: RyzenAI-npu5, aie2p, 6x8

# Validate NPU compute
xrt-smi validate
# GEMM and latency tests should pass
```

### NPU validation results

```
Test 1: gemm        → PASSED (51.0 TOPS)
Test 2: latency     → PASSED (47.0 μs average)
Test 3: throughput  → FAILED (runlist abort — known issue, non-critical)
```

### Key NPU details

- **Driver**: amdxdna v2.23.0 (DKMS, built from `amd/xdna-driver` main branch)
- **XRT**: v2.23.0 (built from submodule, installed at `/opt/xilinx/xrt/`)
- **Firmware**: `npu.sbin.1.0.0.166` at `/lib/firmware/amdnpu/17f0_11/`
- **Device**: `[0000:c7:00.1]` RyzenAI-npu5, aie2p architecture, 6x8 topology
- **memlock**: unlimited (`/etc/security/limits.d/99-amdxdna.conf`)
- **BIOS note**: No NPU/IPU toggle in Sixunited AXB35 BIOS — NPU is enabled by default

### NPU use cases

The NPU (XDNA2, ~50 TOPS INT8) is best for small always-on models, freeing the GPU for large models:

| Use Case | Tool | Status |
|----------|------|--------|
| **Voice assistant STT (Jarvis)** | FastFlowLM `whisper-v3:turbo` (`flm-asr.service`) | Working — ~6x realtime, off the CPU (service on-demand) |
| Small LLM (1-4B) | FastFlowLM (`flm serve <model>`) | 28-89 tok/s |
| Embeddings | `embed-gemma:300m` via flm | Low latency |

#### Implemented: Jarvis STT on the NPU (2026-07-21)

The "Hey Jarvis" assistant's Whisper STT runs on the NPU instead of the CPU, freeing the CPU that the `:8001` MTP draft-verify contends for. Wake-word (openWakeWord) and Piper TTS stay on the CPU — both are tiny with no NPU path.

- **NPU endpoint:** `flm serve lfm2:2.6b --asr 1` exposes an OpenAI-compatible `POST /v1/audio/transcriptions` on `:52625`, backed by `whisper-v3:turbo` on the NPU. Persisted as `flm-asr.service` (see `systemd/`).
  - Gotcha: do **NOT** set `FLM_CONFIG_PATH` to the `~/.config/flm` dir — flm reads it as a model-list *file* and crashes (`basic_filebuf::underflow ... Is a directory`). Leave it unset (flm finds `~/.config/flm/models` from `$HOME`); the service just sources `/opt/xilinx/xrt/setup.sh` for the XRT libs.
- **Assistant wiring:** `~/bin/voice-assistant/assistant.py` `transcribe()` posts the recorded-command WAV to the NPU endpoint when `config.json` has `"stt_backend": "npu"` (+ `"npu_stt_url"`). Default `"cpu"` keeps the openai-whisper path — fully revertible by flipping that one key.
- **Not movable:** MTP/speculative decoding stays GPU-only (integrated MTP heads = no separable draft; a cross-hardware NPU draft would add per-step latency that eats the speedup).

## Critical configuration notes

### mmap vs --no-mmap under the GTT regime (updated 2026-06-08)

The old advice here ("--mmap is REQUIRED for Vulkan") dated from the 96GB-VGM-carve era, when Linux only saw ~31GB of RAM and `--no-mmap` would swap-thrash. **That no longer applies.** With the current 1GB carve + 124GiB GTT, model weights live in host RAM either way, so mmap is now a per-unit tuning choice — the two deployed Vulkan LLM units differ deliberately:

| Unit | mmap | Env |
|------|------|-----|
| `llama-server` (Qwen3.6 MTP, primary) | `--mmap` | `GGML_VK_PREFER_HOST_MEMORY=ON` |
| `llama-server-gemma` (Gemma 4 Q4+MTP, alternate) | `--mmap` | `GGML_VK_PREFER_HOST_MEMORY=ON`, `RADV_PERFTEST=nogttspill` |

`--no-mmap` loads weights into host memory up front (no first-token page-fault stalls); `--mmap` is fine here too since weights stay resident under the GTT regime. If you change either, benchmark on that specific model — don't cargo-cult the flag across units.

### --no-mmap is REQUIRED for ROCm (opposite of Vulkan!)

ROCm toolbox containers use `--no-mmap` because ROCm's mmap path above 64GB is very slow on gfx1151. The GPU has direct access to system memory in ROCm mode, so `--no-mmap` loads into GPU-accessible memory correctly.

ComfyUI also requires `--disable-mmap --cache-none --bf16-vae` for the same reason.

### FP8 is broken on gfx1151 — always use BF16

FP8 is a **software limitation** on Strix Halo (RDNA 3.5). Always use BF16 models for image/video generation.

## Why Vulkan for LLM? Why ROCm for image gen?

**LLM inference**: ROCm doesn't reliably detect gfx1151 for all workloads. Vulkan via RADV works perfectly and uses the full unified pool (~124GiB GTT).

**Image/video generation**: ComfyUI and PyTorch-based pipelines require ROCm. The kyuz0 toolbox containers include patched ROCm (TheRock nightlies) that work on gfx1151 with `HSA_OVERRIDE_GFX_VERSION=11.5.1`.

| | Vulkan (RADV) | ROCm (kyuz0 toolbox) |
|---|---|---|
| LLM (llama.cpp) | **~22 t/s gen, ~393 t/s pp** | ~21 t/s gen, ~268 t/s pp |
| Image gen (ComfyUI) | N/A | ~198 it/s |
| Stability | Excellent | Good (needs toolbox) |

## Models

### LLM (llama-server on port 8001)

| Model | Type | Active Params | Quant | Speed | Use case |
|-------|------|---------------|-------|-------|----------|
| **Qwen3.6-35B-A3B MTP** | MoE | 3B | UD-Q4_K_XL | **~75–86 t/s gen** (native MTP), 256k-capable (run at 128k) | **Default (2026-07-10+)** — Claude Code / coding, fast decode via `--spec-type draft-mtp` |
| **Qwen3.8-27B VL** (:8022, second resident) | Dense | 27B | UD-Q4_K_XL + mmproj-F16 | **~22 t/s gen** (native MTP, 61% accept), 256k ctx | **Vision + writing (2026-08-14+)** — replaced Muse-Glimmer-30B on :8022 |
| Gemma 4 26B-A4B-it | MoE | 4B | UD-Q4_K_XL + MTP | **~78 t/s gen** (draft-mtp n=3, f16 KV peak 82), 128k ctx | Switchable alternate: vision, extraction quality, structured output, tool use |
| Qwen3.6-35B-A3B (Q8, no MTP) | MoE | 3B | UD-Q8_K_XL | ~44 t/s gen, ~839 t/s pp | Prior primary — higher-fidelity quant without MTP |
| Qwen3.5-122B-A10B | MoE | 10B | UD-Q4_K_XL | ~22 t/s gen, ~393 t/s pp | Legacy, SOTA quality but slower |

To flip the live `:8001` model between the Qwen3.6 MTP default and Gemma:
```bash
~/bin/strix-llm-switch.sh qwen    # or: gemma
```
To change quant/path, edit the `-m` line in the relevant unit (`llama-server.service` for
Qwen3.6, `llama-server-gemma.service` for Gemma) and `systemctl --user restart` it.

### VLM — retired standalone service (2026-08-15)

The dedicated Qwen3-VL-32B server (`llama-vlm-bom`, :8080, ROCm toolbox) is **retired**:
the always-on Qwen3.8-27B VL on :8022 handles vision now — one resident model instead of
a windowed 32B that had to be started for every vision batch. Every former :8080 consumer
points at :8022. Surya 2 (:8093) remains the dedicated document-OCR path.

### Image/Video Generation (ComfyUI on port 7860)

Toolbox: `kyuz0/amd-strix-halo-comfyui:latest` (ROCm TheRock nightlies)

| Workflow | Type | Notes |
|----------|------|-------|
| HunyuanVideo 1.5 | I2V / T2V | 4-step LoRA, 720p |
| Qwen Image 2512 | T2I | Must use BF16 (not FP8) |
| Qwen Image Edit | Image Editing | Lightning LoRA |
| Wan 2.2 | I2V / T2V | 14B model with 4-step Lightning LoRA |

## Building llama.cpp (Vulkan)

The LLM path now uses a **fresh upstream `~/llama.cpp`** build (verified @ `fb30ba9`,
2026-07-09) — it exposes the native MTP flag (`--spec-type draft-mtp`) the Qwen3.6
primary needs. The old `~/llama-cpp-turboquant` fork is retired for the LLM (its turbo
KV cache types were CPU-only anyway; on Vulkan we use q8_0 KV cache).

```bash
git clone --depth 1 https://github.com/ggml-org/llama.cpp ~/llama.cpp
cd ~/llama.cpp
cmake -B build -G Ninja -DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=ON
cmake --build build -j16 --target llama-server

# Update service
systemctl --user restart llama-server
curl http://localhost:8001/health  # wait for model to load (~35s)
```

Build deps: `glslc`, `cmake`, `ninja`, Vulkan headers (mesa 1.4.x). The resulting
`build/bin/llama-server` finds its `.so`s via rpath — no `LD_LIBRARY_PATH` wrapper needed.

## Structure

```
├── setup.sh                              # Main setup script
├── systemd/
│   ├── llama-server.service              # PRIMARY LLM — Qwen3.6-35B-A3B MTP (Vulkan, auto)
│   ├── llama-server-qwen38.service       # SECOND RESIDENT — Qwen3.8-27B VL + MTP on :8022 (auto)
│   ├── llama-server-qwen27b.service      # Alternate LLM — Qwen3.6-27B dense (via switch)
│   ├── llama-server-gemma.service        # Alternate LLM — Gemma 4 26B-A4B (via switch)
│   ├── llama-surya2.service              # Surya 2 OCR VLM (document OCR, ROCm, on-demand)
│   ├── ttm-pages-limit.service           # Enforce the 108GiB TTM cap at boot
│   ├── comfyui.service                   # ComfyUI (ROCm toolbox, auto-enabled)
│   └── lemonade.service                  # Lemonade router (optional, disabled by default)
├── bin/
│   ├── llama-server-wrapper.sh           # LD_LIBRARY_PATH wrapper for Vulkan binary
│   ├── sd-server-wrapper.sh              # LD_LIBRARY_PATH wrapper for sd-cpp binary
│   ├── strix-llm-switch.sh               # Flip :8001 between Qwen3.6 MTP and Gemma
│   └── vllm-serve-strix.sh               # vLLM via the lemonade bundle (concurrent serving)
├── configs/
│   └── claude-code-router.config.json    # ccr config → local :8001 (secrets redacted)
├── docs/
│   ├── claude-code-local-qwen3.6-mtp.md  # Claude Code on local Qwen3.6 (full writeup)
│   ├── comfyui-qwen-image.md             # Qwen-Image GGUF workflow notes
│   ├── deepseek-v4-flash-284b.md         # DeepSeek V4 Flash 284B: Vulkan config, numbers, traps
│   ├── diffusion-lora-training-gfx1151.md # Image gen (sd.cpp Vulkan) + LoRA training on gfx1151
│   ├── muse-glimmer-30b-strix.md         # Muse-Glimmer-30B: FP4-ROCm vs Q4-Vulkan A/B
│   ├── strix-guard.md                    # Remote kill-switch / stack guard
│   ├── unsloth-rocm-gfx1151.md           # Fine-tuning: Unsloth on ROCm, multimodal LoRA, GGUF
│   ├── vllm-gfx1151.md                   # vLLM on gfx1151: what blocks it, measured throughput
│   └── vulkan-pinned-build.md            # Why the kyuz0 Vulkan tag must be date-pinned
├── tools/
│   └── cc-qwen-vs-opus.sh                # Head-to-head test harness (local Qwen3.6 vs Opus)
├── workflows/
│   └── qwen-image-2512-gguf-lightning.json  # ComfyUI image workflow
├── patches/
│   ├── lemonade-provider-reasoning.patch # VS Code extension patches (human-readable)
│   └── apply-lemonade-patches.sh         # Auto-apply patches
└── vscode/
    └── continue-config.yaml              # Continue extension config
```

## Build history

| Component | Version | Date | Notes |
|-----------|---------|------|-------|
| Qwen3.8-27B VL on :8022 | unsloth UD-Q4_K_XL + mmproj-F16 | 2026-08-14 | Native VL + native MTP in one model; replaced Muse-Glimmer as the second resident |
| Kernel + boot params | 7.2.0-rc3 vanilla; `amd_iommu=off`, TTM cap 108GiB | 2026-08-09 | IOMMU off (5-12% on this platform); TTM capped below GTT so the GPU can't starve the host |
| Muse-Glimmer-30B on :8022 | custom ROCm-FP4 build | 2026-08-08 | Second resident (vision), ~26.5 t/s; retired 08-14, unit kept as rollback |
| llama.cpp | fresh upstream `~/llama.cpp` @ 69bf643 (Vulkan) | 2026-08-08 | Current build for :8001 and :8022 |
| llama.cpp | fresh upstream `~/llama.cpp` @ fb30ba9 (Vulkan) | 2026-07-10 | Native MTP (`--spec-type draft-mtp`), Qwen3.6 primary, ~75–86 t/s tg |
| Qwen3.6-35B-A3B MTP model | unsloth UD-Q4_K_XL (~22.85 GB) | 2026-07-10 | MTP layers grafted into GGUF; 256k ctx |
| llama.cpp | 8793 (Vulkan build from turboquant fork) | 2026-04-03 | 393 t/s pp, 22 t/s tg |
| llama-server | b8461 (kyuz0 Vulkan RADV) | 2026-03 | 351 t/s pp, 19 t/s tg (replaced) |
| llama-server | b8299 (official release) | 2026-03-13 | +40% prompt speed over b8119 |
| llama-server | b8119 (kyuz0 custom) | 2026-02 | Initial build |
| Kernel | 7.1.0-rc4 (vanilla) | 2026-04-04 | +12-37% pp over 6.19.9 |
| Kernel | 6.19.9 (Fedora 43) | 2026-03 | Previous stable |
| XRT | 2.23.0 | 2026-03-22 | Built from amd/xdna-driver submodule |
| amdxdna driver | 2.23.0 (DKMS) | 2026-03-22 | Out-of-tree, replaces kernel v0.6.0 |
| NPU firmware | 1.0.0.166 | 2026-03 | Protocol v6.x |

## Troubleshooting

### System is laggy when model is loaded
Check the mmap flag on the active unit:
```bash
systemctl --user cat llama-server | grep mmap
```
The Qwen3.6 primary intentionally runs `--mmap`; the Gemma alternate runs `--no-mmap`. Both are correct under the current GTT regime — see [mmap notes](#mmap-vs---no-mmap-under-the-gtt-regime-updated-2026-06-08). If a unit was hand-edited to the wrong flag for its model, laggy load is the symptom.

### llama-server fails to start
```bash
journalctl --user -u llama-server --no-pager -n 50
```
Common causes:
- **"no usable GPU found"** — Vulkan backend libs missing. Check build output.
- **Model path changed** — update `-m` in service file
- **Esuna not mounted** — check `mount | grep Esuna`

### NPU not detected by xrt-smi
1. Check if DKMS module is loaded: `lsmod | grep amdxdna`
2. Check for errors: `journalctl -k -b | grep amdxdna`
3. Verify device: `ls /dev/accel/` (should show `accel0`)
4. If "0 devices found" but accel0 exists → XRT/driver version mismatch. Rebuild both from `~/xdna-driver`.

### ROCm toolbox containers
All ROCm containers use `HSA_OVERRIDE_GFX_VERSION=11.5.1` internally. If you need to run ROCm commands outside a toolbox, set this env var first.

---

<sub>Notes from running local LLMs on AMD Strix Halo in production. Maintained by Zachary Aw · [altronis.sg](https://altronis.sg) · Singapore. Issues and PRs welcome.</sub>
