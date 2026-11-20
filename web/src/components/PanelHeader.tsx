// SPDX-License-Identifier: Apache-2.0
import { useState } from "react";
import type { ActFn } from "../lib/panel";
import type { Card } from "../types";
import { chipClass } from "./Card";

const REASONS = ["rejected", "dropped", "moved"] as const;

export function PanelHeader(props: { card: Card; loreUrl: string | null; act: ActFn; onClose: () => void }) {
  const { card: c, act } = props;
  const [menu, setMenu] = useState(false);
  const [reason, setReason] = useState<string>("rejected");
  const [note, setNote] = useState("");
  const idx = c.stages.indexOf("applied");
  const canApply = !c.closed && idx >= 0 && c.stages.indexOf(c.stage) < idx;

  async function close() {
    const n = note.trim();
    if (await act("close", n ? { reason, note: n } : { reason })) {
      setMenu(false);
      setNote("");
    }
  }
  return (
    <div className="phead">
      <span className={`chip ${chipClass(c.project)}`}>{c.project}</span>
      <span className="mono muted">{c.name}</span>
      <span className="title">{c.subject}</span>
      {c.closed && <span className="muted">closed: {c.closed}{c.closed_note ? ` · ${c.closed_note}` : ""}</span>}
      <span style={{ flex: 1 }} />
      <button type="button" className="btn" onClick={() => void act(c.unread ? "read" : "unread", {})}>
        {c.unread ? "Mark read" : "Mark unread"}
      </button>
      <button type="button" className="btn" onClick={() => void act(c.hidden ? "unhide" : "hide", {})}>
        {c.hidden ? "Unhide" : "Hide"}
      </button>
      {canApply && <button type="button" className="btn" onClick={() => void act("mark-applied", {})}>Mark applied</button>}
      {!c.closed && (
        <span className="fetch-wrap">
          <button type="button" className="btn" aria-expanded={menu} onClick={() => setMenu(!menu)}>Close…</button>
          {menu && (
            <div className="popover closemenu">
              <label>Reason
                <select aria-label="Reason" value={reason} onChange={(e) => setReason(e.target.value)}>
                  {REASONS.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
              </label>
              <label>Note (optional)
                <input aria-label="Close note" value={note} onChange={(e) => setNote(e.target.value)} />
              </label>
              <button type="button" className="btn" onClick={() => void close()}>Close patch</button>
            </div>
          )}
        </span>
      )}
      {props.loreUrl && <a className="btn" href={props.loreUrl} target="_blank" rel="noopener noreferrer">lore ↗</a>}
      <button type="button" className="x" aria-label="Close panel" onClick={props.onClose}>×</button>
    </div>
  );
}
