# Continere private cloud workspace

Production: https://continere-gtm-workspace.vercel.app

## Architecture

Vercel hosts the authenticated dashboard and job API. Upstash Redis stores approved workspace snapshots and queued actions. The private WSL worker polls outward over HTTPS every 15 seconds, executes permitted requests against the loopback-only app and publishes results. There is no tunnel or inbound WSL port. Hermes uses gpt-6-luna with the existing ChatGPT subscription in WSL. No ChatGPT auth files or API keys are uploaded.

The user approved copying prospect details, pasted public reviews, qualification findings, draft scripts, outcome logs, strategy rules and connection-status indicators to private Upstash. Email reply contents, the original PDF, ChatGPT tokens and all API keys remain in WSL. The canonical SQLite database stays in WSL. Saved cloud snapshots can be viewed while WSL is offline; new actions require the computer to be awake and the worker online.

## Access and secrets

Use the new dashboard username `continere` and password from the delivered private access file. Cloud dashboard password, CSRF secret and worker token are separate from ChatGPT credentials and live only in Vercel production environment settings and ignored WSL data files. No secret belongs in source control or browser assets. Upstash was provisioned on `free`, with `autoUpgrade=false`, `eviction=false`, `prodPack=false`. Free-tier quotas still apply.

Deploy only `deploy/vercel`, never the project root. Source uploads exclude .env files, data, the PDF and marketplace helper folders.

## Start after a WSL/computer restart

In WSL terminal 1:

```sh
cd ~/projects/continere-gtm-agent
./start-wsl.sh
```

In WSL terminal 2:

```sh
cd ~/projects/continere-gtm-agent
python3 scripts/cloud_worker.py
```

Keep both running. Worker configuration is private `data/cloud-worker.json`; it contains only the production origin and a new cloud worker token. Errors do not print credentials.

## Approval and interruptions

The cloud UI waits for a private-worker acknowledgment before claiming an action succeeded. Original WSL qualification, duplicate, STOP, text-cap, local-time and human-approval checks remain authoritative. Cloud email sending is disabled on both the API and worker. Spa and Dietitian calls/texts remain manual. No interrupted action is automatically re-delivered or re-executed. Only completion receipts may be retried. An uncertain action requires inspection of saved state before resubmission.

## Verification and redeployment

```sh
cd ~/projects/continere-gtm-agent
python3 -m unittest discover -s tests -q
cd deploy/vercel
node test-cloud.mjs
vercel --prod --yes
```

74 Python tests and 10 cloud checks pass. Live verification: anonymous access 401; signed-in root/state/saved prospects 200; invalid-ICP action queued then rejected by the WSL strategy gate with 400; cloud email sending and bad CSRF rejected with 403; saved Ceremony Spa hook/script present; email reply contents absent.

## CRM

CRM contacts, next actions, draft review and approval are available in the same private cloud dashboard. Email sending remains local-only. The worker excludes CRM email reply bodies, permission evidence text, private notes and Gmail identifiers from snapshots. See [CRM setup](CRM-EMAIL.md).
