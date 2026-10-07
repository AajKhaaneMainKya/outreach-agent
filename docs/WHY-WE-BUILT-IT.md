# Why we built Outreach agent

Created By Rahul for Continere.

## The problem

A bootstrapped team needs to find suitable businesses, understand the available evidence and prepare outreach without paying for a large sales platform. A form that asks the operator to supply every fact does not solve that problem. Nor does a model that invents prospects, reviews or generic copy.

## What we wanted

Start with a simple mission such as finding dietitian practices in Florida. Let discovery and specialist research teams gather public evidence, evaluate the documented ICP and prepare VJ's fixed outreach template. Show the operator the result, what supports it, what remains unknown and the next action. Save each prospect and outcome so the work does not need to be entered again.

The first implementation was a Rehab POC. Spa and Dietitian were added as separate strategy modules without removing that work. One modular dashboard avoids separate applications for every ICP.

## Why this design

Hermes provides subscription-backed inference, delegation and bounded tool use. We use the owner's ChatGPT/Codex subscription rather than silently falling back to a paid inference API. Separate specialist roles help divide research, qualification and policy checking; actual handoffs appear in Messages. Multiple prospect teams can investigate concurrently, while each keeps its evidence scoped to the correct business.

WSL keeps the runnable project and credentials on a Linux filesystem. The optional private cloud dashboard receives approved workspace data through an outward-polling worker; the WSL installation remains private. Credentials, authentication tokens and the original PDF are excluded from Git and cloud assets.

The playbook remains authoritative. Deterministic checks and human approval protect exact wording, source integrity, contact history and suppression. A compelling-looking draft is not permission to send. Spa/Dietitian calls and texts remain manual.

## What we learned

Search quality is the main bottleneck. Directory pages must resolve to real practices. A search result is a lead, not qualification evidence. Website testimonials cannot be assumed to be five-star Google reviews. Adding more agents does not fix missing sources or a search workflow that stops too early.

The current pipeline still has bounded first-success search and missing-evidence budgets. It can return fewer qualified prospects than requested, and review retrieval can remain incomplete. These limitations are visible; no quality or full-autonomy claim is made.

## Budget-conscious next improvements

Research identified the official Brave Search API plus the existing local browser as a practical option, with SearXNG as a self-hosted alternative and Google Places as optional structured enrichment. These are proposals, not implemented integrations.

The proposed next search iteration should split state searches across cities, resolve business identity before qualification, inspect team/services pages before review enrichment, make targeted follow-up queries, turn verified review sources into structured evidence and continue until the qualified target or explicit budget is reached. VJ's script wording should remain unchanged.

Success should be measured on real practice discovery, supported qualification, correct business identity, usable verified hooks and honest incomplete outcomes, rather than the number of agents or volume of generated text.
