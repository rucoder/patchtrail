// SPDX-License-Identifier: Apache-2.0
import { useState, type FormEvent, type KeyboardEvent } from "react";
import type { ActFn } from "../lib/panel";
import type { Card } from "../types";

const isHttp = (u: string) => /^https?:\/\//i.test(u);

export function LinksNote({ card, act }: { card: Card; act: ActFn }) {
  const [url, setUrl] = useState("");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  async function add(e: FormEvent) {
    e.preventDefault();
    const u = url.trim();
    if (!u) return;
    if (await act("links", { add: [u] })) setUrl("");
  }
  async function save() {
    const t = draft.trim();
    if (await act("setNote", { note: t === "" ? null : t })) setEditing(false);
  }
  const key = (e: KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      void save();
    } else if (e.key === "Escape") {
      e.stopPropagation();
      setEditing(false);
    }
  };

  return (
    <div className="linksnote">
      <div className="sec">Links and note</div>
      <div className="lnk">
        {card.links.map((l) => (
          <span key={l.url} className="btn">
            {isHttp(l.url)
              ? <a href={l.url} target="_blank" rel="noopener noreferrer">{l.label}</a>
              : <span>{l.label}</span>}
            {" "}
            <button type="button" className="x" aria-label={`Remove ${l.label}`}
              onClick={() => void act("links", { remove: [l.url] })}>×</button>
          </span>
        ))}
        <form className="addlink" onSubmit={add}>
          <input aria-label="Add link" placeholder="https://…" value={url} onChange={(e) => setUrl(e.target.value)} />
          <button type="submit" className="btn">Add</button>
        </form>
      </div>
      <div className="note">
        {editing ? (
          <>
            <input aria-label="Note" autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={key} />
            <button type="button" className="btn" onClick={() => void save()}>Save</button>
            <button type="button" className="btn" onClick={() => setEditing(false)}>Cancel</button>
          </>
        ) : card.note ? (
          <span className="editable" role="button" tabIndex={0} title="Edit note"
            onClick={() => { setDraft(card.note ?? ""); setEditing(true); }}
            onKeyDown={(e) => { if (e.key === "Enter") { setDraft(card.note ?? ""); setEditing(true); } }}>{card.note}</span>
        ) : (
          <button type="button" className="btn" onClick={() => { setDraft(""); setEditing(true); }}>Add note</button>
        )}
      </div>
    </div>
  );
}
