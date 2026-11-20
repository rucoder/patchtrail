// SPDX-License-Identifier: Apache-2.0
import { useState } from "react";
import type { ActFn } from "../lib/panel";
import { clock, short } from "../lib/time";
import type { BranchRow, Card, Detail } from "../types";
import { LinksNote } from "./LinksNote";

const PREREQ_SHOWN = 8;
const TONE: Record<BranchRow["tone"], string> = { ok: "ok", warn: "warn", bad: "bad", na: "muted" };

function Prereqs({ list }: { list: BranchRow["prereqs"] }) {
  const [all, setAll] = useState(false);
  if (list.length === 0) return null;
  const shown = all ? list : list.slice(0, PREREQ_SHOWN);
  return (
    <div className="prereqs">
      <span className="muted">needs first: </span>
      {shown.map((p) => <div key={p.sha}><span className="mono">{p.sha.slice(0, 12)}</span> <span>{p.text}</span></div>)}
      {list.length > PREREQ_SHOWN && (
        <button type="button" className="more" onClick={() => setAll(!all)}>
          {all ? "show fewer" : `show all (${list.length})`}
        </button>
      )}
    </div>
  );
}

type Commit = Detail["commits"][number];

/** As `ptl ls` says it: Fixes, Cc: stable and where the commit stands in mainline. */
function commitTags(c: Commit): string {
  const tags = c.fixes.map((f) => (f.known
    ? `Fixes: ${f.sha.slice(0, 12)} (${f.release ?? "not released"})`
    : `Fixes: ${f.sha} (unknown commit)`));
  tags.push(c.cc === null ? "no Cc: stable" : `Cc: stable${c.cc ? ` ${c.cc}` : ""}`);
  if (c.mainline) tags.push(c.mainline);
  return tags.join(" · ");
}

/** A kernel patch's commits, its stable table when it follows any branch, and FAILED mails. */
function Kernel({ d, act }: { d: Detail; act: ActFn }) {
  return (
    <>
      {d.commits.length > 0 && (
        <>
          <div className="sec">Commits</div>
          {d.commits.map((c) => (
            <div key={c.sha} className="kc">
              <div><span className="mono">{c.sha.slice(0, 12)}</span> {c.subject}</div>
              <div className="muted">{commitTags(c)}</div>
            </div>
          ))}
        </>
      )}
      {d.branches.length > 0 && <Stable d={d} act={act} />}
      {(d.branches.length > 0 || d.failed.length > 0) && (
        <div className="muted" style={{ marginTop: 6 }}>
          FAILED mails from stable:{" "}
          {d.failed.length === 0 ? "none" : d.failed.map((f, i) => (
            <span key={f.url}>{i > 0 && ", "}<a href={f.url} target="_blank" rel="noopener noreferrer">{f.series} {f.date}</a></span>
          ))}
        </div>
      )}
    </>
  );
}

function Stable({ d, act }: { d: Detail; act: ActFn }) {
  const multi = d.commits.length > 1;
  return (
    <>
      <div className="sec">Stable and longterm</div>
      <table>
        <thead><tr><th>branch</th><th>state</th><th>detail</th><th></th></tr></thead>
        <tbody>
          {d.branches.flatMap((b) => b.rows.map((r, i) => (
            <tr key={`${b.series}:${r.sha}`}>
              <td className="mono">{b.series}{multi && <> <span className="muted">{r.sha.slice(0, 12)}</span></>}</td>
              <td className={TONE[r.tone]}>{r.state.replace(/_/g, " ")}{r.tag ? ` (${r.tag})` : ""}</td>
              <td className="muted">{r.detail.map((l, j) => <div key={j}>{l}</div>)}<Prereqs list={r.prereqs} /></td>
              <td>{i === 0 && (
                <button type="button" className="btn"
                  onClick={() => void act(b.skipped ? "unskip" : "skip", { series: b.series })}>
                  {b.skipped ? "backport again" : "won't backport"}
                </button>
              )}</td>
            </tr>
          )))}
        </tbody>
      </table>
    </>
  );
}

export function Overview({ d, card, act }: { d: Detail; card: Card; act: ActFn }) {
  const changes = d.since.changes;
  const kernel = d.project === "kernel" || d.branches.length > 0;
  return (
    <>
      <div className="trail">
        {d.steps.map((s) => (
          <div key={s.stage} className={s.state === "done" ? "step d" : s.state === "skipped" ? "step skip" : "step"}>
            <div className="o" />
            {s.stage}<br />
            <span className="muted">
              {[s.at !== null ? short(s.at) : null, s.state === "skipped" ? "skipped" : null, s.note].filter(Boolean).join(" · ")}
            </span>
          </div>
        ))}
      </div>
      <div className="cols2">
        <div>
          {changes.length > 0 && (
            <div className="box">
              <b>{d.since.at === null ? "Not read yet" : `Since you read it on ${short(d.since.at)}`}</b>
              {changes.map((c, i) => <div key={i}>{c.text}</div>)}
            </div>
          )}
          {kernel ? <Kernel d={d} act={act} /> : d.commits.length > 0 && (
            <>
              <div className="sec">Commits</div>
              {d.commits.map((c) => (
                <div key={c.sha}>
                  <span className="mono">{c.sha.slice(0, 12)}</span> {c.subject}
                  <span className="muted"> · {c.stage}{c.release ? ` · ${c.release}` : ""}</span>
                </div>
              ))}
            </>
          )}
          {d.hint && <div className="muted hint">{d.hint}</div>}
        </div>
        <div>
          <LinksNote card={card} act={act} />
          {d.thread.length > 0 && (
            <>
              <div className="sec" style={{ marginTop: 12 }}>Thread</div>
              <div className="tl">
                {d.thread.map((m) => (
                  <div key={m.msgid} style={{ marginLeft: Math.min(m.depth, 4) * 22 }}>
                    {m.new && <><span className="dot" /> </>}
                    <span className="muted">{short(m.date)}</span> <b>{m.you ? "you" : m.who}</b> · {m.snippet}
                  </div>
                ))}
              </div>
            </>
          )}
          {d.history.length > 0 && (
            <>
              <div className="sec" style={{ marginTop: 12 }}>History</div>
              <div className="tl muted">
                {d.history.slice(0, 5).map((h) => (
                  <div key={h.at + ":" + h.changes.map((c) => c.field).join(",")}>
                    {short(h.at)} {clock(h.at)} · {h.changes.map((c) => c.text).join(" · ")}
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}
