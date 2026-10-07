# Outreach agent

Created By Rahul. Ownership fingerprint: `3a7e5b80cda31154` ([OWNER.json](OWNER.json)). This identifier is attribution, not authentication.

A WSL-hosted, multi-agent outreach workspace built for Continere. A plain-language mission starts discovery and prospect research; specialist teams collect evidence, assess qualification, prepare VJ's fixed scripts and check the result. Spa, Dietitian and the earlier Rehab POC share one dashboard.

## Why we built it

Small teams need a practical way to turn a marketing playbook into researched prospects and usable outreach without buying a large sales stack or repeatedly filling forms. We built this to keep the strategy, evidence, specialist handoffs, draft review and outcome history together. See [the build notes](docs/WHY-WE-BUILT-IT.md) for the decisions and current limitations.

## Architecture

- Discovery finds public business leads and resolves directory results to individual practice websites.
- Up to three prospect teams work concurrently. Each coordinates research, qualification, fixed-template writing and QA, with specialists for missing review, qualification and contact evidence.
- Messages records actual work summaries, questions, responses and source references. It does not expose private model reasoning.
- Only the orchestrator saves validated findings. Agents cannot approve or contact prospects.
- Deterministic application checks enforce human approval, STOP suppression, contact history and the playbook's contact rules.
- The optional Vercel dashboard uses Upstash snapshots and an outward-polling WSL worker. No inbound tunnel is required. See [cloud setup](docs/vercel.md).

## Start in WSL

Python 3.11+ is required. Keep the runnable project on Ubuntu's filesystem:

```sh
cd ~/projects/outreach-agent
./start-wsl.sh
```

Open http://127.0.0.1:8765/. The owner's existing installation remains at `~/projects/continere-gtm-agent`; it has not been moved or reset.

**Fresh clones require the authorized original strategy PDF**, intentionally excluded from Git. Place it at `knowledge/GMB-Outbound-Playbook-Spa-Dietitian.pdf`. Expected SHA-256: `03c16e24995d0f362a277377b794c81f280e92ae3e7eb17df676ce875d20321b`. The application checks both the PDF and policy digest; Spa/Dietitian policy operations fail closed without the matching source. Do not bypass this check or invent replacement policy. Rehab requires its own approved strategy in the ignored `config/strategy.json`, based on the example.

## Private configuration and integrations

```sh
install -d -m 700 ~/.config/outreach-agent
# Only on a fresh setup; do not overwrite an existing runtime.env.
cp .env.example ~/.config/outreach-agent/runtime.env
chmod 600 ~/.config/outreach-agent/runtime.env
```

The application reads this private file, or a custom `GTM_ENV_FILE`. The legacy project `.env` is only a fallback. Runtime databases, OAuth files and local worker settings remain under ignored `data/`; do not commit them. Hermes credentials are private and must never be copied into source.

Install Hermes separately in WSL using its official setup. Sign in with its `hermes model` command and select the OpenAI Codex / ChatGPT subscription provider. The owner's current profile uses `gpt-6-luna`; availability depends on the account. The worker refuses paid OpenAI API fallback. Check integration with:

```sh
~/.hermes/hermes-agent/venv/bin/python scripts/hermes_worker.py --check
```

For the existing Hermes layout, install no-key search support:

```sh
~/.hermes/hermes-agent/venv/bin/python -m pip install -r requirements-search.txt
```

For optional local browser retrieval:

```sh
python3 -m venv data/browser-venv
data/browser-venv/bin/python -m pip install -r requirements-browser.txt
data/browser-venv/bin/python -m playwright install chromium
```

OS browser dependencies may also be required. Google Places is optional and requires a privately configured key and billing account; no billing is enabled by this application. Gmail belongs to the earlier Rehab workflow and requires separate OAuth setup and approval; sending defaults off.

## Strategy and approval

`config/playbook.json` implements VJ's Spa/Dietitian operational rules. The original PDF remains the authority. Preserve its fixed two-week free offer, money line, program/link rules, hooks, objections and outcomes. Do not generate alternate copy.

Calls and texts are manual and require human approval. Use only the verified business GMB number, never personal cells. Texts are manual, restricted to 8am–8pm prospect-local time and at most two, with immediate STOP suppression. No drug names, results claims or in-clinic treatment claims. Uncovered legal, pricing and new-ICP questions go to VJ. Agents cannot certify line type or newest-review ordering without the required verification.

## Current limitations

No-key search uses ordered DuckDuckGo, Brave and Mojeek backends through DDGS; it is not the official Brave API. Public page and review access can fail. A campaign pool is a bounded number of investigations, not a guarantee of that many qualified prospects. Missing evidence stays unknown, and missing verified hooks remain placeholders with approval blocked. Google Places returns a limited relevance-sorted review sample, which cannot establish the five newest reviews.

The recently researched official Brave API, SearXNG and improved qualification-target search loop are proposals, not installed features. See the build notes.

## Verify

With the authorized PDF installed:

```sh
python3 -m unittest discover -s tests -q
node --check static/playbook.js
node deploy/vercel/test-cloud.mjs
```

The repository contains source, policy, prompts, schemas, UI, deployment code and tests. It excludes credentials, saved prospects, outcomes, private settings, original PDF and runtime environments. A fresh clone does not include the owner's live workspace data.
