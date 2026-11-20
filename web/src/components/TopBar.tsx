// SPDX-License-Identifier: Apache-2.0
import { useState } from "react";
import { scope, type Filters, type View } from "../lib/filters";
import { clock, dayTime } from "../lib/time";
import type { Card, Status } from "../types";
import { AddDialog } from "./AddDialog";
import { FetchButton } from "./FetchButton";

type Props = {
  status: Status | null;
  patches: Card[];
  filters: Filters;
  onFilters: (f: Filters) => void;
  onStatus: (s: Status) => void;
  onRefresh: () => void;
  onAdded: (name: string) => void;
  connError?: string | null; // the service cannot be reached
  clockOffset?: number;
};

export function TopBar({ status, patches, filters, onFilters, onStatus, onRefresh, onAdded, connError = null, clockOffset = 0 }: Props) {
  const [adding, setAdding] = useState(false);
  const projects = [...new Set(patches.map((c) => c.project))].sort();
  const inScope = scope(patches, filters);
  const unread = inScope.filter((c) => c.unread).length;
  const turn = inScope.filter((c) => c.your_turn).length;
  // last_run: the newest full run that finished ok. error: a newer full run that did not.
  const fetched = status?.last_run ? (status.last_run.finished_at ?? status.last_run.started_at) : null;
  const err = status?.error ?? null;
  const errText = err && `last fetch ${err.status === "interrupted" ? "interrupted" : "failed"} ` +
    `${dayTime(err.at)}${err.error ? `: ${err.error}` : ""}`;
  const times: string[] = [];
  if (fetched !== null) times.push(`fetched ${clock(fetched)}`);
  if (status?.next_fetch_at != null) times.push(`next ${clock(status.next_fetch_at)}`);

  const chip = (label: string, on: boolean, click: () => void) => (
    <button type="button" key={label} className={on ? "btn on" : "btn"} onClick={click}>{label}</button>
  );

  return (
    <div className="bar">
      <b>patchtrail</b>
      {chip("All", filters.project === null, () => onFilters({ ...filters, project: null }))}
      {projects.map((p) => chip(p, filters.project === p, () => onFilters({ ...filters, project: p })))}
      {chip(`Unread only · ${unread}`, filters.unread, () => onFilters({ ...filters, unread: !filters.unread }))}
      {chip(`Your turn · ${turn}`, filters.turn, () => onFilters({ ...filters, turn: !filters.turn }))}
      <select className="btn" aria-label="View" value={filters.view}
        onChange={(e) => onFilters({ ...filters, view: e.target.value as View })}>
        <option value="open">Open</option>
        <option value="hidden">Hidden</option>
        <option value="closed">Closed</option>
      </select>
      <span className="sp" />
      {connError && <span className="bad">cannot reach the service: {connError}</span>}
      {errText && <span className="bad">{errText}</span>}
      {times.length > 0 && <span className="muted">{times.join(" · ")}</span>}
      <button type="button" className="btn" onClick={() => setAdding(true)}>Add thread</button>
      <FetchButton status={status} onStatus={onStatus} onRefresh={onRefresh}
        clockOffset={clockOffset} />
      {adding && <AddDialog onClose={() => setAdding(false)} onAdded={onAdded} />}
    </div>
  );
}
