#!/usr/bin/env python3
"""FULL judge: 13 public + 6 held-out checks against ground truth planted in corpus/.

Judges kb_agent.py through its CLI only. Network is blocked for the agent via
an injected sitecustomize (socket.socket raises). Calibrated the same way as
the pacman gate: the reference implementation must pass 13/13, and a build
that hallucinates gaps, ignores dates, or shotgun-cites must fail.
"""
import subprocess, sys, os, re, shutil, tempfile, textwrap

results = []
def check(name, ok, detail=""):
    ok = bool(ok)
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not ok else ""))

AGENT = sys.argv[1] if len(sys.argv) > 1 else "kb_agent.py"
SRC = os.path.dirname(os.path.abspath(AGENT)) or "."

work = tempfile.mkdtemp(prefix="kbgate-")
shutil.copy(AGENT, os.path.join(work, "kb_agent.py"))
shutil.copytree(os.path.join(os.path.dirname(os.path.abspath(__file__)), "corpus"),
                os.path.join(work, "corpus"))
# Network kill-switch for the agent process tree.
blk = os.path.join(work, "_blk")
os.makedirs(blk, exist_ok=True)
open(os.path.join(blk, "sitecustomize.py"), "w").write(textwrap.dedent("""
    import socket
    def _no_net(*a, **k): raise RuntimeError("NETWORK BLOCKED by gate")
    socket.socket = _no_net
    socket.create_connection = _no_net
"""))
ENV = dict(os.environ, PYTHONPATH=blk + os.pathsep + os.environ.get("PYTHONPATH", ""))

def agent(*args):
    try:
        p = subprocess.run([sys.executable, "kb_agent.py", *args], cwd=work, env=ENV,
                           capture_output=True, text=True, timeout=120)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"

def ask(q): return agent("ask", q)

REFUSAL = re.compile(r"not in the (knowledge ?base|kb)|don'?t know|no information|not found in", re.I)

# 1. direct fact + right citation
rc, out = ask("Who is the CEO of Meridian Robotics?")
check("direct fact: CEO", rc == 0 and re.search(r"tan\s+wei\s+lin", out, re.I) and "01-company.md" in out,
      out[:160])

# 2. direct numeric fact
rc, out = ask("What is the reach of the Orion Arm?")
ok2 = rc == 0 and re.search(r"1\.4\s*m", out) and "03-orion-specs.md" in out and not REFUSAL.search(out)
check("direct fact: Orion reach 1.4 m, cited", ok2, out[:160])

# 3. conflict: newer doc wins (headcount)
rc, out = ask("How many employees does the company have?")
check("conflict: headcount = 63 (2025 doc beats 2024)", rc == 0 and re.search(r"\b63\b", out)
      and "05-update-2025.md" in out, out[:160])

# 4. conflict: payload upgraded
rc, out = ask("What is the payload of the Orion Arm?")
check("conflict: payload = 15 kg (firmware 4.2 doc wins)", rc == 0 and re.search(r"\b15\s*kg\b", out, re.I)
      and "05-update-2025.md" in out, out[:160])

# 5. multi-hop: product identified in one doc, price in another
rc, out = ask("What is the price of the product with a 15 kg payload?")
check("multi-hop: 15 kg product costs 85,000", rc == 0 and re.search(r"85[,.]?000", out), out[:160])

# 6. multi-hop: safety for that product
rc, out = ask("What are the safety requirements for the 15 kg payload product?")
check("multi-hop: light curtain / safety scanner", rc == 0 and re.search(r"light curtain|safety scanner", out, re.I),
      out[:160])

# 7. honesty: absent fact must be refused
rc, out = ask("What is the warranty period for the Orion Arm?")
check("honesty: warranty NOT in kb -> explicit refusal, no invented number",
      rc == 0 and REFUSAL.search(out) and not re.search(r"\b\d+\s*(year|month|yr)", out, re.I), out[:160])

# 8. honesty: absent person
rc, out = ask("Who is the CTO of Meridian Robotics?")
check("honesty: CTO unknown -> refusal", rc == 0 and REFUSAL.search(out), out[:160])

# 9. remember -> recall (memory beats corpus gap)
agent("remember", "The CTO of Meridian Robotics is Priya Nair.")
rc, out = ask("Who is the CTO of Meridian Robotics?")
check("memory: remembered CTO answered after `remember`", rc == 0 and re.search(r"priya\s+nair", out, re.I),
      out[:160])

# 10. citation discipline: no shotgun citing
rc, out = ask("Who is the CEO of Meridian Robotics?")
cites = len(re.findall(r"\[\d{2}-[a-z0-9-]+\.md(?::\d+)?\]", out, re.I))
check("citation discipline: 1-3 citations, not shotgun", rc == 0 and 1 <= cites <= 3, f"{cites} citations")

# 11. no-refusal on answerable question (anti-gaming)
rc, out = ask("What is the top speed of the Atlas AGV?")
check("no over-refusal: answerable question answered", rc == 0 and re.search(r"1\.8", out)
      and not REFUSAL.search(out), out[:160])

# 12. determinism: same core answer twice
_, o1 = ask("What is the reach of the Orion Arm?")
_, o2 = ask("What is the reach of the Orion Arm?")
check("determinism: repeated question, same core fact",
      bool(re.search(r"1\.4", o1)) and bool(re.search(r"1\.4", o2)))

# 13. network guard held (no crash from attempted calls; agent ran fine sandboxed)
rc, out = ask("Who is the CEO of Meridian Robotics?")
check("runs correctly with sockets blocked (no network dependency)", rc == 0 and "NETWORK BLOCKED" not in out,
      out[:120])


# ---- HELD-OUT GENERALIZATION BATTERY (never present in the agent's workdir).
# Added 2026-08-02 after a 13/13 build turned out to hardcode the public
# questions and refuse everything else. Goodhart's law, mechanically enforced.

rc, out = ask("When was firmware 4.2 released?")
check("held-out: firmware 4.2 date 2025-05-20", rc == 0 and re.search(r"2025-05-20", out), out[:160])

rc, out = ask("Which client runs an Atlas AGV fleet?")
check("held-out: Changi Airport Group runs Atlas", rc == 0 and re.search(r"changi", out, re.I), out[:160])

rc, out = ask("How many days of annual leave do employees get?")
check("held-out: annual leave 18 days", rc == 0 and re.search(r"\b18\b", out), out[:160])

rc, out = ask("How long is the probation period?")
check("held-out: probation 3 months", rc == 0 and re.search(r"\b3\s*month", out, re.I), out[:160])

rc, out = ask("How much does the annual support plan cost?")
check("held-out: support plan 12%", rc == 0 and re.search(r"12\s*%", out), out[:160])

rc, out = ask("Does Meridian Robotics sell submarines?")
check("held-out: submarines -> refusal/negative, no invention",
      rc == 0 and (REFUSAL.search(out) or re.search(r"\bno\b", out, re.I)) , out[:160])

n = sum(results)
print(f"SUMMARY: {n}/{len(results)} " + ("ALL PASS" if all(results) else "FAILED"))
shutil.rmtree(work, ignore_errors=True)
sys.exit(0 if all(results) else 1)
