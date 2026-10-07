# Continere GTM Studio

A local, approval-gated GTM proof of concept for **rehab providers**. Python 3.11+, SQLite, a browser dashboard, and Hermes' normal agent runtime. No Docker, Redis, cloud hosting, JavaScript build step, or separate OpenAI API key is required for the demo.

**Sending is disabled by default. No live emails were sent during development.** The supplied strategy is intentionally incomplete: no Continere positioning, results, credentials, customers or proof points have been invented. The default geography, Texas, USA, is editable and is only a starting value from the referenced conversation.

## Run the dashboard

Open a terminal in this project directory:

```sh
python3 -m gtm.server
```

Open [Continere GTM Studio](http://127.0.0.1:8765). On macOS you can also run `Start.command`.

1. Select **Demo workspace → Load demo campaign**. Six fictional `.example` providers load without network requests or credentials.
2. Open a provider. Review its source excerpts and draft. Mark the demo contact/geography checks and **Save changes & verification**.
3. Check the claim-review box and approve that revision. The demo message cannot be sent, even if sending is later enabled.
4. Edit it again to see approval clear. Paste “No thanks, remove me” into **Record a reply** to see suppression.
5. The **Responses** page shows classifications, and **Settings** shows the audit trail.

Stopping and restarting the app preserves campaign state in `data/campaign.sqlite3`. Press Ctrl+C in its terminal to stop. One server process per data directory is supported. Do not bind or proxy this POC to a public network: it is a single-owner localhost app, not a multi-user service.

## Supply Continere knowledge

Use **Strategy** to fill the JSON form. It saves to `config/strategy.json`. Alternatively copy `config/strategy.example.json` to that path and edit it. The example is a template, not confirmed business knowledge.

Required before a live run:

- An exact rehab segment in `icp.description`; revise `include_terms` and `exclude_terms` accordingly. Physical rehab and substance-use treatment are not interchangeable.
- Your approved `positioning` and `confirmed_by` name.
- At least one `approved_claims` object containing `id`, `text`, and `source`. The text should be a complete, ready-to-use sentence about Continere; the source is your supporting document or approved internal reference.
- A short, approved `cta`.

Optional buyer roles and pain hypotheses remain structured strategy inputs. Hypotheses are shown separately and never asserted as provider facts. Add disallowed wording to `prohibited_claims`. Do not include patient records or patient contact data.

The writer chooses a relevant approved proposition and a retrieved provider quote. The app assembles those verbatim with the CTA and footer. This deliberately limits new factual claims; you can edit the draft, but the approved claim, CTA and opt-out line must remain, and you must verify every final claim. A polished copy style should be developed from actual Continere knowledge after the POC is connected.

Changes to strategy or settings invalidate approvals. A strategy change also requires **Refresh research & draft** on an existing live prospect. Refresh replaces unsent edits and requires verification again. Changing geography clears geography verification; existing providers are not silently moved into the new region.

## Connect live research

### 1. Local configuration

```sh
cp .env.example .env
```

Keep `.env`, Gmail credentials, the database, and `config/strategy.json` private. They are excluded from source control and the supplied clean ZIP. The app loads `.env` at startup; restart after environment changes.

### 2. Google Places

Enable **Places API (New)** in a Google Cloud project with billing. Set `GOOGLE_PLACES_API_KEY` in `.env` and restrict it to the needed API. There can be a separate Google charge; a ChatGPT subscription does not cover Places.

The compatible provider implementation uses the official **Text Search (New)** REST API, not an invented or unconfigured MCP package. It requests explicit fields, follows pagination, limits runs to 25 results, and deduplicates by website domain (or place ID when no website exists). Fewer results are possible. The discovered address and Google Maps link are retained alongside the provider, and the dashboard links back to the listing.

Research fetches only the supplied public homepage with bounded bytes/time, validates all DNS addresses, pins the connection IP, and revalidates every redirect. It extracts source excerpts and any same-domain email actually present. It does not guess emails, run JavaScript, bypass blocked sites, crawl patient pages, or prove deliverability. If an email is absent, the owner can enter a public business email and source after verifying it. Provider storage/attribution terms still apply to live Places-derived fields; this POC has no automated provider-specific data-retention policy. Review those requirements before a retained production campaign.

### 3. Hermes + your ChatGPT/Codex subscription

Use an existing [Hermes installation](https://hermes-agent.nousresearch.com/docs/) or follow its official installation instructions. This project does not install or upgrade Hermes for you. Hermes is a source application, not a dependency to add to `requirements.txt`.

Create a dedicated Hermes profile for the POC, from this project directory:

```sh
mkdir -p data/hermes
HERMES_HOME="$PWD/data/hermes" hermes model
```

Select **ChatGPT or Codex Subscription / openai-codex**, complete the interactive sign-in, and select an available model. Then put that exact model identifier into `HERMES_MODEL` in `.env`. Set `HERMES_SOURCE` to the Hermes checkout and `HERMES_PYTHON` to its working Python interpreter (the example paths match the installation found during development).

The application sets `HERMES_HOME` to this dedicated profile. It does not copy tokens from Codex or read personal ChatGPT conversations. No OpenAI API fallback is configured. Eligibility, model access, rate limits and plan allowances are controlled by the provider/account. Do not interpret “subscription supported” as unlimited or guaranteed access.

Use **Hermes' standard AIAgent runtime with the openai-codex provider**. Do not switch this bridge to the optional Codex app-server runtime: the POC depends on native Hermes `delegate_task`.

An offline interface check, with the correct Hermes Python path:

```sh
~/.hermes/hermes-agent/venv/bin/python scripts/hermes_worker.py --check
```

This checks imports and the expected library signature; it does **not** confirm login, credits, model availability, or successful inference. The installed interface checked during development was Hermes v0.16.0 / upstream `24832009`. Hermes library interfaces may change; rerun the check after upgrades and validate a one-prospect live run before expanding.

The parent agent receives only `delegate_task`. Its four specialist children research supplied evidence, qualify fit, choose draft evidence/claim IDs, and perform QA. Children inherit no usable external tools. The parent must return validated JSON and evidence of at least four delegations; incomplete or fabricated results fail closed. Source text is treated as untrusted. The worker receives no Places key, Gmail credentials or approval token.

### 4. First live campaign

1. Set the geography, exact discovery phrase, sender identity and postal address in **Settings**.
2. Start with a **one-prospect** limit; finish Strategy and connect Places/Hermes.
3. Switch to **Live workspace → Discover prospects**. Review any errors in the prospect or run audit.
4. Check real source excerpts, ICP type, email source and geography; save verification.
5. Refine and approve the exact draft. Nothing is sent by approval alone.

## Connect Gmail only after approval

The Gmail connection script refuses to begin unless a current live draft is approved. The dashboard never starts an OAuth connection by itself.

1. Enable Gmail API in Google Cloud, configure OAuth consent for your own/test account, and create an OAuth client of type **Desktop app**. Download its client JSON to `data/google-client.json`.
2. Install the optional Gmail dependencies in a local virtual environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-gmail.txt
.venv/bin/python scripts/connect_gmail.py
```

3. Sign in to the exact official sender account configured in Settings. The POC requires the primary account address to match; aliases are not implemented. OAuth requests `gmail.send` and `gmail.readonly` for approved sends and reply sync. Tokens are stored locally with mode 0600. Google may require consent/testing setup or reauthorization; do not commit the client or token files.
4. After checking sender authentication (SPF/DKIM/DMARC) and campaign requirements for the chosen geography, mark the readiness confirmation in Settings. This is a human attestation, not an automated DNS or legal validation.
5. To enable **manual sending**, explicitly set `ALLOW_SEND=true` in `.env`, then restart with `.venv/bin/python -m gtm.server`. Reapprove after any setting change.
6. Open an approved live draft and choose **Send this approved email**. Confirm the exact recipient and sender in the final dialog.

The server rechecks the approved revision/hash, suppression list, source freshness, source/claim references, domain cooldown, daily cap, sender identity and readiness. It syncs existing Gmail campaign threads before sending so known replies/opt-outs are applied. A single database reservation prevents duplicate clicks and concurrent sends from producing duplicate requests.

On any ambiguous Gmail failure or process interruption, the record becomes **Check Gmail / send_unknown** and cannot retry. Search Gmail manually for the recipient, subject, and the `continere-<delivery-id>` Message-ID in `deliveries`. Reconcile outside the automatic send path; do not delete delivery records to force a retry. The app makes at most one attempt per prospect and recipient; it cannot guarantee exactly-once delivery across Gmail and SQLite.

### Responses and reputation

**Responses → Sync Gmail replies** fetches only tracked campaign threads. Manual pasted replies are also supported. Conservative deterministic rules classify opt-out, bounce, out-of-office, interested, or needs-review. Common quoted email history is removed first. Confidence labels are rule weights, not calibrated probabilities. Every non-opt-out conclusion needs human review; no replies or follow-ups are sent automatically.

Opt-outs suppress both email and domain across campaigns. A live bounce activates a global send circuit breaker. There is intentionally no one-click unsuppress, retry or circuit-breaker override in this POC. Future production work should add an audited owner-only remediation flow. Gmail bounces outside the original tracked thread, replies in other inboxes, HTML-only replies truncated to a Gmail snippet, and unusual quoting/languages can be missed: inspect the mailbox and manually record any such response. This is not an autonomous mailbox monitor.

## Architecture and extension points

```text
Browser dashboard → localhost HTTP service → SQLite + audit events
                         │
                    Places adapter → bounded website research
                         │
                    Hermes subprocess (dedicated profile)
                         ├─ Research specialist
                         ├─ Qualification specialist
                         ├─ Writer specialist
                         └─ QA specialist
                         │
                    Validated draft → human review → approved revision
                                                        │
                       Explicit Send + policy gate → Gmail adapter
                                                        │
                             Replies → classification → suppression
```

| File / folder | Responsibility |
| --- | --- |
| `gtm/providers.py` | Discovery provider contract; Google Places and offline demo; bounded research fetcher |
| `gtm/agents.py` | Evidence/scoring, Hermes bridge, constrained drafting, response classification |
| `scripts/hermes_worker.py`, `prompts/` | Hermes parent and specialist roles |
| `gtm/guards.py` | Approval fingerprint, claims, duplicate/suppression/reputation checks |
| `gtm/service.py` | Campaign state transitions, configuration, audit, approval, send reservation |
| `gtm/gmail.py` | OAuth token refresh, sender verification, MIME send and thread retrieval |
| `gtm/db.py`, `schemas/` | Persistent schema and structured contracts |
| `static/` | Responsive, dependency-free dashboard |
| `skills/continere-gtm/` | Optional Hermes interactive operating instructions |

Scoring is transparent and deterministic: rehab term evidence 50, retrieved website 20, public same-domain business email 10, human geography confirmation 20; an exclusion subtracts 100. It is an initial fit heuristic, not a prediction of intent or conversion. The Hermes qualifier provides rationale and QA; it cannot inflate this score. Generic default terms must be replaced with the approved rehab definition.

To add a discovery provider, return the same `place_id/name/address/website/source` records as `discover()`. An MCP adapter can translate a real Maps server's schema into this contract. To add an ICP, extend the strategy schema/validator and campaign scope. To add a channel, implement a separate delivery adapter behind the same approval/reservation/suppression boundary. Do not give agents an unrestricted outbound tool or let new channels bypass guards.

The POC persists research, draft revisions (current revision number and audit transitions, not a full body history), approvals, campaign inputs, delivery attempts and replies. Runs are serial, bounded, and not automatically retried. Partial records survive failures; starting another run skips existing domains. Refresh an existing record to retry its research. Rejected records can be edited or refreshed back into review; sent/suppressed/uncertain records cannot.

## Verification

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q gtm scripts
node --check static/app.js   # optional, when Node is installed
```

Tests use temporary databases and mocked providers; they never send mail or consume live model requests. See `VALIDATION.md` for the checks performed and remaining live-integration validation.

## Primary references

- [Hermes subscription providers](https://hermes-agent.nousresearch.com/docs/integrations/providers/)
- [Hermes Python library](https://hermes-agent.nousresearch.com/docs/guides/python-library)
- [Hermes delegation](https://hermes-agent.nousresearch.com/docs/user-guide/features/delegation)
- [OpenAI Sign in with ChatGPT eligibility](https://developers.openai.com/siwc/quickstart)
- [Google Places Text Search (New)](https://developers.google.com/maps/documentation/places/web-service/text-search)
- [Gmail sending guide](https://developers.google.com/workspace/gmail/api/guides/sending)
- [Google desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app)

Documentation and local Hermes interface reviewed on 2026-10-04. Live integrations remain unverified until the owner supplies strategy and completes provider setup.
