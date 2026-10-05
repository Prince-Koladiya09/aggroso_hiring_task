# Gap Report: first delivery vs. SRS v1.0, and what v1.1 changes

Reviewed repo: `Prince-Koladiya09/aggroso_hiring_task` (main). Method: read every backend module, ran the test suite, built the frontend, then fixed and re-verified against a live server.

## Headline

The first delivery had **all the right modules** (≈9,000 lines: gateway, executor, approvals, redaction, audit chain, agent, React UI), so the *structure* was largely complete. But the **critical paths did not work** and several documented guarantees were not actually enforced. In my judgement roughly half of the SRS was working in substance; the safety-critical half (executor, approvals, gateway, redaction, agent validation) was the part that was missing or broken.

| Check | Before | After |
| --- | --- | --- |
| Backend starts | **No**: `NameError: Tuple` in `orchestrator.py` | Yes |
| Automated tests | 13 failing, 1 test file not collectable, tests ran as an implicit analyst | **139 passing** (deterministic, isolated DB) |
| Frontend | Built, but `alert()/prompt()`, auto-login as analyst, 1,119-line monolith | Login page, toasts, confirm dialogs, 9 tab components; `tsc` clean, build OK |
| S1-S10 live walkthrough | Not runnable | All ten verified over real HTTP (`scripts/scenario_walkthrough.py`) |
| 4 simultaneous execute calls | Not testable | 1×200, 3×409, 14 actions / 14 attempts / 14 keys, no duplicate write |

## Defects found and fixed (by severity)

### Safety-critical (a documented guarantee was false)
| # | Finding | Fix |
| --- | --- | --- |
| 1 | **Every write was denied**: the Gateway required role `executor` but received the human role. | Role is the human's; the *caller* (`EXECUTOR`) is checked separately. |
| 2 | **Gateway never checked approval for write tools** (SRS 9.2 step 5). | Writes need an APPROVED action in the active set, a valid approval (scope, hash, inventory version, TTL, four-eyes), identical arguments, subject ownership, and a policy re-check. |
| 3 | **Reconciliation/pre-image reads were always blocked** (`get_record` allowed only in PLANNING/PLAN_REVIEW) and the error was swallowed, so pre-images were never stored and retry-reconcile never ran. | `get_record` allowed for the Executor in `EXECUTING`/`PARTIALLY_FAILED`; denial now fails the action visibly. |
| 4 | **Retry never advanced request state** (`PARTIALLY_FAILED` forever); a second Execute click after completion raised an illegal transition (500). | Explicit state handling for retry and for post-completion duplicates. |
| 5 | **Blocked/excluded actions could be executed** (executor ran every action of a kind). | Only live actions of the active plan in scope; BLOCKED/REJECTED/SUPERSEDED are excluded from hashes and execution. |
| 6 | **Anonymous requests were treated as the Analyst** (`get_current_user` fell back to `alex.analyst`); CORS `*`. | 401 without a token; CORS locked to configured origins. |
| 7 | **Approvals had no state guard**: any scope could be recorded in any state; plan approval hash and validation used different action sets. | Scope-specific state checks, one shared `approval_actions()` for grant and validation, expiry (72 h), inventory-version binding. |
| 8 | **Four-eyes was trivially true** (only `created_by`, which is always an Analyst). | Approver must differ from creator **and** the user who ran the agent; re-checked at execution. |
| 9 | **Agent output was trusted**: the plan validator checked nothing about action kind, target existence, inventory decision, or requested values. The mock LLM hard-coded `prf_target` and a phone number. | Deterministic validation of every proposal; discards are audited; completeness check; mock LLM is payload-driven, no hard-coded values. |
| 10 | **Export had no state/approval guard** and used a hard-coded list (`Marcus Vance`, `Laura Vance`) as the third-party names. | Export only in `EXPORT_REVIEW` with a valid plan approval; names derived from other profiles, support agents, staff and mention-ticket authors, plus cue-based detection. |
| 11 | **Audit hash chain broke after a DB round-trip** (naive vs aware timestamps) and was not append-only. | Normalised timestamps; ORM guards **and** SQLite triggers; tamper tests. |

### Functional gaps against the SRS
| FR | Gap | Status now |
| --- | --- | --- |
| FR-102 | Type mismatch not surfaced | Flagged in plan + banner (no silent reclassification) |
| FR-105 | Extension was a direct Approver action, no request step, no approval record | Request → Approver decision, `EXTENSION` approval row, one-time only |
| FR-205 | No missing-info detection from the agent | `/agent/interpret` + deterministic checker (code wins) with rule IDs |
| FR-302 | No source-selection stage | Stage 2 with code allowlist and per-type minimums |
| FR-307/309 | No outage toggle; retries without backoff; run log lacked usage | `SIMULATE_LLM_OUTAGE`, backoff, tokens/latency/input hash logged per attempt |
| FR-308 | Prompt files unused; plan prompt had no inventory; no minimisation | Prompts loaded from `prompts/v1`; masked, whitelisted, escaped records only |
| FR-403 | Mention tickets were always REDACT, even for deletions | REDACT for access; excluded for correction/deletion |
| FR-503 | Inventory never versioned; re-plan deleted rows (FK violation once actions exist) | Versioned; re-plan supersedes; any change voids approvals |
| FR-504 | CSV/JSON inventory export | Added |
| FR-603 | No redaction diff | Per-field original vs exported with rule IDs |
| FR-605 | Leak scan used the same lists as the redactor | Independent scan; restricted keys, found identifiers, SSN/e-mail/phone/cue names |
| FR-604 | Release without approval record; any role could download | `EXPORT` approval row; stale/leak checks; Analyst/Approver download only after release |
| FR-707 | Pre-image stored in clear | Fernet-sealed; unsealed only for Approver/Auditor |
| FR-805 | Fault injection only partly reachable | Both modes via UI/API when the flag is on |
| FR-1002 | No addendum path | `POST …/fulfilment-record/addendum` (separate audit event) |
| FR-1003 | AI narrative without human gate | AI draft must be confirmed (or edited) before closing |
| NFR-1 | Default secret, permissive CORS | Production refuses default secret; CORS allowlist |
| NFR-5 | `event=` kwarg collided with structlog; no correlation header | Fixed; `X-Correlation-ID` on every response |
| §12 | Standard error body not used | `{"error":{code,message,rule_ids,correlation_id,fields}}` everywhere |
| §13 | Alerts, no login, no staged progress, no confirm dialogs | Rebuilt (see below) |
| S8 | Unreachable (email always supplied, lookup by email) | Name-only lookup returns candidates → `ambiguous_match` |

### Documentation honesty
The first README and `AGENT_USAGE.md` described controls (e.g. "discard any proposed action not in the inventory", `test_api_integration` end-to-end) that the code did not implement. They now describe only what is implemented and tested.

## New or changed behaviour you should know about

1. `PLAN_APPROVED`/`EXPORT_REVIEW` → `PLAN_REVIEW` is now a legal transition (needed so an inventory change can void an access-request approval, FR-503). `PLANNING_FAILED` can only go to `PLANNING`.
2. Added policy rule `POL-COR-1` (editable subject fields only) and an `approvals`/`llm` section in the YAML; the engine reads retention parameters from the policy.
3. Request creation accepts an optional received date and an authorization-on-file flag; new endpoints: `/agent/interpret`, `PATCH /info`, `/reject`, `/cancel`, `/fulfilment-record/draft`, `/fulfilment-record/addendum`, `/inventory/export`, `/system/flags`, `/system/toggle-llm-outage`.
4. `BCRYPT_ROUNDS`, `CORS_ORIGINS`, `SIMULATE_LLM_OUTAGE`, `PROMPTS_DIR` config added.

## Not done / known limits (be aware)

- **Real LLM not run live.** The Anthropic client exists and its output goes through the same schema + validation path, but no API key was available; only the deterministic mock was exercised.
- **UI not driven in a browser.** It type-checks and builds, and every API it calls is covered by tests or the live walkthrough, but I did not click through it.
- **Docker image not built** in this environment (no Docker). The Dockerfile change is small (random `SECRET_KEY` fallback) but unverified.
- FR-707's "short retention" has no purge job; re-plan drops reviewer overrides; SQLite is single-writer (concurrency was proven for the executor, not load-tested).
