// SPDX-License-Identifier: Apache-2.0
import type { Card } from "../types";

export const COLUMNS = ["submitted", "reviewed", "accepted", "applied", "released", "backports"] as const;
export type Stage = (typeof COLUMNS)[number];
export const TITLES: Record<Stage, string> = {
  submitted: "Submitted", reviewed: "Reviewed", accepted: "Accepted",
  applied: "Applied", released: "Released", backports: "Backports",
};
export const OLDER_DAYS = 30;

export type Column = { stage: Stage; cards: Card[]; idle: Card[]; older: Card[] };

const order = (a: Card, b: Card) =>
  Number(b.unread) - Number(a.unread) || b.last_activity - a.last_activity;

/**
 * Split the cards into the six columns. `older` (finished more than 30 days ago) and `idle`
 * (idle) are folds of read cards: an unread card never folds. A card is in at most one
 * list, older taking precedence.
 */
export function columns(cards: Card[], now: number): Column[] {
  const cutoff = now - OLDER_DAYS * 86400;
  return COLUMNS.map((stage) => {
    const mine = cards.filter((c) => c.stage === stage).sort(order);
    const isOlder = (c: Card) =>
      c.finished && c.finished_at !== null && c.finished_at < cutoff && !c.unread;
    const isIdle = (c: Card) => c.idle && !c.unread && !isOlder(c);
    return {
      stage,
      older: mine.filter(isOlder),
      idle: mine.filter(isIdle),
      cards: mine.filter((c) => !isOlder(c) && !isIdle(c)),
    };
  });
}
