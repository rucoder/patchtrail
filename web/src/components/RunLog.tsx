// SPDX-License-Identifier: Apache-2.0
import { useEffect, useRef, useState } from "react";
import { getRunLog } from "../api";
import { clock } from "../lib/time";
import type { RunLogLine } from "../types";

const POLL_MS = 2000;

/** Popover with a run's log lines; polls while the run is still running. */
export function RunLog(props: { runId: number | null; running: boolean; onClose: () => void }) {
  const { runId, running, onClose } = props;
  const [lines, setLines] = useState<RunLogLine[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const after = useRef(0);
  const seenRun = useRef<number | null>(null);

  useEffect(() => {
    if (runId === null) return;
    if (seenRun.current !== runId) {
      seenRun.current = runId;
      after.current = 0;
      setLines([]);
    }
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      try {
        const { lines: more } = await getRunLog(runId, after.current);
        if (stop) return;
        setErr(null);
        if (more.length) {
          after.current = more[more.length - 1].n;
          setLines((old) => [...old, ...more]);
        }
      } catch (e) {
        if (stop) return;
        setErr(e instanceof Error ? e.message : String(e));
      }
      if (!stop && running) timer = setTimeout(tick, POLL_MS);
    };
    void tick();
    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, [runId, running]);

  return (
    <div className="popover" role="dialog" aria-label="Run log">
      <div className="mh">
        <span className="who">{runId === null ? "Run log" : `Run ${runId} log`}</span>
        <span className="sp" />
        <span className="btn" role="button" tabIndex={0} onClick={onClose}
          onKeyDown={(e) => e.key === "Enter" && onClose()}>close</span>
      </div>
      <pre className="mb">
        {runId === null && "waiting for the run to start…"}
        {runId !== null && lines.length === 0 && !err && "no log lines yet"}
        {lines.map((l) => `${clock(l.at)}  ${l.line}\n`).join("")}
      </pre>
      {err && <div className="bad">{err}</div>}
    </div>
  );
}
