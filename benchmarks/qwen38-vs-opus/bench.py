#!/usr/bin/env python3
"""Qwen3.8-27B (local) vs Claude Opus 4.8 — execution-graded coding pilot.

10 tasks, 4 buckets, every task graded by RUNNING the output (not reading it):
  D  write a function that must pass hidden tests
  B  fix a seeded bug in existing code
  C  add a feature to existing code, given tests
  A  build a self-contained app/game

Both models get the SAME fix loop (run -> grade -> feed the failure back, up to N rounds),
so we compare models, not harnesses. Interfaces are pinned in each prompt so grading is
deterministic. Web tasks are graded with the bridge's verify.py (headless render).

Usage:
  bench.py seed <task_id> <workdir>      # write starter files for a task into workdir
  bench.py prompt <task_id>              # print the task prompt (what the model is given)
  bench.py grade <task_id> <workdir>     # grade whatever is in workdir -> exit 0 pass / 1 fail
  bench.py run-qwen <model> [task_id...]  # run the qwen CLI side end-to-end with the fix loop
  bench.py score                          # print the scorecard from results.jsonl
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results.jsonl"
# verify.py (the headless render grader) is bundled alongside this file.
FIX_ROUNDS = int(os.environ.get("BENCH_FIX_ROUNDS", "2"))
QWEN = os.environ.get("QWEN_BIN", "qwen")     # path to the qwen-code CLI (set QWEN_BIN if not on PATH)


# --------------------------------------------------------------------------- graders
def _pyrun(wd, code, timeout=20):
    """Run a python snippet inside wd; pass = exit 0 and 'PASS' printed."""
    r = subprocess.run([sys.executable, "-c", code], cwd=str(wd),
                       capture_output=True, text=True, timeout=timeout)
    ok = r.returncode == 0 and "PASS" in r.stdout
    why = "" if ok else (r.stderr.strip() or r.stdout.strip())[-400:]
    return ok, why


def g_roman(wd):
    return _pyrun(wd, "from solution import roman_to_int as f\n"
        "for s,n in [('III',3),('IV',4),('IX',9),('LVIII',58),('MCMXCIV',1994),('XL',40)]:\n"
        "    assert f(s)==n, (s,f(s),n)\nprint('PASS')")

def g_merge(wd):
    return _pyrun(wd, "from solution import merge_intervals as f\n"
        "assert f([[1,3],[2,6],[8,10],[15,18]])==[[1,6],[8,10],[15,18]], f([[1,3],[2,6],[8,10],[15,18]])\n"
        "assert f([[1,4],[4,5]])==[[1,5]]\nassert f([])==[]\nassert f([[1,4],[0,4]])==[[0,4]]\nprint('PASS')")

def g_lru(wd):
    return _pyrun(wd, "from solution import LRUCache\n"
        "c=LRUCache(2); c.put(1,1); c.put(2,2)\nassert c.get(1)==1\nc.put(3,3)\n"
        "assert c.get(2)==-1\nc.put(4,4)\nassert c.get(1)==-1 and c.get(3)==3 and c.get(4)==4\nprint('PASS')")

def g_offbyone(wd):
    return _pyrun(wd, "from binsearch import binary_search as f\n"
        "a=[1,3,5,7,9,11]\nfor i,v in enumerate(a): assert f(a,v)==i,(v,f(a,v),i)\n"
        "assert f(a,4)==-1 and f(a,12)==-1 and f([],1)==-1 and f([2],2)==0\nprint('PASS')")

def g_crash_empty(wd):
    # the script must handle empty stdin without a traceback and print a total of 0
    r = subprocess.run([sys.executable, "sumlines.py"], cwd=str(wd),
                       input="", capture_output=True, text=True, timeout=20)
    ok1 = r.returncode == 0
    r2 = subprocess.run([sys.executable, "sumlines.py"], cwd=str(wd),
                        input="3\n4\n10\n", capture_output=True, text=True, timeout=20)
    ok2 = r2.returncode == 0 and "17" in r2.stdout
    ok = ok1 and ok2
    return ok, "" if ok else f"empty:rc={r.returncode} err={r.stderr[-150:]} | nums:out={r2.stdout[-80:]}"

def g_search(wd):
    return _pyrun(wd, "from contacts import Contacts\n"
        "c=Contacts()\nc.add('Alice','a@x.com'); c.add('Bob','bob@y.com'); c.add('alison','al@z.com')\n"
        "r=sorted(x[0] for x in c.search('al'))\nassert r==['Alice','alison'], r\n"
        "assert c.search('nope')==[]\nassert sorted(x[0] for x in c.search('B'))==['Bob']\nprint('PASS')")

def g_paginate(wd):
    return _pyrun(wd, "from paginate import paginate as p\n"
        "d=list(range(1,26))\nassert p(d,1,10)==list(range(1,11))\nassert p(d,3,10)==[21,22,23,24,25]\n"
        "assert p(d,4,10)==[]\nassert p([],1,10)==[]\nprint('PASS')")

def _verify_web(wd, entry="index.html", need_dom=None):
    sys.path.insert(0, str(ROOT))
    import verify  # noqa (bundled beside this file)
    res = verify.verify(wd, [Path(wd) / entry])
    if not res.ok:
        return False, res.summary + (" | " + res.fix_hint[:120] if res.fix_hint else "")
    return True, res.summary

def g_todo(wd):
    # renders w/o error, non-trivial, and the page exposes an add-item control
    ok, why = _verify_web(wd)
    if not ok:
        return False, why
    html = (Path(wd) / "index.html").read_text(errors="ignore").lower()
    has_input = ("input" in html) and ("button" in html or "onsubmit" in html or "addeventlistener" in html)
    return (has_input, "" if has_input else "no add-item input/button found in the todo app")

def g_snake(wd):
    ok, why = _verify_web(wd)
    if not ok:
        return False, why
    html = (Path(wd) / "index.html").read_text(errors="ignore").lower()
    has_loop = "requestanimationframe" in html or "setinterval" in html
    has_canvas = "<canvas" in html
    return (has_loop and has_canvas, "" if (has_loop and has_canvas) else "snake missing canvas or a game loop")


# --------------------------------------------------------------------------- tasks
TASKS = [
    dict(id="d1_roman", bucket="D-function", grade=g_roman, seed={},
         prompt="Write a file `solution.py` containing a function `roman_to_int(s: str) -> int` "
                "that converts a Roman numeral string (e.g. 'MCMXCIV') to its integer value. "
                "Handle the subtractive cases (IV=4, IX=9, XL=40, XC=90, CD=400, CM=900). "
                "Output only the file."),
    dict(id="d2_merge", bucket="D-function", grade=g_merge, seed={},
         prompt="Write a file `solution.py` containing a function `merge_intervals(intervals: "
                "list[list[int]]) -> list[list[int]]` that merges all overlapping intervals and "
                "returns them sorted by start. E.g. [[1,3],[2,6],[8,10],[15,18]] -> "
                "[[1,6],[8,10],[15,18]]. Handle the empty list. Output only the file."),
    dict(id="d3_lru", bucket="D-function", grade=g_lru, seed={},
         prompt="Write a file `solution.py` containing a class `LRUCache` with `__init__(self, "
                "capacity: int)`, `get(self, key) -> int` (returns -1 if absent), and "
                "`put(self, key, value)`. Evict the least-recently-used item when over capacity. "
                "get and put both count as a use. Output only the file."),
    dict(id="b1_offbyone", bucket="B-fixbug", grade=g_offbyone,
         seed={"binsearch.py": "def binary_search(a, target):\n"
               "    lo, hi = 0, len(a)\n"          # BUG: hi should be len(a)-1 (or use hi=len(a) with lo<hi)
               "    while lo <= hi:\n"
               "        mid = (lo + hi) // 2\n"
               "        if a[mid] == target:\n"
               "            return mid\n"
               "        elif a[mid] < target:\n"
               "            lo = mid + 1\n"
               "        else:\n"
               "            hi = mid - 1\n"
               "    return -1\n"},
         prompt="The file `binsearch.py` has a `binary_search(a, target)` that should return the "
                "index of target in the sorted list `a`, or -1 if absent. It has a bug (it can "
                "raise IndexError / miss elements). Fix `binsearch.py` in place so it is correct "
                "for all inputs including empty lists. Keep the function name and signature."),
    dict(id="b2_blankcanvas", bucket="B-fixbug", grade=lambda wd: _verify_web(wd),
         seed={"index.html": (
             "<!doctype html><html><head><meta charset=utf-8><style>html,body{margin:0}"
             "canvas{display:block}</style></head><body><canvas id=c width=640 height=420></canvas>"
             "<script>\nconst cv=document.getElementById('c');const ctx=cv.getContext('2d');\n"
             "const state={x:100,y:100};\nfunction draw(){\n"
             "  ctx.fillStyle='#0a1020';ctx.fillRect(0,0,cv.width,cv.height);\n"
             "  // BUG: box uses state.vx which was never defined -> NaN -> nothing visible\n"
             "  ctx.fillStyle='#e33';ctx.fillRect(state.x+state.vx, state.y, 60, 60);\n"
             "  requestAnimationFrame(draw);\n}\ndraw();\n</script></body></html>")},
         prompt="`index.html` is a small canvas app that should draw a red box on a dark "
                "background, but the canvas renders blank. Find and fix the bug in `index.html` "
                "so the red box is actually visible. It runs but shows nothing — the classic "
                "'renders blank' bug. Fix it in place."),
    dict(id="b3_crashempty", bucket="B-fixbug", grade=g_crash_empty,
         seed={"sumlines.py": "import sys\n"
               "nums = [int(x) for x in sys.stdin.read().split('\\n')]\n"  # BUG: '' -> int('') crash
               "print('total', sum(nums))\n"},
         prompt="`sumlines.py` reads integers, one per line, from stdin and prints their total. "
                "It crashes when a line is blank or the input is empty. Fix `sumlines.py` so it "
                "handles blank lines and empty input (printing a total of 0), and still sums "
                "normal input like '3\\n4\\n10' to 17. Keep it runnable as `python3 sumlines.py`."),
    dict(id="c1_search", bucket="C-feature", grade=g_search,
         seed={"contacts.py": "class Contacts:\n    def __init__(self):\n        self._c = []\n"
               "    def add(self, name, email):\n        self._c.append((name, email))\n"},
         prompt="Add a method `search(self, query: str) -> list` to the `Contacts` class in "
                "`contacts.py`. It returns the list of (name, email) tuples whose NAME contains "
                "`query` case-insensitively. Empty result if none match. Keep `add` working. "
                "Edit the file in place."),
    dict(id="c2_paginate", bucket="C-feature", grade=g_paginate,
         seed={"paginate.py": "# implement paginate(data, page, per_page) below\n"},
         prompt="In `paginate.py`, implement `paginate(data: list, page: int, per_page: int) -> "
                "list` returning the slice of `data` for 1-indexed `page` with `per_page` items "
                "each. page 1 = first per_page items; a page past the end returns []. Handle the "
                "empty list. Edit the file in place."),
    dict(id="a1_todo", bucket="A-build", grade=g_todo, seed={},
         prompt="Build a self-contained to-do web app as a single file `index.html` (inline CSS "
                "+ JS, no external libraries or network). It must let the user type a task in a "
                "text input and add it to a visible list via a button or Enter, mark items done, "
                "and delete them. Persist with localStorage. Must run with no console errors."),
    dict(id="a2_snake", bucket="A-build", grade=g_snake, seed={},
         prompt="Build the classic Snake game as a single self-contained file `index.html` using "
                "an HTML5 <canvas> and vanilla JS (no libraries/network). Arrow keys steer a "
                "snake on a grid, eating food grows it and scores, hitting the wall or itself "
                "ends the game. Use a game loop (requestAnimationFrame or setInterval). Show the "
                "score. Must run with no console errors and actually draw the board."),
]
BYID = {t["id"]: t for t in TASKS}


# --------------------------------------------------------------------------- harness
def seed(task, wd: Path):
    wd.mkdir(parents=True, exist_ok=True)
    for name, content in task.get("seed", {}).items():
        (wd / name).write_text(content)


def grade(task, wd: Path):
    try:
        ok, why = task["grade"](Path(wd))
        return bool(ok), str(why)
    except subprocess.TimeoutExpired:
        return False, "grader timed out (likely a hang / infinite loop)"
    except Exception as e:  # noqa: BLE001
        return False, f"grader error: {type(e).__name__}: {e}"


def run_qwen(task, wd: Path, model: str):
    """Run the qwen CLI with the same fix loop the bridge uses. Returns a result dict."""
    seed(task, wd)
    prompt = task["prompt"]
    t0 = time.time()
    rounds = 0
    passed, why = False, ""
    while rounds <= FIX_ROUNDS:
        env = dict(os.environ)
        try:
            subprocess.run([QWEN, "-p", prompt, "-o", "text", "-y", "-m", model],
                           cwd=str(wd), env=env, capture_output=True, text=True, timeout=1800)
        except subprocess.TimeoutExpired:
            why = "qwen run timed out (30 min)"
            break
        passed, why = grade(task, wd)
        if passed:
            break
        if rounds == FIX_ROUNDS:
            break
        rounds += 1
        prompt = (f"Your solution FAILED an automated test:\n{why}\n\n"
                  f"Fix it in place in this directory. Original task:\n{task['prompt']}")
    return dict(task=task["id"], bucket=task["bucket"], model=f"qwen:{model}",
                passed=passed, fix_rounds=rounds, secs=round(time.time() - t0, 1), why=why[:300])


def _append(rec):
    with RESULTS.open("a") as f:
        f.write(json.dumps(rec) + "\n")


def score():
    if not RESULTS.exists():
        print("no results yet"); return
    rows = [json.loads(l) for l in RESULTS.read_text().splitlines() if l.strip()]
    models = sorted({r["model"] for r in rows})
    buckets = ["D-function", "B-fixbug", "C-feature", "A-build"]
    print(f"\n{'':16}", *[f"{m:>22}" for m in models])
    for b in buckets:
        cells = []
        for m in models:
            sub = [r for r in rows if r["model"] == m and r["bucket"] == b]
            p = sum(r["passed"] for r in sub)
            cells.append(f"{p}/{len(sub)}" if sub else "-")
        print(f"{b:16}", *[f"{c:>22}" for c in cells])
    print("-" * (16 + 23 * len(models)))
    for m in models:
        sub = [r for r in rows if r["model"] == m]
        p = sum(r["passed"] for r in sub)
        avg_r = sum(r["fix_rounds"] for r in sub) / max(1, len(sub))
        avg_t = sum(r["secs"] for r in sub) / max(1, len(sub))
        print(f"{m}: {p}/{len(sub)} passed | avg fix-rounds {avg_r:.1f} | avg {avg_t:.0f}s/task")


def main():
    if len(sys.argv) < 2:
        print(__doc__); return
    cmd = sys.argv[1]
    if cmd == "prompt":
        print(BYID[sys.argv[2]]["prompt"])
    elif cmd == "seed":
        seed(BYID[sys.argv[2]], Path(sys.argv[3]))
        print("seeded", sys.argv[3])
    elif cmd == "grade":
        ok, why = grade(BYID[sys.argv[2]], Path(sys.argv[3]))
        print("PASS" if ok else "FAIL", "-", why)
        sys.exit(0 if ok else 1)
    elif cmd == "run-qwen":
        model = sys.argv[2]
        ids = sys.argv[3:] or [t["id"] for t in TASKS]
        for tid in ids:
            wd = ROOT / "runs" / f"qwen_{tid}"
            rec = run_qwen(BYID[tid], wd, model)
            _append(rec)
            print(f"[{rec['passed'] and 'PASS' or 'FAIL'}] {tid} "
                  f"rounds={rec['fix_rounds']} {rec['secs']}s  {rec['why'][:80]}")
        score()
    elif cmd == "score":
        score()
    else:
        print("unknown:", cmd)


if __name__ == "__main__":
    main()
