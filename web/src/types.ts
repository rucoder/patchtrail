// SPDX-License-Identifier: Apache-2.0
// Mirrors the API contract (see src/patchtrail/views.py).

export type Run = {
  id: number;
  trigger: "cli" | "schedule" | "page" | "api";
  started_at: number;
  finished_at: number | null;
  status: "running" | "ok" | "failed" | "interrupted";
  phase: string | null;
  step: number | null;
  steps: number | null;
  error: string | null;
};

export type Status = {
  version: string;
  now: number;
  interval_hours: number;
  next_fetch_at: number | null; // newest run's started_at + interval; now if no run yet
  running: Run | null; // the run in progress, from any process
  starting: boolean; // the service started a child whose run row isn't written yet
  last_run: Run | null; // newest run that has finished
  error: { run_id: number; at: number; error: string } | null; // newest failed run, if no ok run after it
};

export type Link = { url: string; label: string };
export type Pill = { series: string; state: string; tone: "ok" | "warn" | "bad" | "na" };
export type Standing = { kind: string; who: string; since: number; text: string };

export type Card = {
  name: string;
  project: string;
  relation: "mine" | "following";
  subject: string;
  stage: string;
  stages: string[]; // stages the project declares
  closed: "rejected" | "dropped" | "moved" | null;
  closed_note: string | null;
  hidden: boolean;
  standing: Standing;
  your_turn: boolean;
  unread: boolean;
  unread_changes: number; // flagging changes since read
  links: Link[];
  note: string | null;
  pills: Pill[];
  finished: boolean;
  finished_at: number | null; // start of the newest unbroken finished streak
  idle: boolean;
  last_activity: number; // newest mail date, 0 if none
  version: number; // newest series revision's version, 1 if none
  fetched: boolean; // has a snapshot
};

export type ChangeT = { field: string; text: string; flags: boolean };
export type Step = {
  stage: string;
  state: "done" | "todo" | "skipped";
  at: number | null;
  note: string | null;
};
export type Prereq = {
  sha: string;
  subject: string;
  tag: string | null;
  stable: boolean;
  text: string;
};
export type BranchRow = {
  sha: string;
  state: string;
  tag: string | null;
  tone: Pill["tone"];
  detail: string[];
  prereqs: Prereq[];
};

export type Detail = Card & {
  lore_url: string | null;
  revisions: {
    version: number;
    msgid: string;
    subject: string;
    posted_at: number | null;
    kind: "series" | "backport";
    branch: string | null;
  }[];
  steps: Step[];
  since: { at: number | null; changes: ChangeT[] }; // at null: never read
  commits: {
    sha: string;
    subject: string;
    where: string | null;
    stage: string;
    release: string | null;
    cc: string | null;
    fixes: { sha: string; release: string | null; known: boolean }[];
  }[];
  branches: { series: string; skipped: boolean; rows: BranchRow[] }[]; // kernel only, newest series first
  failed: { series: string; date: string; url: string }[];
  hint: string | null;
  history: { at: number; changes: ChangeT[] }[]; // newest first
  thread: {
    msgid: string;
    depth: number;
    date: number;
    who: string;
    you: boolean;
    snippet: string;
    new: boolean;
  }[]; // overview summary, tree order
};

export type Mail = {
  msgid: string;
  parent: string | null;
  depth: number;
  date: number;
  from_name: string;
  from_addr: string;
  you: boolean;
  subject: string;
  new: boolean;
  body: string;
  omitted: number;
  lore_url: string;
};
export type MailGroup = { label: string | null; mails: Mail[] };

// Bodies and extra answers (not part of the table of shared types).
export type RunLogLine = { n: number; at: number; line: string };
export type AddBody = {
  name: string;
  msgid: string;
  follow?: boolean;
  note?: string;
  links?: string[];
};
export type AddResult = {
  name: string;
  msgid: string;
  project: string;
  stage: string | null;
  standing: string | null;
  links: unknown;
  note: string | null;
  url: string;
};
export type CloseBody = { reason: string; note?: string };
export type Action =
  | "read"
  | "unread"
  | "hide"
  | "unhide"
  | "close"
  | "mark-applied"
  | "skip"
  | "unskip"
  | "links";
