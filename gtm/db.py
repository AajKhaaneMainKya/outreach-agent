import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from .config import DATA

def now():
    return datetime.now(timezone.utc).isoformat()

@contextmanager
def connect():
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(DATA / 'campaign.sqlite3', timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def init():
    with connect() as db:
        db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS runs (
          id TEXT PRIMARY KEY, mode TEXT NOT NULL, status TEXT NOT NULL,
          geography TEXT NOT NULL, created TEXT NOT NULL, error TEXT,
          settings TEXT NOT NULL, strategy TEXT NOT NULL, processed INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS prospects (
          id TEXT PRIMARY KEY, dedupe_key TEXT UNIQUE NOT NULL, run_id TEXT REFERENCES runs(id),
          mode TEXT NOT NULL, name TEXT NOT NULL, website TEXT NOT NULL, domain TEXT NOT NULL,
          email TEXT NOT NULL DEFAULT '', email_source TEXT NOT NULL DEFAULT '',
          contact_verified INTEGER NOT NULL DEFAULT 0, geography_verified INTEGER NOT NULL DEFAULT 0,
          address TEXT NOT NULL, score INTEGER NOT NULL, status TEXT NOT NULL,
          research TEXT NOT NULL, draft TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
          approved_revision INTEGER, approval_hash TEXT, approved_at TEXT,
          gmail_thread TEXT, gmail_id TEXT, created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY, prospect_id TEXT, kind TEXT NOT NULL, detail TEXT NOT NULL, created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS suppressions (
          key TEXT PRIMARY KEY, reason TEXT NOT NULL, created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS deliveries (
          id TEXT PRIMARY KEY, prospect_id TEXT UNIQUE NOT NULL REFERENCES prospects(id),
          recipient TEXT NOT NULL, domain TEXT NOT NULL, status TEXT NOT NULL,
          created TEXT NOT NULL, message_id TEXT, error TEXT);
        CREATE TABLE IF NOT EXISTS replies (
          id TEXT PRIMARY KEY, prospect_id TEXT NOT NULL REFERENCES prospects(id),
          text TEXT NOT NULL, category TEXT NOT NULL, confidence REAL NOT NULL,
          source TEXT NOT NULL, created TEXT NOT NULL);
        ''')
        # Network side effects are never replayed after an interrupted process.
        db.execute("UPDATE runs SET status='interrupted', error='App restarted. Completed prospects are saved; start a new run for remaining work.' WHERE status='running'")
        db.execute("UPDATE deliveries SET status='unknown', error='Restart during send; reconcile Gmail manually. Do not retry.' WHERE status='sending'")
        db.execute("UPDATE prospects SET status='send_unknown' WHERE status='sending'")

def event(db, kind, detail, pid=None):
    db.execute('INSERT INTO events(prospect_id,kind,detail,created) VALUES(?,?,?,?)', (pid, kind, detail, now()))

def prospect(row):
    if row is None:
        raise ValueError('Prospect not found')
    p = dict(row)
    p['research'] = json.loads(p['research'])
    p['draft'] = json.loads(p['draft'])
    return p

def get(db, pid):
    return prospect(db.execute('SELECT * FROM prospects WHERE id=?', (pid,)).fetchone())
