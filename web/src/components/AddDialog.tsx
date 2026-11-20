// SPDX-License-Identifier: Apache-2.0
import { useState, type FormEvent } from "react";
import { addPatch } from "../api";
import type { AddBody } from "../types";

export function AddDialog(props: { onClose: () => void; onAdded: (name: string) => void }) {
  const [name, setName] = useState("");
  const [msgid, setMsgid] = useState("");
  const [links, setLinks] = useState("");
  const [note, setNote] = useState("");
  const [follow, setFollow] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    const body: AddBody = { name: name.trim(), msgid: msgid.trim(), follow };
    const ls = links.split("\n").map((s) => s.trim()).filter(Boolean);
    if (ls.length) body.links = ls;
    if (note.trim()) body.note = note.trim();
    setBusy(true);
    setError(null);
    try {
      const r = await addPatch(body);
      props.onClose();
      props.onAdded(r.name);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <div className="modal-back" onKeyDown={(e) => e.key === "Escape" && props.onClose()}>
      <form className="modal" role="dialog" aria-label="Add thread" onSubmit={submit}>
        <div className="title">Add thread</div>
        <label>Name
          <input value={name} onChange={(e) => setName(e.target.value)} required autoFocus />
        </label>
        <label>Message-ID or lore URL
          <input value={msgid} onChange={(e) => setMsgid(e.target.value)} required />
        </label>
        <label>Links (one per line)
          <textarea rows={3} value={links} onChange={(e) => setLinks(e.target.value)} />
        </label>
        <label>Note
          <input value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
        <label className="check">
          <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />
          someone else's thread
        </label>
        {error && <div className="bad" role="alert">{error}</div>}
        <div className="row">
          <button type="button" className="btn" onClick={props.onClose}>Cancel</button>
          <button type="submit" className="btn on" disabled={busy}>Add</button>
        </div>
      </form>
    </div>
  );
}
