#!/usr/bin/env python3
"""Quality layer for the pilot: beyond pass/fail, measure robustness + code size.

For each task and each model's saved solution:
  * robustness — run HARDER edge cases the base grader never tested (a solution can pass
    the basic test yet be fragile). Execution-based, objective.
  * functional depth for the apps — actually drive the todo app (add + persist) and check
    the snake loop advances (canvas changes over time), not just "renders".
  * loc — non-blank lines of the primary solution file.

Usage: analyze.py            # table over runs/{qwen,opus}_* for every task
       analyze.py <id> <wd>  # one solution
"""
from __future__ import annotations
import json, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent  # verify.py is bundled here
PRIMARY = {"d1_roman": "solution.py", "d2_merge": "solution.py", "d3_lru": "solution.py",
           "b1_offbyone": "binsearch.py", "b2_blankcanvas": "index.html",
           "b3_crashempty": "sumlines.py", "c1_search": "contacts.py",
           "c2_paginate": "paginate.py", "a1_todo": "index.html", "a2_snake": "index.html"}


def _py(wd, code, inp=None, timeout=20):
    r = subprocess.run([sys.executable, "-c", code], cwd=str(wd), input=inp,
                       capture_output=True, text=True, timeout=timeout)
    ok = r.returncode == 0 and "PASS" in r.stdout
    return ok, ("" if ok else (r.stderr.strip() or r.stdout.strip())[-200:])


def _script(wd, name, inp, want, timeout=20):
    r = subprocess.run([sys.executable, name], cwd=str(wd), input=inp,
                       capture_output=True, text=True, timeout=timeout)
    ok = r.returncode == 0 and want in r.stdout
    return ok, ("" if ok else f"rc={r.returncode} out={r.stdout[-80:]} err={r.stderr[-80:]}")


def rob_d1(wd):
    return _py(wd, "from solution import roman_to_int as f\n"
        "for s,n in [('MMMCMXCIX',3999),('D',500),('CM',900),('CD',400),('XC',90),('I',1),('MMXXIV',2024)]:\n"
        "    assert f(s)==n,(s,f(s),n)\nprint('PASS')")

def rob_d2(wd):
    return _py(wd, "from solution import merge_intervals as f\n"
        "assert f([[6,8],[1,9],[2,4],[4,7]])==[[1,9]]      # unsorted, all overlap\n"
        "assert f([[1,4],[2,3]])==[[1,4]]                  # fully nested\n"
        "assert f([[-5,-2],[-3,0]])==[[-5,0]]              # negatives\n"
        "assert f([[1,1]])==[[1,1]]\nprint('PASS')")

def rob_d3(wd):
    return _py(wd, "from solution import LRUCache\n"
        "c=LRUCache(1); c.put(1,1); c.put(2,2)\nassert c.get(1)==-1 and c.get(2)==2   # cap 1\n"
        "c2=LRUCache(2); c2.put(1,1); c2.put(1,10)\nassert c2.get(1)==10               # update value\n"
        "print('PASS')")

def rob_b1(wd):
    return _py(wd, "from binsearch import binary_search as f\n"
        "assert f([5],5)==0 and f([5],3)==-1\n"
        "a=list(range(0,100,2))\nassert f(a,0)==0 and f(a,98)==49 and f(a,50)==25 and f(a,51)==-1\n"
        "assert f([-10,-3,0,7],-3)==1\nprint('PASS')")

def rob_b3(wd):
    ok1, d1 = _script(wd, "sumlines.py", " \n\n5\n\n-3\n", "2")   # blanks + negatives -> 2
    ok2, d2 = _script(wd, "sumlines.py", "  \n \n", "0")          # whitespace only -> 0
    return (ok1 and ok2), ("" if (ok1 and ok2) else f"blanks:{d1} ws:{d2}")

def rob_c1(wd):
    return _py(wd, "from contacts import Contacts\n"
        "c=Contacts(); c.add('Charlie','c@x'); c.add('bob','b@x')\n"
        "assert sorted(x[0] for x in c.search('AR'))==['Charlie']   # mid-substring, case-insensitive\n"
        "assert c.search('z')==[]\nprint('PASS')")

def rob_c2(wd):
    return _py(wd, "from paginate import paginate as p\n"
        "assert p([1,2,3],1,10)==[1,2,3]                 # per_page > len\n"
        "d=list(range(1,11))\nassert p(d,2,5)==[6,7,8,9,10] and p(d,3,5)==[]\n"
        "assert p([1,2,3,4],2,2)==[3,4]\nprint('PASS')")


def _pw(wd, fn, timeout=30):
    """Run fn(page) inside a headless page serving wd/index.html; fail-open on harness error."""
    sys.path.insert(0, str(ROOT)); import verify  # bundled beside this file
    from playwright.sync_api import sync_playwright
    httpd, port = verify._serve(Path(wd))
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True, args=[
                "--enable-unsafe-swiftshader", "--use-gl=angle", "--use-angle=swiftshader"])
            pg = b.new_page(viewport={"width": 640, "height": 480})
            pg.route("**/*", lambda r: (r.continue_() if r.request.url.startswith("http://127.0.0.1")
                                        else r.fulfill(status=200, body="")))
            pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load", timeout=timeout * 1000)
            out = fn(pg, port)
            b.close()
            return out
    except Exception as e:  # noqa: BLE001 — harness issue never counts against the model
        return None, f"(inconclusive: {type(e).__name__})"
    finally:
        try: httpd.shutdown()
        except Exception: pass


def rob_a1_todo(wd):
    def drive(pg, port):
        pg.wait_for_timeout(300)
        inp = pg.query_selector("input[type=text], input:not([type])")
        if not inp:
            return False, "no text input found"
        inp.fill("buy milk")
        # try Enter then any button
        pg.keyboard.press("Enter")
        for b in pg.query_selector_all("button"):
            try: b.click(timeout=500)
            except Exception: pass
            if "buy milk" in pg.inner_text("body"): break
        pg.wait_for_timeout(200)
        added = "buy milk" in pg.inner_text("body")
        # reload -> persisted?
        pg.reload(wait_until="load"); pg.wait_for_timeout(300)
        persisted = "buy milk" in pg.inner_text("body")
        ok = added and persisted
        return ok, ("" if ok else f"added={added} persisted={persisted}")
    r = _pw(wd, drive)
    return (False, r[1]) if r[0] is None else r

def rob_a2_snake(wd):
    def drive(pg, port):
        pg.wait_for_timeout(400)
        s1 = pg.screenshot()
        pg.wait_for_timeout(700)   # loop should advance the board
        s2 = pg.screenshot()
        moving = s1 != s2
        return moving, ("" if moving else "canvas identical after 700ms — game loop not advancing")
    r = _pw(wd, drive)
    return (False, r[1]) if r[0] is None else r


ROB = {"d1_roman": rob_d1, "d2_merge": rob_d2, "d3_lru": rob_d3, "b1_offbyone": rob_b1,
       "b2_blankcanvas": None,  # render quality is the base check; nothing extra to prove
       "b3_crashempty": rob_b3, "c1_search": rob_c1, "c2_paginate": rob_c2,
       "a1_todo": rob_a1_todo, "a2_snake": rob_a2_snake}


def loc(wd, task):
    f = Path(wd) / PRIMARY[task]
    if not f.exists():
        return 0
    return sum(1 for ln in f.read_text(errors="ignore").splitlines() if ln.strip())


def analyze(task, wd):
    fn = ROB.get(task)
    if fn is None:
        rob, detail = None, "n/a"
    else:
        try:
            rob, detail = fn(Path(wd))
        except subprocess.TimeoutExpired:
            rob, detail = False, "timed out"
        except Exception as e:  # noqa: BLE001
            rob, detail = None, f"harness err: {e}"
    return dict(task=task, loc=loc(wd, task), robust=rob, detail=str(detail)[:120])


def main():
    if len(sys.argv) == 3:
        print(json.dumps(analyze(sys.argv[1], sys.argv[2]), indent=2)); return
    tasks = list(PRIMARY)
    print(f"\n{'task':16}{'loc q/o':>12}{'robust q':>10}{'robust o':>10}   detail")
    for t in tasks:
        rows = {}
        for m in ("qwen", "opus"):
            wd = ROOT / "runs" / f"{m}_{t}"
            rows[m] = analyze(t, wd) if wd.exists() else dict(loc=0, robust=None, detail="no run")
        def mark(r):
            return "PASS" if r is True else ("FAIL" if r is False else "-")
        d = rows["qwen"]["detail"] if rows["qwen"]["robust"] is False else rows["opus"]["detail"]
        print(f"{t:16}{str(rows['qwen']['loc'])+'/'+str(rows['opus']['loc']):>12}"
              f"{mark(rows['qwen']['robust']):>10}{mark(rows['opus']['robust']):>10}   {d[:60]}")


if __name__ == "__main__":
    main()
