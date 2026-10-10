# FRI v2.4 — Evidence-constrained Research Advisor

FRI v2.4 adds a **deterministic, proof-linked advisory pack** and **optional local-only language model phrasing**. This is an operator review tool for design of **new preregistered research**, not a strategy recommender, statistical significance test, scientific approval tool, or trading agent.

## Default mode: no LLM, no network

```bash
mkdir -p local_data
python -m forexpro_ri.cli memory ingest examples/closed_synthetic --db local_data/demo.sqlite --unsigned-synthetic
python -m forexpro_ri.cli memory ingest examples/closed_synthetic_peer --db local_data/demo.sqlite --unsigned-synthetic
python -m forexpro_ri.cli advisor --db local_data/demo.sqlite --unsigned-synthetic \
  --expected-procedure MONTE_CARLO --format markdown
```

The default is **signed-only**. `--unsigned-synthetic` is a test-only switch; never use it with actual ForexPro exports. The advisor calls the existing Research Program engine, which audits Research Memory and historical signature receipts within a consistent SQLite snapshot. It creates stable `item_id`s, links each question to exact experiment IDs, entry digests, receipt digests, the source Research Program digest and memory snapshot digest. A sample of up to eight evidence links per topic is included; evidence counts cover all cases, and the full source program digest binds the complete evidence selection.

Topics are selected by fixed, documented review ordering: evidence gaps first, then repeated not-evaluable procedures, then repeated recorded failures. Ordering is a **navigation aid**, not a risk/profit score, causal inference or scientific conclusion. Reports contain no raw observations or strategy text.

## Optional LLM prose: localhost Ollama, explicit consent

1. Separately install and run an **operator-controlled local** Ollama server listening on **`127.0.0.1:11434`** (this project does not install it or start it).
2. Download and manage a compatible model separately; model availability, license and security are the operator's responsibility.
3. Run only if you explicitly want a local model to see **bounded, sanitized** research metadata:

```bash
python -m forexpro_ri.cli advisor --db local_data/demo.sqlite \
  --unsigned-synthetic --expected-procedure MONTE_CARLO \
  --local-model qwen2.5:7b --format markdown
```

The adapter connects **only** to `http://127.0.0.1:11434/api/generate`. It does not accept alternative URLs, does not use proxies or follow redirects, makes no cloud API calls, requests JSON, imposes size and timeout bounds and rejects unsupported model responses. The request contains only fixed procedure codes, counts, predefined prospective questions, item IDs and a small sample of entry hashes. **No raw source observation, report free text, private filesystem paths, token, trust store or ForexPro protected data is sent.**

Model output is not proof. FRI validates the supplied `item_id` references, types and lengths and labels model content `LOCAL_MODEL_UNVERIFIED_PROSE`. It cannot modify existing evidence, scientific status, citations or the original deterministic proposal set. Arbitrary model text is HTML-escaped in Markdown. **Semantic truthfulness and absence of misleading phrasing cannot be guaranteed by schema validation.** A human must review every suggestion. If the local service is unavailable, invalid, or responds excessively, the operation fails closed instead of fabricating a successful inference.

**Privacy caveat:** a localhost model is still separate software and may retain/log requests. A local server shared with other users can see the sanitized prompt. FRI cannot enforce other programs' retention policies; disable logging or choose no-model mode for sensitive environments. Running under multiuser/shared OS accounts is not a strong isolation boundary.

## Read-only Research Control Center

A token-protected `GET /api/advisor` view exposes only fixed deterministic proposals and never invokes the LLM. Use the web UI to review evidence-linked questions; invoke the local model **only from CLI** with explicit `--local-model` opt-in. The HTTP service cannot dispatch jobs or access protected sources.

## Threat model / limitations

- Historical signature validation ≠ current key authorization ≠ permission to export from ForexPro ≠ scientific approval.
- Hashes bind records but are not privileged-database tamper-proof seals or causal evidence.
- No holdout/broker access, no trading actions, no running experiments, no automatic strategy editing.
- Similarities, repeated failures and missing evidence are descriptive within operator-selected records only.
- The FRI project remains publicly visible; actual bundles, runtime SQLite databases and generated reports must stay private.
- No autonomous AI loop, background scheduling, internet APIs or automatic application of model suggestions.

## Tests

`PYTHONPATH=src python -m unittest discover -s tests -v`

Includes signed-only gate, tamper detection, deterministic hashes, CLI creation-only output, strict model response referencing, HTML escaping, bounded model transports, HTTP authentication, no-model HTTP rule and mutation rejection. Public CI uses synthetic fixtures and never calls a live model.
