"""Append-only local SQLite store for fetched account suggestions.

Every suggestion fetch keeps the **raw response** (gzip, content-addressed in
`blobs`) plus one `fetches` row (source, url, params, status, timestamp) and
one `suggestions` row per suggested user. Nothing is ever updated or deleted;
a re-fetch adds new rows. No request headers (cookie / csrf) are stored.

Default path: ~/.config/tweetkit/suggestions.sqlite (override: TWEETKIT_DB).
"""
import csv
import gzip
import hashlib
import json
import os
import sqlite3
import time

DEFAULT_DB = os.path.join(os.path.expanduser("~/.config/tweetkit"), "suggestions.sqlite")

SCHEMA = """
CREATE TABLE IF NOT EXISTS blobs (sha TEXT PRIMARY KEY, body_gz BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS fetches (
    id INTEGER PRIMARY KEY, ts TEXT NOT NULL, source TEXT NOT NULL,
    method TEXT, url TEXT, params TEXT, status INTEGER,
    for_user_id TEXT, for_username TEXT, body_sha TEXT REFERENCES blobs(sha));
CREATE TABLE IF NOT EXISTS suggestions (
    id INTEGER PRIMARY KEY, fetch_id INTEGER NOT NULL REFERENCES fetches(id),
    ts TEXT NOT NULL, source TEXT NOT NULL, for_user_id TEXT, for_username TEXT,
    user_id TEXT NOT NULL, username TEXT, name TEXT, bio TEXT,
    followers INTEGER, following INTEGER, verified INTEGER, token TEXT);
CREATE INDEX IF NOT EXISTS ix_sugg_user ON suggestions(user_id);
CREATE INDEX IF NOT EXISTS ix_sugg_for ON suggestions(for_username);
"""

COLUMNS = ["ts", "source", "for_user_id", "for_username", "user_id", "username",
           "name", "bio", "followers", "following", "verified", "token", "fetch_id"]


def _utc():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def connect(path=None):
    path = path or os.environ.get("TWEETKIT_DB") or DEFAULT_DB
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    return db


def save_fetch(db, *, source, method, url, params, status, body, users,
               for_user_id=None, for_username=None):
    """Store one raw response + its parsed users. Returns the fetch id."""
    raw = body.encode() if isinstance(body, str) else (body or b"")
    sha = hashlib.sha256(raw).hexdigest()
    ts = _utc()
    with db:
        db.execute("INSERT OR IGNORE INTO blobs(sha, body_gz) VALUES (?, ?)",
                   (sha, gzip.compress(raw)))
        fid = db.execute(
            "INSERT INTO fetches(ts, source, method, url, params, status, for_user_id,"
            " for_username, body_sha) VALUES (?,?,?,?,?,?,?,?,?)",
            (ts, source, method, url, json.dumps(params, sort_keys=True), status,
             for_user_id, for_username, sha)).lastrowid
        db.executemany(
            "INSERT INTO suggestions(fetch_id, ts, source, for_user_id, for_username, user_id,"
            " username, name, bio, followers, following, verified, token)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(fid, ts, source, for_user_id, for_username, str(u["id"]), u.get("username"),
              u.get("name"), u.get("bio"), u.get("followers"), u.get("following"),
              None if u.get("verified") is None else int(bool(u["verified"])), u.get("token"))
             for u in users])
    return fid


def list_suggestions(db, *, for_username=None, source=None, distinct=False, limit=None):
    """Saved suggestions, newest first. distinct=True keeps only the latest row per user_id."""
    where, args = [], []
    if for_username:
        where.append("lower(for_username) = lower(?)")
        args.append(for_username.lstrip("@"))
    if source:
        where.append("source = ?")
        args.append(source)
    w = f"WHERE {' AND '.join(where)}" if where else ""
    cols = ", ".join(COLUMNS)
    if distinct:
        sql = (f"SELECT {cols} FROM suggestions WHERE id IN "
               f"(SELECT max(id) FROM suggestions {w} GROUP BY user_id) ORDER BY id DESC")
    else:
        sql = f"SELECT {cols} FROM suggestions {w} ORDER BY id DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return [dict(zip(COLUMNS, row)) for row in db.execute(sql, args)]


def export(db, path, fmt=None, **filters):
    """Write saved suggestions to .csv / .json / .jsonl (by extension or fmt). Returns row count."""
    rows = list_suggestions(db, **filters)
    fmt = fmt or os.path.splitext(path)[1].lstrip(".").lower() or "csv"
    tmp = path + ".tmp"
    with open(tmp, "w", newline="") as f:
        if fmt == "csv":
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(rows)
        elif fmt == "jsonl":
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        else:
            json.dump(rows, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return len(rows)
