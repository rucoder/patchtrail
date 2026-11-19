CREATE TABLE patches (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  project TEXT NOT NULL DEFAULT 'unknown',
  project_override INTEGER NOT NULL DEFAULT 0,
  relation TEXT NOT NULL DEFAULT 'mine' CHECK (relation IN ('mine','following')),
  hidden INTEGER NOT NULL DEFAULT 0,
  closed TEXT CHECK (closed IN ('rejected','dropped','moved')),
  closed_note TEXT,
  manual_applied INTEGER NOT NULL DEFAULT 0,
  force_stable INTEGER NOT NULL DEFAULT 0,
  tree_url TEXT, tree_branch TEXT,
  tree_source TEXT CHECK (tree_source IN ('manual','auto')),
  read_snapshot_id INTEGER REFERENCES snapshots(id) ON DELETE SET NULL,
  prev_read_snapshot_id INTEGER REFERENCES snapshots(id) ON DELETE SET NULL,
  flagged INTEGER NOT NULL DEFAULT 0,
  read_on_first_snapshot INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL
);
CREATE TABLE revisions (
  id INTEGER PRIMARY KEY,
  patch_id INTEGER NOT NULL REFERENCES patches(id) ON DELETE CASCADE,
  root_msgid TEXT NOT NULL UNIQUE,
  version INTEGER NOT NULL DEFAULT 1,
  subject TEXT NOT NULL,
  author TEXT,                       -- lowercased address
  posted_at INTEGER,
  change_id TEXT,
  kind TEXT NOT NULL DEFAULT 'series' CHECK (kind IN ('series','backport')),
  branch TEXT                        -- '6.1' for kind='backport'
);
CREATE TABLE mails (
  msgid TEXT PRIMARY KEY,            -- without <>
  revision_id INTEGER NOT NULL REFERENCES revisions(id) ON DELETE CASCADE,
  in_reply_to TEXT, date INTEGER NOT NULL DEFAULT 0,
  from_name TEXT, from_addr TEXT, subject TEXT,
  raw BLOB NOT NULL, first_seen INTEGER NOT NULL
);
CREATE TABLE commits (
  id INTEGER PRIMARY KEY,
  patch_id INTEGER NOT NULL REFERENCES patches(id) ON DELETE CASCADE,
  sha TEXT NOT NULL, subject TEXT,
  source TEXT NOT NULL CHECK (source IN ('applied-mail','search','manual')),
  UNIQUE (patch_id, sha)
);
CREATE TABLE branch_skips (
  patch_id INTEGER NOT NULL REFERENCES patches(id) ON DELETE CASCADE,
  series TEXT NOT NULL, PRIMARY KEY (patch_id, series)
);
CREATE TABLE snapshots (
  id INTEGER PRIMARY KEY,
  patch_id INTEGER NOT NULL REFERENCES patches(id) ON DELETE CASCADE,
  taken_at INTEGER NOT NULL, state TEXT NOT NULL      -- JSON, see Task 6
);
CREATE TABLE ignored (msgid TEXT PRIMARY KEY);         -- roots of deleted patches
CREATE TABLE runs (
  id INTEGER PRIMARY KEY, pid INTEGER, trigger TEXT NOT NULL,
  started_at INTEGER NOT NULL, finished_at INTEGER,
  status TEXT NOT NULL CHECK (status IN ('running','ok','failed','interrupted')),
  phase TEXT, step INTEGER, steps INTEGER, error TEXT
);
CREATE TABLE run_log (run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                      at INTEGER NOT NULL, line TEXT NOT NULL);
CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX revisions_patch ON revisions(patch_id);
CREATE INDEX mails_revision ON mails(revision_id);
CREATE INDEX snapshots_patch ON snapshots(patch_id);
