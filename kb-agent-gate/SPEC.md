# SPEC — KB Agent (single file, stdlib only, no network)

Build `kb_agent.py`: a knowledge-base agent over the markdown corpus in
`./corpus/`. Python 3 standard library ONLY. Any network use is an automatic
fail (the gate blocks sockets and treats attempts as errors).

## CLI contract (the gate calls exactly these)

```
python3 kb_agent.py ask "question text"
python3 kb_agent.py remember "a fact to store"
```

`ask` prints an answer to stdout and exits 0.
`remember` persists the fact to `notes.md` in the working directory and exits 0.

## Behaviour requirements

1. **Grounded answers with citations.** Every factual answer cites its source
   like `[03-orion-specs.md]` (line numbers optional: `[03-orion-specs.md:4]`).
   Cite only sources actually used — at most 3 citations per answer.
2. **Conflict resolution by recency.** Docs carry `Last updated:` dates. When
   two docs disagree, the newer doc wins (e.g. headcount, payload).
3. **Multi-hop.** Some questions need facts combined from two docs (e.g. "what
   does the 15 kg-payload product cost?" — identify Orion from one doc, price
   from another). Answer with both citations.
4. **Honesty about gaps.** If the corpus does not contain the answer, say so
   explicitly (a phrase like "not in the knowledge base" / "I don't know").
   NEVER invent a value. Refusing an answerable question is also a failure.
5. **Memory.** Facts stored via `remember` are used by later `ask` calls and
   take precedence over corpus gaps (e.g. remember the CTO's name, then answer
   who the CTO is).
6. **Determinism.** The same question twice gives the same core answer.

## Notes

- Keyword/substring/BM25-style retrieval is fine. No LLM calls — the program
  IS the intelligence being graded.
- Keep the whole thing in `kb_agent.py`. The gate copies a fresh corpus for
  each run; `notes.md` starts absent.
