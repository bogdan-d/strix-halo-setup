#!/usr/bin/env python3
"""Reference KB agent — the calibration standard for gate_kb.py.

Plain-stdlib retrieval with the four behaviours the spec demands: recency wins
conflicts, two-hop entity bridging, explicit refusal on gaps, and a notes file
that outranks the corpus. If the gate ever fails this file, the gate is wrong.
"""
import sys, os, re, glob

STOP = set("the a an of is are was were be been has have had will what which who how many does do can it for to in on with and or its their this that now".split())

def tokens(s):
    return [w for w in re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", s.lower()) if w not in STOP]

def load_docs():
    docs = []
    for path in sorted(glob.glob(os.path.join("corpus", "*.md"))):
        text = open(path, encoding="utf-8").read()
        m = re.search(r"Last updated:\s*([0-9-]+)", text)
        docs.append({"name": os.path.basename(path), "date": (m.group(1) if m else "0000"),
                     "lines": text.splitlines()})
    if os.path.exists("notes.md"):
        docs.append({"name": "notes.md", "date": "9999-12-31",
                     "lines": open("notes.md", encoding="utf-8").read().splitlines()})
    return docs

def line_df(docs):
    """How many lines contain each token — the rarity signal."""
    df = {}
    for d in docs:
        for line in d["lines"]:
            for w in set(tokens(line)):
                df[w] = df.get(w, 0) + 1
    return df

def score_lines(docs, words, df):
    """Rarity-weighted overlap: a line mentioning 'ceo' (df 1) outranks a title
    that merely repeats the company name (df 5+). Recency breaks ties."""
    hits = []
    want = set(words)
    for d in docs:
        for i, line in enumerate(d["lines"]):
            if line.lstrip().startswith("#"):
                continue                      # titles are structure, not facts
            lw = set(tokens(line))
            if not lw:
                continue
            ov = lw & want
            if not ov:
                continue
            score = sum(1.0 / df.get(w, 1) for w in ov)
            hits.append({"doc": d, "line": line.strip(), "n": i + 1,
                         "score": score, "date": d["date"]})
    hits.sort(key=lambda h: (round(h["score"], 6), h["date"]), reverse=True)
    return hits

def entities(line):
    """Capitalised multi-word phrases — the bridge for two-hop questions."""
    return re.findall(r"(?:[A-Z][a-z0-9]+\s?){1,3}", line)

def answer(question):
    docs = load_docs()
    df = line_df(docs)
    words = tokens(question)
    # Honesty rule: a salient question word that appears NOWHERE in the kb
    # means the kb cannot answer this — refuse rather than pattern-match the
    # generic words around it.
    missing = [w for w in words if len(w) >= 3 and w.isalpha() and df.get(w, 0) == 0]
    hits = score_lines(docs, words, df)
    top = hits[0]["score"] if hits else 0.0
    # Blended honesty rule: a question word absent from the whole kb suggests
    # the kb cannot answer — but only refuse when the best hit is also weak.
    # "How many days of leave do employees GET" must not refuse over 'get',
    # while "what is the warranty period" (only generic words match) must.
    if (missing and top < 0.9) or top < 0.3:
        print("That is not in the knowledge base.")
        return
    best = hits[0]
    used = [best]
    covered = set(tokens(best["line"]))
    leftover = [w for w in words if w not in covered and len(w) > 2]
    if leftover:  # two-hop: bridge through entities named in the first hit
        for ent in entities(best["line"]):
            second = score_lines(docs, tokens(ent) + leftover, df)
            second = [h for h in second if h["line"] != best["line"]]
            if second and second[0]["score"] >= 0.5:
                used.append(second[0])
                break
    cites = []
    for u in used[:3]:
        c = f"[{u['doc']['name']}:{u['n']}]"
        if c not in cites:
            cites.append(c)
    print(" ".join(u["line"] for u in used) + " " + " ".join(cites))

def remember(fact):
    with open("notes.md", "a", encoding="utf-8") as f:
        f.write(fact.rstrip() + "\n")
    print("Noted.")

if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in ("ask", "remember"):
        print("usage: kb_agent.py ask|remember \"text\""); sys.exit(2)
    (answer if sys.argv[1] == "ask" else remember)(sys.argv[2])
