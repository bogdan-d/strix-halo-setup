# Pac-Man gate — a local-LLM coding benchmark that measures the *game*, not the checklist

A single prompt (`SPEC.md`), a Playwright judge (`gate.py`) that plays the
generated HTML in a real browser, and — the part that matters — a **reference
implementation** the judge is calibrated against.

## Why the reference exists

The judge ran for weeks without one. On 2026-08-02 a 284B model produced a build
that scored **10 of 14** and was unplayable: one arrow key moved Pac-Man exactly
one cell, and he then froze forever. Every motion check had been satisfied by
that single step.

An instrument that has never been shown a correct answer cannot grade a wrong
one. `reference/pacman.html` is that correct answer — it scores **17/17** and is
genuinely playable. Writing it immediately exposed two long-standing judge bugs
and produced three new checks.

## Judge bugs the reference found

| Bug | Effect |
|---|---|
| `eating a dot` asserted **exactly one** dot per 600 ms | Silently failed any game running faster than ~1.6 cells/sec. A correct Pac-Man eats 3–4 in that window. Now asserts the speed-independent invariant: **+10 score per dot eaten**. |
| No sustained-motion check | A game that moves one cell and freezes passed. |
| No liveness-after-play check | A game that accepts input once and then ignores it passed. |

Added checks: **keeps moving through sustained play** (≥4 distinct cells while
steering), **still responds to input after 8 s**, **score keeps climbing in a
second burst**. The 10/14 build scores **11/17 FAILED** under them.

## Reference bugs worth stealing

Each cost a debugging round and each is a plausible failure in model output too:

- **Sealed ghost house** — the door was carved one column off; a flood fill found
  17 unreachable cells. *Flood-fill your maze before trusting it.*
- **Pac-Man spawned in a corridor walled above and below**, so any up/down probe
  reported "stuck".
- **No scatter/chase waves** — ghosts beelined from t=0, killed an idle Pac-Man
  repeatedly, and each death reset the house timers, so two ghosts never left.
- **Frightened ghosts fleeing to scatter corners** are uncatchable, which makes
  the power pellet decorative. They flee *locally* and at half speed.
- **Eaten ghosts must rehouse immediately** (the spec says so); an eyes-walk-home
  animation fails the contract.
- **A queued turn is consumed when applied, but direction is held at a wall.**
  Clearing direction at a wall makes Pac-Man stop dead until the next keypress —
  which reads as "the game keeps getting stuck".

## Running it

```bash
pip install playwright pillow numpy && playwright install chromium
python3 gate.py path/to/pacman.html          # any candidate build
python3 gate.py reference/pacman.html        # should print 17/17 ALL PASS
```

Feed `SPEC.md` to a model, save its HTML, and score it. The reference is the
control: if the judge ever fails it, the judge is wrong.

## Scores observed (single roll each — see the caveat)

| model | score |
|---|---|
| reference (this repo) | 17/17 |
| DeepSeek-V4-Flash 0731, Q8-attention 2-bit quant | 10/14 on the *old* judge; 11/17 failed on the new one |
| Qwen3.6-35B-A3B (stock) | 8/14 on the old judge |

⚠ **One roll per model, temperature 1.0.** The same model and prompt produced
0-reached and 4/14 an hour apart, so single-roll scores are close to coin flips.
Treat any gap under ~4 checks as noise, and re-run before believing a ranking.
