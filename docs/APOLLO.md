# Apollo contacts in WSL

Apollo adds individual contact discovery at a selected practice. It does not replace practice qualification, Google review research or VJ's fixed scripts. This integration never creates Apollo contacts/sequences, approves outreach or sends messages.

## Create and save a scoped key

In Apollo, open Settings > Integrations > API Keys and create a key for People API Search (`mixed_people/api_search`) and, only if desired, People Enrichment (`people/match`). Prefer endpoint-scoped permissions rather than a master key. Account access varies; free people-search access requires work-email registration and may have further eligibility restrictions.

In your WSL terminal:

```sh
cd ~/projects/continere-gtm-agent
python3 scripts/apollo_contacts.py configure
python3 scripts/apollo_contacts.py check
```

The configure command prompts for the key without showing it, preserving other private settings. It writes `~/.config/outreach-agent/runtime.env` with permissions 600; a custom `GTM_ENV_FILE` is supported. Never paste the key into chat, a browser form, GitHub or source files. Restart the WSL app after saving it. A successful auth health check does not establish endpoint eligibility; test search next.

## Search people without enrichment

```sh
python3 scripts/apollo_contacts.py search --website https://YOUR-PRACTICE-DOMAIN --title owner --title founder --limit 5
```

Replace the domain with the real selected business. The API search endpoint is documented as zero credits. It does not return email addresses or phone numbers, and names can be partly obscured. Domain filters can include previous employers: verify current employment and buyer role before choosing anyone.

The Spa/Dietitian contact-search specialist has `continere_apollo_contacts`, scoped to the selected practice domain and two requests per prospect mission, five results per request. It reports contacts and limitations in Messages. A missing key does not block the existing research workflow. Apollo does not infer staff counts or qualify an ICP.

Search and enrichment records stay in ignored `data/apollo/contacts.sqlite3` with permissions 600. They are not automatically copied into prospect records, email recipients or cloud snapshots. Specialist summaries may appear in the existing Messages board. Apollo remains optional; the first integration supports practice-scoped contact lookup, not standalone nationwide people discovery or a contact management screen.

## Explicit work-email enrichment

Enrichment consumes credits when chargeable data is found. Check Apollo's current allowance/pricing first. Enable `ALLOW_APOLLO_ENRICHMENT=true` in the private runtime.env only when wanted; `APOLLO_DAILY_ENRICHMENT_LIMIT=5` defaults to five attempts per UTC day and is restricted to 1–20. This is an attempt cap, not a dollar cap or account-wide allowance. Failed calls count conservatively and are not automatically retried.

Use a person ID from the saved search for that exact business:

```sh
python3 scripts/apollo_contacts.py enrich --website https://YOUR-PRACTICE-DOMAIN --person-id RETURNED_ID --confirm-credit-use
```

Personal email, phone reveal and waterfall are explicitly false. Returned phones/personal emails are discarded. Only Apollo-verified email matching the selected current employer domain is retained; other results stay incomplete. The agent has no enrichment tool and no authority to spend enrichment credits. Cached retained emails avoid repeated enrichment.

Apollo contact availability is not permission to reach out. VJ's Spa/Dietitian calls/texts still use the verified GMB business number, never personal cells. Individual email outreach for those modules requires an approved strategy from VJ; this addition does not authorize a new channel. Rehab's existing email gates remain unchanged.

## Troubleshooting

401 means the key was rejected; 403 can mean missing endpoint permissions or account eligibility; 429 means the rate limit was reached. Provider errors are sanitized, with no raw response or key output. No redirect forwarding, webhook, inbound tunnel, automatic retry or paid fallback is configured.

Official references: [Create a key](https://docs.apollo.io/docs/create-api-key), [People API Search](https://docs.apollo.io/reference/people-api-search), [People Enrichment](https://docs.apollo.io/reference/people-enrichment), [Pricing and credits](https://docs.apollo.io/docs/api-pricing).
