// SPDX-License-Identifier: Apache-2.0
// Builders for tests.
import type { Card, Detail, Run, Status } from "./types";

export function run(over: Partial<Run> = {}): Run {
  return {
    id: 1, trigger: "page", started_at: 1000, finished_at: null, status: "running",
    phase: null, step: null, steps: null, error: null, ...over,
  };
}

export function status(over: Partial<Status> = {}): Status {
  return {
    version: "0.2", now: 2000, interval_hours: 3, next_fetch_at: 12000, running: null,
    starting: false, last_run: null, error: null, ...over,
  };
}

export function card(name: string, over: Partial<Card> = {}): Card {
  return {
    name, project: "kernel", relation: "mine", subject: `subject of ${name}`, stage: "submitted",
    stages: ["submitted", "accepted"], closed: null, closed_note: null, hidden: false,
    standing: { kind: "none", who: "", since: 0, text: "" }, your_turn: false, unread: false,
    unread_changes: 0, links: [], note: null, pills: [], finished: false, finished_at: null,
    idle: false, last_activity: 0, version: 1, fetched: true, ...over,
  };
}

export function detail(name: string, over: Partial<Detail> = {}): Detail {
  return {
    ...card(name), lore_url: null, revisions: [], steps: [], since: { at: null, changes: [] },
    commits: [], branches: [], failed: [], hint: null, history: [], thread: [], ...over,
  };
}
