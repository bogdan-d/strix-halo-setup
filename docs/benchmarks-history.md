# Benchmark history

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

## Mesa 26 decode regression (Vulkan mat-vec split) — 2026-09-07

After a Fedora 43 → 44 upgrade (Mesa **25.3.6 → 26.1.8**, RADV, gfx1151), speculative
(MTP) decoding regressed on **decode only** while prompt processing stayed healthy.
Measured with a 32-prompt chat-completion harness (thinking off), single-slot,
Qwen3.8-27B UD-Q4_K_XL + `--spec-type draft-mtp`, ctx 131072:

| Stack | decode t/s | prefill t/s | notes |
|-------|-----------|-------------|-------|
| F43, Mesa 25.3.6, current build | **~24** | ~100 | pre-upgrade baseline |
| F44, Mesa 26.1.8, current build | **15.4** | 106 | decode −34%, prefill fine |
| F44, Mesa 26.1.8, current build, **`GGML_VK_MMV_NO_SPLIT=1`** | **23.1** | 116 | **fix — both axes recovered** |
| F44, Mesa 26.1.8, older build (~381 commits behind) | 23.5 | ~38 | recovers decode but halves prefill — inferior to the flag |

Isolation (each step is a one-variable test on the live server):

1. **Kernel ruled out.** Booting kernel 7.2 with Mesa held at 26 gave the *same* 15.4 t/s
   as the 7.3-rc1 kernel → the amdgpu kernel path is not the regressor. (Don't pin an old
   kernel for this.)
2. **Binary × driver interaction.** An older llama.cpp build decoded at ~23 on the same
   Mesa 26, so the regression tracks an upstream Vulkan change — but that change was
   *decode-neutral on Mesa 25*; it only regresses once paired with Mesa 26. The trigger is
   the **batched mat-vec split** path, which MTP verification exercises at small
   (2–4 column) batch sizes.
3. **The fix beats pinning.** `GGML_VK_MMV_NO_SPLIT=1` disables that split on the *current*
   binary and restores decode to ~23 t/s **without** losing the newer build's
   prompt-processing gains. Output is byte-identical (identical harness pass counts).

Conclusion: on Mesa 26 + gfx1151, set `GGML_VK_MMV_NO_SPLIT=1` for MTP/speculative decode
serving. It is harmless on Mesa 25. Token generation on this platform remains
memory-bandwidth bound at the top end; this knob only removes a driver-specific slow path,
it does not raise the ceiling.

