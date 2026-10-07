# Validation record

Checked on 2026-10-04.

## Executed successfully

- 25 automated tests in temporary databases, including HTTP request boundaries, stale approvals, config/strategy changes, evidence freshness, opt-out suppression, duplicate replies, concurrent send clicks, uncertain-send recovery, daily caps, bounce circuit breaker, provider pagination and SSRF rejection.
- Python compilation for the application and scripts.
- JavaScript syntax check for the dashboard.
- Hermes worker offline library-contract check using the installed Hermes v0.16.0, upstream `24832009`, Python 3.11.13. Imports and required constructor parameters passed.
- Local HTTP server and dashboard render.
- Browser walkthrough in an isolated test database: load six fictional providers → open a provider → verify demo contact and geography → save revision 2 → attest and approve → confirm demo Send remains disabled → record opt-out → confirm “Do not contact” and disabled approval/edit actions.
- Visual inspection of the overview and review drawer. Desktop layout and the narrower in-app layout rendered. No external fonts, asset network dependencies, or build step.

## Not exercised with real accounts

- Live Hermes model inference, successful native delegation, subscription eligibility, model access and rate limits. The adapter checks actual delegation results at runtime and rejects incomplete output.
- Google Places billable search and real website research as a combined live campaign. Provider HTTP calls were mocked in tests.
- Google OAuth consent, token refresh, Gmail sends, and real Gmail reply synchronization. Delivery was mocked; no actual email was sent.
- Domain DNS authentication, mailbox reputation or jurisdiction-specific campaign review. Readiness is an owner attestation.

Complete the README setup and run one live prospect before increasing the batch size. Keep `ALLOW_SEND=false` until an actual approved live draft is ready and Gmail is explicitly connected. The ZIP is a clean source bundle, without the working database, tokens, actual strategy, or personal configuration.

## Private Vercel deployment
74 Python tests and 10 Node cloud checks passed. No tunnel. Source PDF and ChatGPT credentials stay local. User-authorized workspace records mirrored to private Upstash. Production root/state/prospects verified with authentication, anonymous access blocked, and invalid-ICP queued request rejected by the private worker. Cloud email send disabled.
