// SPDX-License-Identifier: Apache-2.0
import { useMemo, useState } from "react";
import { useApp } from "../app-context";
import { columns, TITLES } from "../lib/board";
import type { Card as CardT } from "../types";
import { Card } from "./Card";

const KEY = "patchtrail.folds";
type Open = Record<string, boolean>; // "stage:idle" / "stage:older"

function loadOpen(): Open {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? "{}");
    return v && typeof v === "object" && !Array.isArray(v) ? v : {};
  } catch {
    return {};
  }
}
function saveOpen(o: Open) {
  try {
    localStorage.setItem(KEY, JSON.stringify(o));
  } catch {
    // storage unavailable: the folds just are not remembered
  }
}

export function Board({ cards }: { cards: CardT[] }) {
  const { route, navigate, clockOffset } = useApp();
  const [open, setOpen] = useState<Open>(loadOpen);
  const now = Date.now() / 1000 + clockOffset;
  const cols = useMemo(() => columns(cards, now), [cards, now]);
  const toggle = (k: string) =>
    setOpen((o) => {
      const n = { ...o, [k]: !o[k] };
      saveOpen(n);
      return n;
    });
  const select = (name: string) => navigate({ name, tab: "overview" });
  const draw = (c: CardT) => (
    <Card key={c.name} card={c} selected={route.name === c.name} onSelect={select} />
  );

  return (
    <div className="board">
      {cols.map((col) => {
        const total = col.cards.length + col.idle.length + col.older.length;
        const fold = (kind: "idle" | "older", list: CardT[]) => {
          if (list.length === 0) return null;
          const k = `${col.stage}:${kind}`;
          return (
            <>
              <button type="button" className="more" aria-expanded={!!open[k]} onClick={() => toggle(k)}>
                +{list.length} {kind}
              </button>
              {open[k] && <div className={kind === "idle" ? "folded idle-fold" : "folded"}>{list.map(draw)}</div>}
            </>
          );
        };
        return (
          <div className="col" key={col.stage} data-stage={col.stage}>
            <div className="h">{TITLES[col.stage]} · {total}</div>
            {col.cards.map(draw)}
            {fold("idle", col.idle)}
            {fold("older", col.older)}
          </div>
        );
      })}
    </div>
  );
}
