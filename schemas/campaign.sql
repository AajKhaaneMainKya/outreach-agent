-- Application schema including separate manual playbook tables; no campaign data.
PRAGMA foreign_keys=ON;

CREATE TABLE deliveries (
          id TEXT PRIMARY KEY, prospect_id TEXT UNIQUE NOT NULL REFERENCES prospects(id),
          recipient TEXT NOT NULL, domain TEXT NOT NULL, status TEXT NOT NULL,
          created TEXT NOT NULL, message_id TEXT, error TEXT);

CREATE TABLE events (
          id INTEGER PRIMARY KEY, prospect_id TEXT, kind TEXT NOT NULL, detail TEXT NOT NULL, created TEXT NOT NULL);

CREATE TABLE manual_contacts (
          id INTEGER PRIMARY KEY, prospect_id TEXT NOT NULL REFERENCES manual_prospects(id),
          action TEXT NOT NULL, created TEXT NOT NULL);

CREATE TABLE manual_logs (
          id INTEGER PRIMARY KEY, prospect_id TEXT NOT NULL REFERENCES manual_prospects(id),
          row TEXT NOT NULL, reply TEXT NOT NULL, created TEXT NOT NULL);

CREATE TABLE manual_prospects (
          id TEXT PRIMARY KEY, business_key TEXT UNIQUE NOT NULL, phone TEXT UNIQUE NOT NULL,
          facts TEXT NOT NULL, draft TEXT NOT NULL, stage TEXT NOT NULL,
          approval_hash TEXT, approved_action TEXT, created TEXT NOT NULL);

CREATE TABLE playbook_candidates (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES playbook_runs(id),
          place_id TEXT UNIQUE NOT NULL, stage TEXT NOT NULL, place TEXT NOT NULL,
          research TEXT NOT NULL, analysis TEXT NOT NULL, facts TEXT NOT NULL,
          manual_id TEXT, created TEXT NOT NULL);

CREATE TABLE playbook_runs (
          id TEXT PRIMARY KEY, settings TEXT NOT NULL, stage TEXT NOT NULL,
          error TEXT, created TEXT NOT NULL);

CREATE TABLE prospects (
          id TEXT PRIMARY KEY, dedupe_key TEXT UNIQUE NOT NULL, run_id TEXT REFERENCES runs(id),
          mode TEXT NOT NULL, name TEXT NOT NULL, website TEXT NOT NULL, domain TEXT NOT NULL,
          email TEXT NOT NULL DEFAULT '', email_source TEXT NOT NULL DEFAULT '',
          contact_verified INTEGER NOT NULL DEFAULT 0, geography_verified INTEGER NOT NULL DEFAULT 0,
          address TEXT NOT NULL, score INTEGER NOT NULL, status TEXT NOT NULL,
          research TEXT NOT NULL, draft TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
          approved_revision INTEGER, approval_hash TEXT, approved_at TEXT,
          gmail_thread TEXT, gmail_id TEXT, created TEXT NOT NULL);

CREATE TABLE replies (
          id TEXT PRIMARY KEY, prospect_id TEXT NOT NULL REFERENCES prospects(id),
          text TEXT NOT NULL, category TEXT NOT NULL, confidence REAL NOT NULL,
          source TEXT NOT NULL, created TEXT NOT NULL);

CREATE TABLE runs (
          id TEXT PRIMARY KEY, mode TEXT NOT NULL, status TEXT NOT NULL,
          geography TEXT NOT NULL, created TEXT NOT NULL, error TEXT,
          settings TEXT NOT NULL, strategy TEXT NOT NULL, processed INTEGER DEFAULT 0);

CREATE TABLE suppressions (
          key TEXT PRIMARY KEY, reason TEXT NOT NULL, created TEXT NOT NULL);
