# Agent Platform (multi-tenant)

A browser-based version of the commission-tracker built for **other insurance agents** —
starting with Ethan's brother, then more if it works for him.

This is a **separate project** from Ethan's personal `commission-tracker`. Nothing here
touches that system, and nothing there touches this. It began as a code-only copy of the
engine (no client data, no credentials) and evolves independently.

## How it differs from Ethan's personal system

| | Ethan's system (`commission-tracker`) | This (agent-platform) |
|---|---|---|
| Data in | Local watcher + Claude agent auto-ingest | Agent **drags files into the website** |
| Storage | Local parquet + his Google Sheet | **In-app, isolated per agent** |
| Users | Just Ethan (one PIN) | **Many agents, each sees only their own book** |
| Alerts | iMessage texts to his phone | In-app only (no texting rig) |
| CRM | GoHighLevel | none |
| Carrier data | Auto-scraped from portals | Agent uploads carrier CSVs |

## What carries over (works from an upload alone)
Active book · renewals · losses · past-due · commissions & disputes · **AOR Defense**
(the "taken by another agent" data is in the HealthSherpa export's AOR column, so no
scraping is needed).

## What's dropped (needs Ethan's local rig)
iMessage alerts · GoHighLevel · carrier-portal auto-scraping · launchd watchers.

## Architecture
- **Engine reused as-is:** `tracker/` (ingest, diff, commissions, pastdue, aor_defense,
  carriers, carrier_status, carrier_truth, dashboard, reconcile, supplemental).
- **Per-tenant storage:** `tenants/<agent_id>/snapshots/…` — the same parquet pipeline,
  scoped to the logged-in agent. Gitignored (never committed).
- **Upload in-app:** Streamlit file-uploader → `tracker.ingest` → that agent's folder → render.
- **Auth:** simple per-agent login; multi-tenant from day one.

## Build roadmap
- [ ] **1. Tenant shell** — login, per-agent data folders, session scoping
- [ ] **2. Upload flow** — drag-drop HealthSherpa/carrier CSV → ingest into the agent's folder
- [ ] **3. Port pages** — book, renewals, losses, past-due, commissions, AOR Defense
      (strip the Sheets/GHL/iMessage wiring from the copied `app.py` / `report.py`)
- [ ] **4. Onboard brother** — first real account, real data, feedback
- [ ] **5. Grow** — add accounts; revisit hosting/billing only if it proves out

## Status
Scaffolded 2026-07-16. Engine + reference `app.py` copied. Multi-tenant refactor not started yet.
