# DeepSeek V4 Flash (284B) on Strix Halo — Vulkan, no CUDA

Running **DeepSeek-V4-Flash-0731, 284B parameters**, fully GPU-offloaded on a 128GB
Strix Halo mini PC (Ryzen AI Max 395 + Radeon 8060S iGPU) via llama.cpp's **Vulkan**
backend. No CUDA, no cloud, no API key. Measured 2026-08-01.

The short version: **it runs, at read-aloud speed, at full 131k context** — and it is
still not the model you want for spec-compliant code generation. Both halves matter.

## TL;DR — the config that works

```bash
llama-server -m DeepSeek-V4-Flash-0731-UD-IQ2_XXS-00001-of-00003.gguf \
  -ngl 99 -c 131072 -ub 1024 -fa on \
  -np 1 --cache-prompt --jinja --no-warmup \
  --reasoning-budget 4096
# env: GGML_VK_PREFER_HOST_MEMORY=ON
```

Sampling per Unsloth's guidance for this model: `--temp 1.0 --top-p 1.0 --min-p 0.0`.

## Measured numbers

llama.cpp mainline (build fb30ba9), Vulkan/RADV on gfx1151, unsloth `UD-IQ2_XXS`
(84.62 GiB on disk, 284.33B params), full offload:

| test | t/s |
|---|---|
| pp512 | 130.17 |
| tg32 | 12.24 |
| pp512 @ 4k depth | 94.52 |
| tg32 @ 4k depth | 11.57 |

Generation decays only **~5%** from empty context to 4k depth. Sustained 11.8 t/s was
reproduced across four separate 500–717 second generations, so the figure is stable
rather than a lucky sample.

**Memory:** 97G used with the model resident and 131k context allocated, 26G free on a
128GB box. The 84.6 GiB of weights is irreducible at this quant — everything else is
rounding.

## Context: 131,072 tokens, first try

Full context loads with the config above. This surprised us — an earlier naive attempt
at 16k crashed, which made 16k look like a ceiling. It was not; see the allocation trap
below.

## Traps that cost a full day

**1. `llama-cli` in interactive mode is indistinguishable from a hung model.**
Run unattended with no TTY, it prints `>`, reads instant EOF, treats that as a finished
turn, prints `>` again, forever. We collected **2.6 GB of `>` characters** while
concluding "the model crawls at 1% GPU". It was never asked anything. Use `llama-bench`,
or `llama-cli -st` with stdin closed. If you see `>` repeated in a log, that is this bug.

**2. Vulkan refuses single allocations above ~5GB.**
A naive `-c 16384` asks for one 17.7 GB compute buffer and the server dies at startup
with `failed to allocate ... exceeds device buffer size limit`. The fix is not less
context — it is a smaller batch. `-ub 1024` (or lower) shrinks that buffer enough that
**131k context allocates fine**.

**3. It is a thinking model; unbudgeted reasoning eats the answer.**
With reasoning uncapped and a 6000-token output budget, it spent ~5,200 tokens planning
and emitted 366 characters of actual code. `--reasoning-budget` is mandatory. Measured
appetite: ~1,900 tokens for straightforward generation, ~3,200+ for debugging existing
code. 4096 is a reasonable default; the model self-limits below the cap when satisfied.

**4. `llama-server` defaults to 4 parallel slots — 4× the KV cache for nothing.**
Use `-np 1` for single-user work.

**5. Quantized KV cache halves throughput on Vulkan.**
`-ctk q8_0 -ctv q8_0` dropped generation from 11.8 t/s to **4.8 t/s** — dequantization
overhead on every attention op. It is a memory lever, not a speed lever. Only enable it
if you are actually memory-bound.

**6. Size your client timeout to your token budget.**
Raising `max_tokens` to 32,000 at ~5 t/s needs ~110 minutes. A 60-minute HTTP timeout
kills a perfectly healthy generation and looks like a model failure.

## Which quant fits 128GB

Unsloth ships the full ladder for this model:

| quant | size |
|---|---|
| UD-IQ1_S | 83 GB |
| UD-IQ1_M | 87 GB |
| UD-IQ2_XXS | 91 GB (84.6 GiB on disk — what these numbers use) |
| UD-IQ2_M | 91 GB |
| UD-Q2_K_XL | 97 GB |
| UD-IQ3_XXS | 103 GB |
| UD-Q4_K_XL | 155 GB |
| UD-Q8_K_XL | 162 GB |

On 128GB unified there is real headroom up to about **Q2_K_XL**. IQ3_XXS at 103GB sits
right at the edge once KV cache and compute buffers are added. Q4_K_XL and above are out
of reach on this class of machine.

Note the naming mixes two families: `IQ*` (IQ1_S, IQ2_XXS, IQ3_XXS) and `*_K_XL`
(Q2_K_XL, Q4_K_XL). There is no "IQ2_XL".

## Quality: the honest half

Scored against a strict local spec-compliance benchmark — a detailed Pac-Man
specification with an automated Playwright gate that checks a testability contract
before it will run any gameplay assertions.

**DeepSeek-V4 at IQ2_XXS failed the gate**, and the failure is instructive rather than
random. The spec required specific top-level state variables and function declarations
so the harness can reach live game state. The model produced exactly the right names —
then left them as empty stubs:

```js
let pacman, ghosts, maze, score, lives, powerMode, gameState, dotCount, totalDots;
// Top-level function declarations
function movePacman() {}
function moveGhost() {}
function checkGhostCollisions() {}
```

…and wrote the real implementations 120 lines further down. In JavaScript the later
declarations win, so the game largely still works — but the variables stay `undefined`
until `startGame()` runs, the contract probe throws, and the gate stops before testing
anything.

That is **spec-compliance as ritual**: pattern-matching the shape of a requirement
while missing its purpose. For comparison, a 27B/35B model of the same generation
distilled for reasoning clears this gate.

It does write large coherent programs: a complete self-contained Pac-Man (canvas, four
ghosts, collision, score, game loop, balanced braces, closing `</html>`) in ~12 minutes
at 8,434 tokens — playable structure, with real logic bugs in turn buffering and ghost
pathing.

## Why a smaller model beats it here

The useful mental model:

> **usable capability ≈ active parameters × bits per weight × task fit**

The comparison is not 35B versus 284B. It is *35B at ~4.5 bits, instruction-tuned* versus
*284B at 2.06 bits, reasoning-tuned*. Quantization damage is not linear — below roughly
3 bits, the first casualty is multi-step instruction-following, which is exactly what a
strict spec benchmark measures. And a mixture-of-experts model with ~3B active parameters
per token will comfortably out-run a dense model with far fewer total parameters.

The local-model scene fixates on the first term. On this hardware, the second and third
decide whether the thing is actually useful.

## Verdict

Worth running if you want a frontier-scale model that never leaves your machine and you
can work at ~12 t/s: hard analysis, overnight batch work, second opinions on things you
would not send to a cloud API. Not worth running as a daily coding driver, where a
well-preserved smaller model wins decisively.

Either way, a 284B model at full 131k context on a mini PC iGPU is a genuinely different
2026 than most people assume.
