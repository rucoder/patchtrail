// SPDX-License-Identifier: Apache-2.0
import { useEffect, useMemo, useRef, useState } from "react";
import { getMails } from "../api";
import { classify, foldDiffs } from "../lib/mailtext";
import { dayTime } from "../lib/time";
import type { Mail, MailGroup } from "../types";

const INDENT = 22;
const MAX_LEVELS = 6;
const errText = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** Bodies are text: every line is a React text child, never HTML. */
function Body({ body }: { body: string }) {
  const [open, setOpen] = useState<Set<number>>(new Set());
  const lines = useMemo(() => {
    const l = body.split("\n");
    if (l[l.length - 1] === "") l.pop();
    return l;
  }, [body]);
  const rows = useMemo(() => foldDiffs(lines), [lines]);
  const out: React.ReactNode[] = [];
  const line = (text: string, cls: string | null, key: string) =>
    out.push(<span key={key} className={cls ?? undefined}>{text + "\n"}</span>);
  rows.forEach((r, i) => {
    if ("fold" in r) {
      if (open.has(r.at)) {
        for (let j = r.at; j < r.at + r.fold; j++) line(lines[j], classify(lines[j]), `f${j}`);
      } else {
        out.push(
          <button key={`b${i}`} type="button" className="btn fold"
            onClick={() => setOpen((s) => new Set(s).add(r.at))}>{`… ${r.fold} more lines`}</button>,
        );
      }
    } else line(r.line, r.cls, `l${i}`);
  });
  return <pre className="mb">{out}</pre>;
}

function MailView({ m, open, onToggle }: { m: Mail; open: boolean; onToggle: () => void }) {
  const first = m.body.split("\n").find((l) => l.trim() !== "" && !l.startsWith(">")) ?? "";
  return (
    <div className={m.new ? "msg new" : "msg"} style={{ marginLeft: Math.min(m.depth, MAX_LEVELS) * INDENT }}>
      <div className="mh" onClick={onToggle} style={{ cursor: "pointer" }}>
        {m.new && <span className="dot" />}
        <span className="who">{m.from_name}{m.you ? " (you)" : ""}</span>
        {!open && <span className="muted snip">{first.slice(0, 100)}</span>}
        <span className="sp" />
        <span className="muted">{dayTime(m.date)}</span>
        <a href={m.lore_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>lore ↗</a>
      </div>
      {open && (
        <>
          <Body body={m.body} />
          {m.omitted > 0 && <div className="muted" style={{ padding: "0 12px 6px" }}>[{m.omitted} non-text parts not shown]</div>}
        </>
      )}
    </div>
  );
}

export function Thread({ name, tick }: { name: string; tick: number }) {
  const [groups, setGroups] = useState<MailGroup[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [toggled, setToggled] = useState<Map<string, boolean>>(new Map());
  const seq = useRef(0);
  useEffect(() => {
    const s = ++seq.current;
    getMails(name).then(
      (r) => { if (s === seq.current) { setGroups(r.groups); setError(null); } },
      (e) => { if (s === seq.current) setError(errText(e)); },
    );
  }, [name, tick]);

  if (error) return <div className="perr bad" role="alert">{error}</div>;
  if (!groups) return <div className="muted">Loading…</div>;
  const all = groups.flatMap((g) => g.mails);
  const isOpen = (m: Mail) => toggled.get(m.msgid) ?? m.new;
  const setAll = (v: boolean) => setToggled(new Map(all.map((m) => [m.msgid, v])));
  const allOpen = all.length > 0 && all.every(isOpen);
  const copy = () => {
    try {
      void navigator.clipboard?.writeText(`ptl open ${name}`)?.catch(() => {});
    } catch { /* no clipboard over plain http */ }
  };
  if (all.length === 0) return <div className="muted">No mails yet.</div>;
  return (
    <div className="thread">
      <div className="thead" style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
        <button type="button" className="btn" onClick={() => setAll(!allOpen)}>{allOpen ? "Collapse all" : "Expand all"}</button>
        <span className="sp" style={{ flex: 1 }} />
        <button type="button" className="btn" onClick={copy}>Open in neomutt: <span className="mono">ptl open {name}</span></button>
      </div>
      {groups.map((g, gi) => (
        <div key={g.label ?? `series${gi}`}>
          {g.label && <h4 className="glabel">{g.label}</h4>}
          {g.mails.map((m) => (
            <MailView key={m.msgid} m={m} open={isOpen(m)}
              onToggle={() => setToggled((t) => new Map(t).set(m.msgid, !isOpen(m)))} />
          ))}
        </div>
      ))}
    </div>
  );
}
