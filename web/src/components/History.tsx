// SPDX-License-Identifier: Apache-2.0
import { dayTime } from "../lib/time";
import type { Detail } from "../types";

export function History({ d }: { d: Detail }) {
  if (d.history.length === 0) return <div className="muted">No history yet.</div>;
  return (
    <div className="tl history">
      {d.history.map((h) => (
        <div key={h.at + ":" + h.changes.map((c) => c.field).join(",")}>
          <span className="muted">{dayTime(h.at)}</span>
          {h.changes.map((c, i) => (
            <span key={i}> · {c.flags ? <b>{c.text}</b> : <span>{c.text}</span>}</span>
          ))}
        </div>
      ))}
    </div>
  );
}
