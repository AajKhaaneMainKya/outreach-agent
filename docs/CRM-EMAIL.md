# CRM and requested email follow-up

The CRM is a tab in the existing dashboard for Spa, Dietitian and Rehab. It tracks the business, named contact, email, stage, next action/date, notes, permission, drafts and activity. Add a saved research result through Add a contact, or enter a business manually. Domain deduplication prevents duplicate businesses; this first version stores one primary contact per business.

## Intended workflow

1. Research and make the playbook-approved manual call/text.
2. If the recipient asks for information by email, record the requested address, verify it, choose the request source and record the evidence in CRM.
3. Prepare the follow-up using VJ's approved email template. The existing Hermes orchestrator can also use `continere_prepare_followup` when explicitly asked for a follow-up on that same CRM-linked prospect. It cannot grant consent, choose a recipient, approve or send.
4. Read the exact draft and approve its revision.
5. From the WSL-local dashboard, separately click Send approved email.
6. Sync replies, review responses and record the next action. With follow-up sending enabled, the local server checks sent Gmail threads every two minutes. It checks again before another send. There are no automated follow-up sequences.

Permission is for one requested email. Changing the address clears permission; editing the contact/settings clears approval. A fresh specific request can authorize a new email, but an uncertain prior delivery blocks further attempts. Replies after a request require review and fresh permission before another email. STOP/unsubscribe suppresses immediately across the applicable contact/domain; quoted previous unsubscribe footers are not treated as a new opt-out. Provider errors never trigger an automatic send retry.

## Email setup

The selected sender is `vijai@continerehealth.com`. In CRM > Email setup enter the sender name, valid business postal address, domain-readiness confirmation, approved subject/body, VJ as approver and the approval source/reference. Wording is supplied and attested by the operator; the app does not obtain approval from VJ or invent an email strategy from the call/text PDF. Leave templates blank until approved. Optional placeholders are `$business`, `$contact_name`, `$sender_name`, `$website`; a postal address and reply-unsubscribe instruction are appended.

Install Gmail dependencies if needed and place the OAuth desktop-client file in ignored `data/google-client.json` (or the configured private path). After approving a real requested follow-up, connect privately in WSL:

```sh
cd ~/projects/continere-gtm-agent
python3 -m pip install -r requirements-gmail.txt
python3 scripts/connect_gmail.py --crm
```

Sign in as the configured sender. The connected Gmail profile must match the sender. OAuth scopes permit sending and reading Gmail; tokens stay in WSL, out of Git and cloud snapshots.

Only when ready, set `ALLOW_FOLLOWUP_SEND=true` in `~/.config/outreach-agent/runtime.env` and restart the app. This switch is separate from Rehab's `ALLOW_SEND`. Default daily CRM cap is five network attempts, configurable 1–20, counted in UTC. Domain-readiness confirmation is a human attestation, not an automatic SPF/DKIM/DMARC audit.

This feature is for requested follow-ups, not unsolicited campaign sending. VJ's original Spa/Dietitian calls and texts remain manual and retain their existing guards.

## Private cloud and data

The SQLite CRM is in ignored WSL `data/campaign.sqlite3`; additive tables preserve all existing research and contact history. The Vercel CRM supports adding contacts, recording permission, preparing drafts and approval through the outward-only worker. Sending, reply-body entry and Gmail reply sync are local only. Cloud snapshots exclude reply bodies, permission evidence text, private notes, Gmail message/thread identifiers and tokens. Stage/action dates, public prospect/contact details, draft emails and redacted activity remain viewable.

The computer must stay awake for local research, Gmail operations and cloud updates. No new inbound tunnel, Resend, Apollo or paid sending platform is added.

## Limits

One primary contact per business; one email per recorded request. Unknown deliveries require manual Gmail reconciliation and cannot be retried in this version. Bounce detection covers delivery-failure messages on tracked Gmail threads and is not a complete cross-provider webhook service. Plain-text replies are supported; HTML-only replies may need manual review. Consent and VJ approval are operator attestations and must have real supporting evidence.
