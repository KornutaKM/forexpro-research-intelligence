# FRI v2.3 — local Research Control Center

The Control Center is a **read-only, loopback-only, offline** interface. It exposes selected metadata already in the FRI local queue and Research Memory. It does **not** execute FRI jobs, mutate scientific state, upload research, or access ForexPro Core.

## Start and connect

Install with Python 3.12+ (including package assets), then:

```bash
python -m pip install -e .
python -m forexpro_ri.cli control serve \
  --queue local_data/jobs.sqlite --db local_data/research.sqlite --port 8765
```

Open `http://127.0.0.1:8765/`. The CLI prints an **ephemeral session token**, which the UI requests via `Connect session`. The token is held only in tab memory, is not placed into a URL, and is lost on refresh. Keep it private. Close the process with Ctrl+C to end the session. For synthetic fixture-only histories, opt in with `--allow-unsigned-synthetic`. Omit this flag for signed-only program evaluation.

The interface does not create a queue or memory database if either is absent. CLI imports and job execution remain separate, explicit operator actions. **Do not expose the listener through SSH remote forwarding, reverse proxies, containers with published ports, public tunnels, or untrusted hosts.** Localhost does not grant multi-user security: other processes under the same machine account can potentially access local files or observe terminals. Run under a dedicated OS account and secure local storage.

## Views

1. **Overview:** validated, whitelisted metadata and job counts with warnings for missing databases, failed jobs, and retry backlog.
2. **Job queue:** states, attempt counts and error-code summaries. Result paths, source bundle locations, request payloads and tokens are never served.
3. **Research Memory / Dossier:** minimal closed-experiment identities, recorded verdict counts, procedure outcomes, historical signature status, and evidence gaps. No free-text observations, protected holdout bytes, or execution authority.
4. **Research Program:** review topics built from verified stored entries. Signed-only by default; explicitly synthetic unsigned history is for fixture testing only.
5. **Integrity audit:** operator-triggered local checks of queue event chain and Research Memory. Checksums and historical receipts are **not** proof of scientific approval, current key validity, or authorization.

## HTTP and security boundaries

- Bind is *hardcoded* to IPv4 `127.0.0.1`, not configurable to `0.0.0.0`.
- A fresh cryptographically random 256-bit session token is generated for each server invocation. Every `/api/*` endpoint requires the `Authorization: Bearer` header, compared in constant time. Static HTML/CSS/JS is safe to view without a token.
- Rejects unexpected Host headers to mitigate localhost DNS-rebinding attacks. Never issues CORS approvals or cross-origin cookies; JavaScript uses no external scripts, frameworks, resources, analytics or storage.
- Content Security Policy, `nosniff`, `DENY` framing, `no-referrer`, and `no-store` on every response. The UI constructs all research labels with `textContent`, never dynamic `innerHTML`.
- HTTP is **GET-only**. Unknown endpoints and query parameters are rejected. Dossier experiment IDs use strict validation and bound SQL parameters in the underlying evidence engine. All displayed fields use allowlists, with small UI result limits and generic API errors that never echo private paths or SQLite diagnostics.
- No terminal logs of bearer tokens or request URLs. No network listeners besides the explicitly started control server. No external network connections or LLM provider dependencies.
- The Control Center is *not* a production multi-user security gateway. No TLS, reverse proxy, role management, authentication renewal, rate limiting or cross-host access is provided. Do not deploy as a public internet service.

## Conformance and operational testing

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m unittest discover -s tests -p test_control_center.py -v
```

Tests use ephemeral localhost ports and synthetic fixtures, and check data minimization, bearer authentication, Host rejection, absent-database behavior, signed-only gating, mutations blocked, CSP, and end-to-end queue/dossier/audit views. They never touch ForexPro Core. The existing GitHub CI discovers these tests automatically.

**Remaining for later releases:** private multi-user role controls (if ever needed), signed trust-store rotation policy, explicit alert scheduling and authorized private ForexPro exporter integration.
