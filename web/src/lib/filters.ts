// SPDX-License-Identifier: Apache-2.0
import type { Card } from "../types";

export type View = "open" | "hidden" | "closed";
export type Filters = { project: string | null; unread: boolean; turn: boolean; view: View };
export const defaultFilters: Filters = { project: null, unread: false, turn: false, view: "open" };

export function inView(c: Card, view: View): boolean {
  if (view === "closed") return c.closed !== null;
  if (view === "hidden") return c.hidden && c.closed === null;
  return !c.hidden && c.closed === null;
}

/** Cards in the chosen view and project: what the unread and your-turn counts are over. */
export function scope(cards: Card[], f: Filters): Card[] {
  return cards.filter((c) => inView(c, f.view) && (f.project === null || c.project === f.project));
}

/** Cards the board shows: scope plus the unread and your-turn toggles. */
export function visible(cards: Card[], f: Filters): Card[] {
  return scope(cards, f).filter((c) => (!f.unread || c.unread) && (!f.turn || c.your_turn));
}
