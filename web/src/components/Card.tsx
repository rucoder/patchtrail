// SPDX-License-Identifier: Apache-2.0
import type { KeyboardEvent } from "react";
import type { Card as CardT } from "../types";

const CHIP: Record<string, string> = { kernel: "k", qemu: "q", grub: "g", "erofs-utils": "e", liburing: "l" };
export const chipClass = (project: string) => CHIP[project.toLowerCase()] ?? "";

type Props = { card: CardT; selected: boolean; onSelect: (name: string) => void };

export function Card({ card: c, selected, onSelect }: Props) {
  const cls = ["crd", c.unread ? "u" : "", selected ? "sel" : "", c.idle ? "idle" : ""].filter(Boolean).join(" ");
  const key = (e: KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onSelect(c.name);
    }
  };
  const badge = c.unread_changes > 0 ? String(c.unread_changes) : c.unread ? "new" : null;
  return (
    <div className={cls} role="button" tabIndex={0} aria-pressed={selected}
      onClick={() => onSelect(c.name)} onKeyDown={key}>
      <span className={`chip ${chipClass(c.project)}`}>{c.project}</span>
      {badge !== null && <> <span className="badge">{badge}</span></>}
      {c.relation === "following" && <> <span className="muted following">following</span></>}
      <div className="t">{c.name}</div>
      <div className="standing">
        {c.your_turn && <span className="turn">your turn</span>}
        {c.your_turn && c.standing.text && " "}
        {c.standing.text && <span className="muted">{c.your_turn ? "· " : ""}{c.standing.text}</span>}
      </div>
      {c.links.length > 0 && (
        <div className="muted links">{c.links.map((l) => l.label).join(" · ")}</div>
      )}
      {c.pills.length > 0 && (
        <div className="pills">
          {c.pills.map((p) => (
            <span key={p.series} className={`pill p-${p.tone}`} title={`${p.series}: ${p.state}`}>{p.series}</span>
          ))}
        </div>
      )}
    </div>
  );
}
