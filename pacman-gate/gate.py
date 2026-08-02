#!/usr/bin/env python3
"""Deterministic acceptance gate for pacman.html. Every check prints PASS/FAIL. Exit 0 only if all pass."""
import os, sys, random, io, math
from playwright.sync_api import sync_playwright
import PIL.Image, PIL.ImageChops
import numpy as np

FNAME = sys.argv[1] if len(sys.argv) > 1 else "pacman.html"
results = []
def check(name, ok, detail=""):
    ok = bool(ok)                      # floats/objects leaked in and produced "26.45/22" summaries
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not ok else ""))

errors = []
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={'width':390,'height':844}, has_touch=True, is_mobile=True)
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: errors.append(str(e)[:200]))
    def fresh_start():
        pg.goto("file://" + os.path.abspath(FNAME)); pg.wait_for_timeout(1000)
        for attempt in range(3):
            try:
                bx = pg.locator("text=PLAY").first.bounding_box()
                pg.touchscreen.tap(bx['x']+bx['width']/2, bx['y']+bx['height']/2)
            except Exception:
                try:
                    cb = pg.locator("canvas").first.bounding_box()
                    pg.touchscreen.tap(cb['x']+cb['width']/2, cb['y']+cb['height']/2)
                except Exception:
                    pass
            pg.wait_for_timeout(500)
            if pg.evaluate("() => typeof gameState!=='undefined' && gameState==='playing'"):
                return
            try:
                pg.locator("text=PLAY").first.click(timeout=2000); pg.wait_for_timeout(500)
            except Exception:
                pass
            if pg.evaluate("() => typeof gameState!=='undefined' && gameState==='playing'"):
                return
    pg.goto("file://" + os.path.abspath(FNAME)); pg.wait_for_timeout(1000)

    # 1. PLAY starts via touch
    def tap_start():
        try:
            box = pg.locator("text=PLAY").first.bounding_box()
            pg.touchscreen.tap(box['x']+box['width']/2, box['y']+box['height']/2)
        except Exception:
            try:
                cb = pg.locator("canvas").first.bounding_box()
                pg.touchscreen.tap(cb['x']+cb['width']/2, cb['y']+cb['height']/2)
            except Exception:
                pass
        pg.wait_for_timeout(500)
    tap_start()
    started = pg.evaluate("() => typeof gameState !== 'undefined' && gameState === 'playing'")
    if not started:
        tap_start()
        started = pg.evaluate("() => typeof gameState !== 'undefined' && gameState === 'playing'")
    check("PLAY starts game via touch", started)

    # 2. testability contract
    contract = pg.evaluate("""() => {
      try { return {pac: typeof pacman==='object' && 'x' in pacman && 'prev' in pacman,
        gh: Array.isArray(ghosts) && ghosts.length===4 && 'prev' in ghosts[0],
        fns: [movePacman, moveGhost, checkGhostCollisions].every(f=>typeof f==='function'),
        maze: Array.isArray(maze), dots: typeof totalDots==='number' && totalDots>50}; }
      catch(e){ return null; } }""")
    check("testability contract (top-level state + functions, >50 dots)", bool(contract) and all(contract.values()),
          str(contract))
    if not (bool(contract) and all(contract.values())):
        print("SUMMARY: 0 further checks run — fix the contract first"); b.close(); sys.exit(1)

    # 3. ghosts all exit house <= 8s
    pg.wait_for_timeout(8000)
    housed = pg.evaluate("() => ghosts.map(g=>!!g.inHouse)")
    check("all 4 ghosts out of house by 8s", not any(housed), f"inHouse={housed}")

    # 4. chase convergence: no input, blinky closes distance
    d0 = pg.evaluate("() => Math.abs(ghosts[0].x-pacman.x)+Math.abs(ghosts[0].y-pacman.y)")
    dmin = d0
    for _ in range(12):
        pg.wait_for_timeout(1000)
        st = pg.evaluate("() => gameState")
        if st != 'playing':
            dmin = min(dmin, 3)  # a death means a ghost REACHED pacman: chase proven
            break
        d = pg.evaluate("() => Math.abs(ghosts[0].x-pacman.x)+Math.abs(ghosts[0].y-pacman.y)")
        dmin = min(dmin, d)
        if dmin <= 3: break
    check("blinky chases (closes to <=3 cells within 12s)", dmin <= 3, f"start {d0}, min {dmin}")

    # 5. ghosts actually moving (no frozen ghost)
    fresh_start()
    moved = pg.evaluate("""() => { window.__gp = ghosts.map(g=>[g.x,g.y]); return true; }""")
    pg.wait_for_timeout(2500)
    frozen = pg.evaluate("""() => ghosts.map((g,i)=> g.inHouse ? false : (g.x===window.__gp[i][0] && g.y===window.__gp[i][1]))""")
    check("no out-of-house ghost frozen over 2.5s", not any(frozen), f"frozen={frozen}")

    # 11. natural play: swipes raise score
    def swipe(dx,dy):
        pg.evaluate(f"""() => {{
          const cv=document.querySelector('canvas'); const r=cv.getBoundingClientRect();
          const cx=r.x+r.width/2, cy=r.y+r.height/2;
          const t=(x,y)=>new Touch({{identifier:1,target:cv,clientX:x,clientY:y}});
          for (const el of [cv, document.body]) {{
            el.dispatchEvent(new TouchEvent('touchstart',{{touches:[t(cx,cy)],changedTouches:[t(cx,cy)],bubbles:true,cancelable:true}}));
            el.dispatchEvent(new TouchEvent('touchend',{{touches:[],changedTouches:[t(cx+{dx},cy+{dy})],bubbles:true,cancelable:true}}));
          }} }}""")
    fresh_start()
    s0 = pg.evaluate("() => score"); random.seed(4)
    for _ in range(14): swipe(*random.choice([(80,0),(-80,0),(0,80),(0,-80)])); pg.wait_for_timeout(300)
    s1 = pg.evaluate("() => score")
    check("swipes steer + dots eaten in natural play", s1 > s0, f"score {s0} -> {s1}")

    # 11b. SUSTAINED MOVEMENT (added 2026-08-02 after a build scored 10/14 while
    # being unplayable: one arrow key moved pacman exactly ONE cell and it then
    # stopped forever. Every motion check here was satisfied by that single step
    # — "score went up once" and "pixels changed once" are not "the game runs".)
    # One input, then sample the position repeatedly: a working game keeps
    # advancing cell to cell until it hits a wall; a broken one freezes.
    fresh_start()
    seen = []
    for i, key in enumerate(["ArrowRight","ArrowDown","ArrowLeft","ArrowUp"]*3):
        pg.keyboard.press(key); pg.wait_for_timeout(250)
        seen.append(pg.evaluate("() => `${pacman.x},${pacman.y}`"))
    distinct = len(set(seen))
    check("keeps moving through sustained play (>=4 distinct cells)", distinct >= 4,
          f"{distinct} distinct positions: {seen[:6]}")

    # 11c. STILL ALIVE LATER: re-steer after 8 seconds of play. A game that
    # accepts input once and then ignores it passes every one-shot probe.
    pg.wait_for_timeout(8000)
    before = pg.evaluate("() => `${pacman.x},${pacman.y}`")
    pg.keyboard.press("ArrowDown"); pg.wait_for_timeout(400)
    pg.keyboard.press("ArrowUp"); pg.wait_for_timeout(1200)
    after = pg.evaluate("() => `${pacman.x},${pacman.y}`")
    check("still responds to input after 8s of play", before != after,
          f"pos {before} -> {after}")

    # 11d. SCORE KEEPS CLIMBING: a live game eats dots continuously, not once.
    s2 = pg.evaluate("() => score")
    for _ in range(10): swipe(*random.choice([(80,0),(-80,0),(0,80),(0,-80)])); pg.wait_for_timeout(300)
    s3 = pg.evaluate("() => score")
    check("score keeps climbing in continued play (2nd burst)", s3 > s2,
          f"score {s2} -> {s3}")

    # 12. smoothness: interpolated rendering
    frames=[]
    for _ in range(20):
        frames.append(PIL.Image.open(io.BytesIO(pg.screenshot())).convert('RGB')); pg.wait_for_timeout(50)
    moving = sum(1 for i in range(19) if (np.array(PIL.ImageChops.difference(frames[i],frames[i+1])).sum(axis=2)>30).sum()>20)
    check("motion rendered every frame (interpolation)", moving >= 10, f"{moving}/19 moving pairs")

    # 6. dot eat: move onto a dot cell
    fresh_start()
    pre6 = pg.evaluate("""() => {
      for (let r=0;r<maze.length;r++) for (let c=1;c<maze[r].length;c++)
        if (maze[r][c]===2 && maze[r][c-1]!==1 && maze[r][c-1]!==4) {
          pacman.prev={x:c-1,y:r}; pacman.x=c-1; pacman.y=r;
          return {s0:score, d0:dotCount}; } }""")
    pg.keyboard.press("ArrowRight"); pg.wait_for_timeout(600)
    r6 = pg.evaluate(f"() => ({{ds: score-{pre6['s0']}, dd: dotCount-{pre6['d0']}}})") if pre6 else None
    # Speed-independent: +10 per dot, at least one eaten. (Was ds==10 and dd==1,
    # which failed any game running faster than ~1.6 cells/sec — a correct
    # reference build eats 3 dots in the same 600ms window.)
    check("eating a dot: +10 score per dot eaten",
          bool(r6) and r6['dd'] >= 1 and r6['ds'] == r6['dd']*10, str(r6))

    # 7. power pellet by real move: +50, powerMode on, expires 5-10s
    pre7 = pg.evaluate("""() => {
      for (let r=0;r<maze.length;r++) for (let c=1;c<maze[r].length;c++)
        if (maze[r][c]===3 && maze[r][c-1]!==1 && maze[r][c-1]!==4) {
          pacman.prev={x:c-1,y:r}; pacman.x=c-1; pacman.y=r;
          return {s0:score}; }
      return null; }""")
    pg.keyboard.press("ArrowRight"); pg.wait_for_timeout(600)
    r7 = pg.evaluate(f"() => ({{ds: score-{pre7['s0']}, power: powerMode}})") if pre7 else 'no pellet reachable'
    ok7 = isinstance(r7, dict) and r7['ds']==50 and r7['power']
    check("power pellet: +50 and powerMode fires", ok7, str(r7))
    expired = False
    if ok7:
        pg.evaluate("() => { lives=9; }")
        pg.wait_for_timeout(4500)
        mid = pg.evaluate("() => { lives=9; if (gameState!=='playing') gameState='playing'; return powerMode; }")
        pg.wait_for_timeout(5500)
        expired = pg.evaluate("() => !powerMode") and mid
    check("power mode lasts ~7s (on at 4.5s, off by 10s)", expired)

    # 8. frightened ghost eaten: +200, rehoused
    r8 = pg.evaluate("""() => { powerMode=true;
      ghosts[0].inHouse=false; ghosts[0].x=pacman.x; ghosts[0].y=pacman.y; ghosts[0].prev={x:pacman.x,y:pacman.y};
      const s0=score; checkGhostCollisions(); return {ds:score-s0, housed:!!ghosts[0].inHouse}; }""")
    check("frightened ghost eaten: +>=200 and rehoused", bool(r8) and r8['ds']>=200 and r8['housed'], str(r8))

    # 9. death: -1 life
    r9 = pg.evaluate("""() => { powerMode=false; lives=3; gameState='playing';
      ghosts[1].inHouse=false; ghosts[1].x=pacman.x; ghosts[1].y=pacman.y; ghosts[1].prev={x:pacman.x,y:pacman.y};
      const l0=lives; checkGhostCollisions(); return {dl:lives-l0}; }""")
    check("normal-mode collision: lives -1", bool(r9) and r9['dl']==-1, str(r9))

    # 10. swap-through collision
    r10 = pg.evaluate("""() => { powerMode=false; lives=3; gameState='playing';
      const g=ghosts[2]; g.inHouse=false;
      g.prev={x:pacman.x,y:pacman.y}; pacman.prev={x:g.prev.x+1,y:pacman.y};
      g.x=pacman.prev.x; g.y=pacman.y; pacman.x=g.prev.x; pacman.y=pacman.y;
      const l0=lives; checkGhostCollisions(); return {dl:lives-l0}; }""")
    check("swap-through collision detected", bool(r10) and r10['dl']==-1, str(r10))

    # 13. zero page errors through everything above
    # ---- checks 18-21: added 2026-08-02 from Zach's HAND-TESTING of a 17/17
    # build. Every one is a defect the first 17 checks passed: a respawned ghost
    # that stayed edible after power expired, a mouthless pacman disc, ghosts
    # drawn as plain blobs, and the maze bottom cropped on a phone. The gate
    # only learns what human play keeps teaching it.

    # 18. post-expiry collision, ALL ghost states (incl eaten-and-respawned)
    fresh_start()
    r18 = pg.evaluate("""() => new Promise(res => {
      for (let y=0;y<maze.length;y++) for (let x=0;x<maze[0].length;x++)
        if (maze[y][x]===3) { pacman.prev={x,y}; pacman.x=x; pacman.y=y; y=1e9; break; }
      const g0=ghosts[0];
      g0.inHouse=false; g0.eaten=false; g0.frightened=true;
      g0.x=pacman.x; g0.y=pacman.y; g0.prev={x:pacman.x,y:pacman.y};
      powerMode=true; checkGhostCollisions();          // eat one during power
      setTimeout(() => {
        const out={eatWorked: score>=200, results:[]};
        for (let i=0;i<4;i++) {
          // re-read LIVE objects each round: a death may have rebuilt the
          // ghosts array and pacman (that is correct game behaviour, and
          // iterating a stale snapshot was a bug in this check's first draft).
          gameState="playing"; lives=3;
          const g=ghosts[i]; if (!g) continue;
          g.inHouse=false; g.eaten=false; g.frightened=false;
          g.x=pacman.x; g.y=pacman.y; g.prev={x:pacman.x,y:pacman.y};
          const s0=score, l0=lives;
          checkGhostCollisions();
          out.results.push({ds:score-s0, dl:lives-l0});
        }
        res(out);
      }, 11000);                                        // well past any 7s power window
    })""")
    bad18 = [r for r in (r18 or {}).get('results',[]) if r['ds'] >= 200 or r['dl'] >= 0]
    check("after power expiry NO ghost is edible (incl respawned)", bool(r18) and not bad18,
          f"{r18}")

    # 19. pacman has a MOUTH (stationary sprite vs its own bounding disc).
    # v1 measured pixel variance while moving — motion itself varies the count,
    # so a mouthless disc passed. v2: freeze pacman, compare filled-pixel count
    # to the area of the disc implied by the sprite's own bounding box. A wedge
    # removes >=10% of the disc; anti-aliasing costs <5%.
    fresh_start()
    pg.wait_for_timeout(400)   # no input: pacman stationary
    r19 = pg.evaluate("""() => {
      const cv=document.querySelector('canvas');
      const C=maze[0].length, R=maze.length;
      const cw=cv.width/C, ch=cv.height/R;
      const ctx=cv.getContext('2d');
      const d=ctx.getImageData(Math.max(0,(pacman.x-0.6)*cw), Math.max(0,(pacman.y-0.6)*ch),
                               Math.ceil(cw*2.2), Math.ceil(ch*2.2));
      const px=d.data, W=d.width, H=d.height;
      const tally={};
      for (let y=0;y<H;y++) for (let x=0;x<W;x++) {
        const i=(y*W+x)*4;
        if (px[i]+px[i+1]+px[i+2] < 120) continue;
        const k=(px[i]>>5)+"-"+(px[i+1]>>5)+"-"+(px[i+2]>>5);
        (tally[k]=tally[k]||[]).push([x,y]);
      }
      let best=null, n=0;
      for (const k in tally) if (tally[k].length>n) { n=tally[k].length; best=tally[k]; }
      if (!best || n<25) return {n, ratio:1, note:"sprite not found"};
      let x0=1e9,x1=-1,y0=1e9,y1=-1;
      for (const [x,y] of best) { x0=Math.min(x0,x); x1=Math.max(x1,x); y0=Math.min(y0,y); y1=Math.max(y1,y); }
      const r=Math.max(x1-x0, y1-y0)/2 + 0.5;
      const disc=Math.PI*r*r;
      return {n, ratio: n/disc};
    }""")
    check("pacman has a mouth (sprite is a wedge, not a full disc)",
          bool(r19) and r19.get('ratio',1) < 0.90,
          f"filled/disc ratio {r19.get('ratio',0):.2f} (full disc ~0.95+, wedge <0.90)")

    # 20. ghosts are drawn as GHOSTS (eyes or scalloped skirt), not plain blobs
    r20 = pg.evaluate("""() => {
      const cv=document.querySelector('canvas');
      const C=maze[0].length, R=maze.length;
      const cw=cv.width/C, ch=cv.height/R;
      const ctx=cv.getContext('2d');
      let ghostly=0, seen=0;
      for (const g of ghosts) {
        if (g.inHouse) continue;
        seen++;
        const d=ctx.getImageData(Math.max(0,(g.x-0.5)*cw), Math.max(0,(g.y-0.5)*ch),
                                 Math.ceil(cw*2), Math.ceil(ch*2));
        const px=d.data, W=d.width, H=d.height;
        let white=0; const bottoms={};
        for (let y=0;y<H;y++) for (let x=0;x<W;x++) {
          const i=(y*W+x)*4;
          const r=px[i],gg=px[i+1],b=px[i+2];
          if (r>200&&gg>200&&b>200) white++;
          if (r+gg+b>150 && !(r>200&&gg>200&&b>200)) bottoms[x]=y;   // colored body lowest y
        }
        const ys=Object.values(bottoms);
        const skirt = ys.length>4 && (Math.max(...ys)-Math.min(...ys)) >= 3;
        if (white>=6) ghostly++;   // eyes MANDATORY: rounded-square blobs faked the skirt test (v1)
      }
      return {ghostly, seen};
    }""")
    check("ghosts look like ghosts (visible eyes on most)", bool(r20) and r20['seen']>0 and r20['ghostly'] >= max(1, r20['seen']-1),
          f"{r20}")

    # 21. phone fit: full maze + HUD visible in a 390x844 viewport, no crop
    pg.set_viewport_size({"width":390, "height":660})   # telegram in-app browser reality, not a bare phone
    pg.wait_for_timeout(500)
    r21 = pg.evaluate("""() => {
      const cv=document.querySelector('canvas');
      const r=cv.getBoundingClientRect();
      const hud=[...document.querySelectorAll('body *')].filter(e =>
        /score|lives/i.test(e.textContent||'') && e.children.length===0)
        .map(e=>e.getBoundingClientRect());
      const hudOK = hud.length===0 ? true : hud.every(h => h.bottom <= innerHeight+2 && h.top >= -2);
      return {cvTop:r.top, cvBottom:r.bottom, ih:innerHeight, cvOK: r.bottom <= innerHeight+2 && r.top >= -2, hudOK};
    }""")
    check("in-app browser viewport (390x660): maze + HUD fully visible, no crop",
          bool(r21) and r21['cvOK'] and r21['hudOK'],
          f"canvas {r21['cvTop']:.0f}..{r21['cvBottom']:.0f} vs viewport {r21['ih']}" if r21 else "no data")

    # 22. SPEC: "Timer visibly runs out (blink last 2s)". Zach ate a
    # normal-LOOKING ghost: without the blink, the last edible seconds are
    # indistinguishable from normal. Sample a frightened ghost's dominant color
    # late in power mode — it must alternate.
    fresh_start()
    pg.evaluate("""() => {
      for (let y=0;y<maze.length;y++) for (let x=0;x<maze[0].length;x++)
        if (maze[y][x]===3) { pacman.prev={x,y}; pacman.x=x; pacman.y=y; y=1e9; break; }
      const g=ghosts[0];
      g.inHouse=false; g.eaten=false;
      g.x=Math.max(1,pacman.x-3); g.y=pacman.y; g.prev={x:g.x,y:g.y};
    }""")
    pg.keyboard.press("ArrowLeft"); pg.wait_for_timeout(300)
    pg.wait_for_timeout(4700)     # into the last ~2s of a 7s window
    cols=[]
    for _ in range(10):
        c = pg.evaluate("""() => {
          const g=ghosts[0]; if (!g || g.inHouse || g.eaten) return null;
          const cv=document.querySelector('canvas');
          const C=maze[0].length, R=maze.length;
          const cw=cv.width/C, ch=cv.height/R;
          const d=cv.getContext('2d').getImageData(Math.max(0,(g.x-0.5)*cw), Math.max(0,(g.y-0.5)*ch),
                                                   Math.ceil(cw*1.6), Math.ceil(ch*1.6)).data;
          const t={};
          for (let i=0;i<d.length;i+=4) {
            if (d[i]+d[i+1]+d[i+2] < 120) continue;
            const k=(d[i]>>5)+"-"+(d[i+1]>>5)+"-"+(d[i+2]>>5);
            t[k]=(t[k]||0)+1;
          }
          let bk=null,bn=0; for (const k in t) if (t[k]>bn){bn=t[k];bk=k;}
          return bk;
        }""")
        if c: cols.append(c)
        pg.wait_for_timeout(150)
    blink_ok = len(set(cols)) >= 2 and len(cols) >= 5
    check("power-mode blink warning in the last 2s (spec line)", blink_ok,
          f"dominant colors sampled: {sorted(set(cols))}")

    check("zero JS page errors end-to-end", len(errors)==0, "; ".join(errors[:3]))
    b.close()

n_pass = sum(results)
print(f"SUMMARY: {n_pass}/{len(results)} " + ("ALL PASS" if all(results) else "FAILED"))
sys.exit(0 if all(results) else 1)
