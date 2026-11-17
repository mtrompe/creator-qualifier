"""SQLite storage for creators, fetched channel data, LLM runs and human labels."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "qualifier.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS creators (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    platform        TEXT NOT NULL,          -- YouTube | Twitch
    channel_url     TEXT NOT NULL UNIQUE,
    audience_note   TEXT,                   -- free text from the outreach sheet
    outreach_priority TEXT,                 -- priority given during outreach (1/2/3/X)
    contacted       INTEGER,                -- 1 if contacted
    replied         INTEGER                 -- 1 if the creator replied
);

-- One row per fetch of a channel from the YouTube / Twitch API (raw JSON kept for traceability)
CREATE TABLE IF NOT EXISTS channel_snapshots (
    id              INTEGER PRIMARY KEY,
    creator_id      INTEGER NOT NULL REFERENCES creators(id),
    fetched_at      TEXT NOT NULL DEFAULT (datetime('now')),
    ok              INTEGER NOT NULL,       -- 0 if the API call failed
    error           TEXT,
    channel_title   TEXT,
    description     TEXT,
    language        TEXT,
    subscribers     INTEGER,                -- YouTube subscribers (NULL on Twitch)
    current_game    TEXT,                   -- Twitch category, if any
    recent_titles   TEXT,                   -- JSON list of recent video / VOD titles
    raw_json        TEXT
);

-- One row per LLM call: which prompt, which model, what it answered, what it cost
CREATE TABLE IF NOT EXISTS llm_runs (
    id              INTEGER PRIMARY KEY,
    creator_id      INTEGER NOT NULL REFERENCES creators(id),
    snapshot_id     INTEGER REFERENCES channel_snapshots(id),
    run_at          TEXT NOT NULL DEFAULT (datetime('now')),
    model           TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,
    fit_score       INTEGER,                -- 1 (no fit) .. 5 (perfect fit)
    output_json     TEXT,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    latency_ms      INTEGER,
    error           TEXT
);

-- Human ground truth: Maxime's own judgement, used to evaluate the LLM
CREATE TABLE IF NOT EXISTS labels (
    creator_id      INTEGER PRIMARY KEY REFERENCES creators(id),
    fit_score       INTEGER NOT NULL,       -- 1..5
    comment         TEXT,
    labeled_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    # v2 columns: activity signals (added after label review showed inactivity mattered)
    cols = {r[1] for r in con.execute("PRAGMA table_info(channel_snapshots)")}
    for name, typ in (("last_upload_at", "TEXT"), ("avg_recent_views", "INTEGER")):
        if name not in cols:
            con.execute(f"ALTER TABLE channel_snapshots ADD COLUMN {name} {typ}")
    return con
