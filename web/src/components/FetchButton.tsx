// SPDX-License-Identifier: Apache-2.0
import { useEffect, useRef, useState } from "react";
import { ApiError, fetchNow } from "../api";
import { elapsed } from "../lib/time";
import type { Run, Status } from "../types";
import { RunLog } from "./RunLog";

type Props = {
  status: Status | null;
  onStatus: (s: Status) => void; // a fresh Status from the 202 answer
  onRefresh: () => void; // ask the app to re-read the status now
  clockOffset?: number; // server clock minus this browser's clock, seconds
};

function progress(run: Run | null, now: number): string {
  if (!run) return "starting…";
  const parts = [run.phase ?? "starting…"];
  if (run.step !== null && run.steps !== null) parts.push(`step ${run.step} of ${run.steps}`);
  parts.push(elapsed(run.started_at, now));
  return parts.join(" · ");
}

export function FetchButton({ status, onStatus, onRefresh, clockOffset = 0 }: Props) {
  const [pending, setPending] = useState(false); // clicked, no newer status yet
  const [conflict, setConflict] = useState<Run | null>(null); // progress from a 409
  const [error, setError] = useState<string | null>(null);
  // The popover belongs to the run that was clicked; it stays until the user closes it.
  const [log, setLog] = useState<{ id: number | null } | null>(null);
  const [, tick] = useState(0);
  const inflight = useRef(false);
  const first = useRef(true);

  // A new status ends the optimistic states.
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    setPending(false);
    setConflict(null);
  }, [status]);

  const run = status?.running ?? conflict;
  useEffect(() => {
    if (!log || !run) return;
    if (log.id === null) setLog({ id: run.id }); // clicked while starting: adopt the run
    else if (log.id !== run.id) setLog(null); // a different run: never open by itself
  }, [log, run]);

  const busy = !!run || !!status?.starting || pending;

  useEffect(() => {
    if (!busy) return;
    const t = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [busy]);

  async function click() {
    if (inflight.current) return;
    inflight.current = true;
    setPending(true);
    setError(null);
    try {
      onStatus(await fetchNow());
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        const r = (e.body as { running?: Run | null } | null)?.running ?? null;
        setConflict(r);
        setPending(r === null); // no run row yet: still "starting…"
        onRefresh();
      } else {
        setPending(false);
        setError(e instanceof Error ? e.message : String(e));
      }
    } finally {
      inflight.current = false;
    }
  }

  const popover = log && (
    <RunLog key="log" runId={log.id} running={!!run && run.id === log.id && run.status === "running"}
      onClose={() => setLog(null)} />
  );
  if (!busy) {
    return (
      <span className="fetch-wrap">
        <button type="button" className="btn" onClick={click}>Fetch now</button>
        {error && <span className="bad">{error}</span>}
        {popover}
      </span>
    );
  }
  const toggle = () => setLog(log ? null : { id: run?.id ?? null });
  return (
    <span className="fetch-wrap">
      <span className="btn on" tabIndex={0} title="Show the run log" onClick={toggle}
        onKeyDown={(e) => e.key === "Enter" && toggle()}>
        {progress(run, Date.now() / 1000 + clockOffset)}
      </span>
      {popover}
    </span>
  );
}
