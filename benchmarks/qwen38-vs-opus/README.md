# Qwen3.8-27B (local, Q8) vs Claude Opus 4.8 — execution-graded coding pilot

A small, **reproducible, execution-graded** head-to-head between the local Qwen3.8-27B
(Q8_0, served on this Strix Halo box — see the
[decode-speed section](../../README.md#decode-speed-ceiling-for-dense-27b-q8-on-gfx1151))
and Claude Opus 4.8. Every task is graded by **running the output**, not by reading it.

## Headline result (2026-08-22)

| bucket | Opus 4.8 | Qwen3.8-27B Q8 |
|---|---|---|
| write a function to pass hidden tests | 3/3 | 3/3 |
| fix a seeded bug | 3/3 | 3/3 |
| add a feature (given tests) | 2/2 | 2/2 |
| build a self-contained app | 2/2 | 2/2 |
| **total correct** | **10/10** | **10/10** |
| avg fix-rounds used | 0.0 | 0.0 |
| avg wall-clock / task | ~29 s | ~320 s |
| **robustness (harder hidden edge cases)** | **9/9** | **9/9** |

On **this pilot the local 27B tied Opus 4.8** — identical correctness *and* robustness,
neither model needing a single retry. The only gap is **speed: Opus was ~11× faster**
(cloud API vs a local model at ~17 tok/s with thinking on). Qwen's solutions were also
consistently *more compact* (e.g. todo 182 vs 226 LOC, snake 126 vs 189) and equally correct.

### Read this result honestly

The tie says something real **and** has a real limit:

- **Real:** for **common, fully-specified, self-contained tasks of this size**, a local
  Q8 27B is genuinely good-enough — as correct and as robust as a frontier model. For that
  class of work the offload case is strong (11× slower, but free, private, on-box).
- **Limit:** these are **classic textbook problems** (roman numerals, LRU cache, binary
  search, a snake game) that are heavily represented in training data and handed over with
  the exact interface pinned. That is the *most favorable* condition for a smaller model.
  The tasks were **not hard enough to discriminate** the two models — which is itself the
  finding. What is *not* tested here: novel/underspecified problems, multi-file codebases,
  and long-horizon debugging, which is where a frontier model is still expected to pull
  ahead. Those need harder suites (Aider polyglot, SWE-bench) to measure.

## Method

- **Execution-graded.** Each task has a deterministic grader that runs the solution
  (`bench.py grade`). Python tasks are executed against assertions; web/game tasks are
  rendered in **headless Chromium** and checked for JS errors and a *non-blank canvas*
  (`verify.py`) — this catches the "runs but shows nothing" class (a NaN transform, dead
  draw loop) that a syntax check cannot see.
- **Graders were validated first.** Every task's reference solution passes its grader, and
  every seeded bug fails it, *before* any model was run — so a broken grader can't fake the
  score.
- **Same harness for both sides.** Both models get the identical task prompt and the same
  **grade-and-retry loop** (run → grade → feed the failure back, ≤3 attempts). Interfaces
  (file names, function signatures) are pinned in each prompt so grading is objective.
- **Quality pass (`analyze.py`).** Beyond pass/fail: each solution is re-run against
  **harder hidden edge cases** (roman `3999`, capacity-1 LRU, whitespace-only lines, pages
  past the end, …). The two apps are additionally *driven* — the todo app must actually add
  an item and persist it across reload; snake's loop must advance the canvas over time.

## The 10 tasks

| id | bucket | what |
|---|---|---|
| d1_roman | function | `roman_to_int` |
| d2_merge | function | `merge_intervals` |
| d3_lru | function | `LRUCache` |
| b1_offbyone | fix-bug | fix an off-by-one in `binary_search` (IndexError) |
| b2_blankcanvas | fix-bug | fix a NaN that makes a `<canvas>` render blank |
| b3_crashempty | fix-bug | stop a script crashing on empty/blank stdin |
| c1_search | feature | add a case-insensitive `search()` to a `Contacts` class |
| c2_paginate | feature | implement `paginate(data, page, per_page)` |
| a1_todo | build | a single-file to-do web app (add/done/delete + localStorage) |
| a2_snake | build | a single-file canvas Snake game |

Full prompts and graders are in [`bench.py`](bench.py); the exact solutions each model
produced are in [`solutions/`](solutions/).

## Reproduce

```bash
# 1. one model at a time (both use the same fix loop)
QWEN_BIN=/path/to/qwen  python3 bench.py run-qwen qwen3.8-27b-think   # local side
# (the opus side was run via an agent per task, then graded with:)
python3 bench.py grade <task_id> <workdir>

# 2. scorecard + quality
python3 bench.py score
python3 analyze.py
```

Needs Python 3, `node` (for JS syntax checks), and Playwright + Pillow (for the headless
render/quality checks). Results append to `results.jsonl`.

## Caveats (so the number is not over-read)

- **Opus is one of the two contestants**, so there is **no hand-scored "elegance"** — every
  score here is execution-based. Judge code taste yourself from [`solutions/`](solutions/).
- Wall-clock is end-to-end incl. self-grading. Opus is a cloud API; Qwen is local at
  ~17 tok/s with thinking on — most of its ~5 min/task is reasoning tokens.
- Model versions: `claude-opus-4-8` and the local `qwen3.8-27b-think` (Q8_0). Hardware:
  AMD Strix Halo (Ryzen AI Max+ 395, gfx1151), llama.cpp Vulkan + MTP.
- Textbook, fully-specified tasks favor a smaller model. This measures a **band of
  difficulty**, not "coding" in general. Harder/less-contaminated suites are the next step.

## Files

- `bench.py` — tasks, graders, the run-and-retry runner, scorecard.
- `analyze.py` — robustness + functional-depth quality pass.
- `verify.py` — the headless-render smoke tester (blank-canvas / JS-error detection).
- `results.jsonl` — raw per-task results.
- `RESULTS.txt` — the scorecard + quality tables as generated.
- `solutions/{qwen,opus}/` — the actual code each model produced, per task.
